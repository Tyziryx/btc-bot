"""
Polymarket BTC 15-min Legging Arbitrage Bot — Pro-Enhanced v2

Strategy (two paths):
  1. Instant Arb  — combined ask < MAX_COMBINED_COST → buy both sides, guaranteed profit
  2. Legging Arb  — confidence > threshold → buy leg1 (signal direction), hunt for leg2
     Leg2 found:  guaranteed profit = $1 - combined_cost - fee
     Leg2 not found (window expires): resolve directionally — token pays $1 or $0

Signal stack:
  TFI: Trade Flow Imbalance (Polymarket) — net dollar flow from book + trade events
  OBI: Order Book Imbalance (Polymarket) — bid/ask pressure at top-N levels
  Binance OFI: real-time orderbook imbalance from Binance — primary directional signal
  Confidence: composite [0-100], Binance OFI acts as multiplier

Loss management:
  - Binance OFI stop-loss: if OFI strongly reverses against leg1 → abandon early at mark price
  - Directional resolution: if leg2 not found, token resolves to $1 or $0 at window end
    (formerly: always deducted -$2 on abandonment — now only lose if direction was wrong)
"""

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.arb_config import ArbConfig
from bot.polymarket import (
    find_market, get_market_price, MarketInfo, ClobWebSocket,
)


# ─── State constants ──────────────────────────────────────────────────────────
IDLE = "IDLE"
LEG1_OPEN = "LEG1_OPEN"


@dataclass
class Leg:
    """A single executed leg (kept for instant-arb path)."""
    side: str
    token_id: str
    price: float
    size: float
    cost: float
    timestamp: float
    window_id: int


@dataclass
class ArbPosition:
    """Legging arb position — leg1 enters on signal, leg2 completes the arb."""
    leg1: Leg
    leg2: Leg | None = None
    status: str = "open"   # "open" | "complete" | "win" | "lose" | "abandoned"
    profit: float = 0.0
    window_id: int = 0
    exit_price: float = 0.0   # Used when resolving leg1 directionally at window end


class ArbTrader:
    def __init__(self, config: ArbConfig | None = None, capital: float = 100.0):
        self.config = config or ArbConfig()

        # Capital
        self.capital = capital
        self.initial_capital = capital

        # State machine
        self.state = IDLE
        self.current_position: ArbPosition | None = None
        self.positions: list[ArbPosition] = []

        # Stats
        self.wins = 0
        self.losses = 0
        self.arbs_completed = 0   # instant arbs
        self.arbs_abandoned = 0
        self.total_profit = 0.0
        self.ticks = 0

        # ── Signal buffers ────────────────────────────────────────────────
        # Two separate deques to avoid double-counting across signal sources
        self._tfi_book_events: deque[tuple[float, float]] = deque()   # from price_change
        self._tfi_trade_events: deque[tuple[float, float]] = deque()  # from last_trade_price
        self._last_tfi: float = 0.0
        self._last_obi: float = 0.0
        self._last_confidence: float = 0.0
        self._last_direction: str = "NONE"

        # Current market
        self._current_market: MarketInfo | None = None
        self._next_market: MarketInfo | None = None
        self._next_window_subscribed: bool = False

        # Window tracking
        self._current_window: int = 0
        self._trades_this_window: int = 0

        # WS + Binance
        self._ws: ClobWebSocket | None = None
        self._binance = None   # BinanceFeed, lazy-imported

        # Graceful shutdown flag (set by signal handler)
        self._shutdown: bool = False

        # ── Logging setup ─────────────────────────────────────────────────
        os.makedirs(self.config.DATA_DIR, exist_ok=True)
        self.log_path = os.path.join(self.config.DATA_DIR, "arb_trades.jsonl")

        logs_dir = os.path.join(self.config.DATA_DIR, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        start_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        try:
            import subprocess
            git_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            git_hash = "unknown"
        self._log_file_path = os.path.join(
            logs_dir, "arb_%s_%s.log" % (start_ts, git_hash))
        self._log_file = open(self._log_file_path, "a", buffering=1)

    # ─── Logging ─────────────────────────────────────────────────────────────

    def _log(self, message: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = "%s %s" % (ts, message)
        print(line)
        self._log_file.write(line + "\n")

    def _log_decision(self, action: str, **kwargs):
        """Emit a structured DECISION event — parsed by dashboard log_reader."""
        payload = {"action": action}
        for k, v in kwargs.items():
            payload[k] = round(v, 4) if isinstance(v, float) else v
        self._log("DECISION %s" % json.dumps(payload))

    def _save_trade(self, trade: dict):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(trade) + "\n")

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _window_id(ts: float | None = None) -> int:
        t = int(ts or time.time())
        return (t // 900) * 900

    def _seconds_remaining_in_window(self) -> int:
        now = int(time.time())
        return max(0, self._current_window + 900 - now)

    # ─── Signal: Trade Flow Imbalance (TFI) ──────────────────────────────────
    #
    # On Polymarket 15-min binary markets, actual trade executions (last_trade_price)
    # are extremely rare — the market maker reprices via price_change events, not fills.
    # Strategy: use SEPARATE deques for each source to avoid double-counting, then combine.
    #
    #   _tfi_book_events  — from price_change (order placement/cancellation pressure)
    #   _tfi_trade_events — from last_trade_price (actual fills, rare but high-quality)
    #
    # Final TFI = book_signal + trade_signal (trades weighted 2× to reflect higher signal quality)

    def _on_ws_price_change(self, asset_id: str, changes: list):
        """Feed TFI from order placement / cancellation events.

        Interprets:
          BUY side (bids) on UP token   → bullish pressure (+)
          BUY side (bids) on DOWN token → bearish pressure (-)
          SELL side (asks) on UP token  → bearish pressure (-) when asks grow
          SELL side (asks) on DOWN token→ bullish pressure (+) when DOWN asks grow (DOWN cheapening)

        Size=0 means level removed (opposite pressure — weighted negatively).
        """
        now = time.time()
        market = self._current_market
        if not market:
            return

        for change in changes:
            side = change.get("side", "")
            size = float(change.get("size", 0))
            # Level removed (size=0) = opposite of addition; skip size=0 to avoid noise
            if size == 0:
                continue

            if side == "BUY":
                # New bid placed
                delta = size if asset_id == market.up_token_id else -size
            else:
                # New ask placed — ask on UP = sell pressure (bearish); ask on DOWN = UP pressure
                delta = -size if asset_id == market.up_token_id else size

            self._tfi_book_events.append((now, delta))

    def _on_ws_trade(self, asset_id: str, price: str, size: str):
        """TFI feed: actual trade executions (rare on Polymarket, high-quality signal).
        UP token trade = bullish (+), DOWN token trade = bearish (-).
        """
        try:
            trade_size = float(size)
        except (ValueError, TypeError):
            return

        market = self._current_market
        if not market:
            return

        now = time.time()
        if asset_id == market.up_token_id:
            delta = trade_size
        elif asset_id == market.down_token_id:
            delta = -trade_size
        else:
            return
        self._tfi_trade_events.append((now, delta))

    def _compute_tfi(self) -> tuple[float, int, int]:
        """Compute TFI from both book changes and trade executions.

        Returns (tfi_value, book_event_count, trade_event_count).
        Trades are weighted 2× because they are higher-quality signal.
        """
        now = time.time()
        cutoff = now - self.config.OFI_WINDOW_S

        while self._tfi_book_events and self._tfi_book_events[0][0] < cutoff:
            self._tfi_book_events.popleft()
        while self._tfi_trade_events and self._tfi_trade_events[0][0] < cutoff:
            self._tfi_trade_events.popleft()

        book_signal = sum(d for _, d in self._tfi_book_events)
        trade_signal = sum(d for _, d in self._tfi_trade_events)

        # Trades weighted 2× — actual fills > passive order placement
        self._last_tfi = book_signal + (trade_signal * 2.0)
        return self._last_tfi, len(self._tfi_book_events), len(self._tfi_trade_events)

    # ─── Signal: Order Book Imbalance (OBI) ──────────────────────────────────

    def _compute_obi(self) -> float:
        """Order Book Imbalance: net pressure from top-N bid/ask levels.

        Returns net_obi in [-1, +1]:
          +1 = strong UP buy pressure (UP bids heavy vs UP asks, DOWN asks heavy vs DOWN bids)
          -1 = strong DOWN buy pressure
           0 = balanced

        Formula: ((UP_bid - UP_ask) - (DOWN_bid - DOWN_ask)) / total_vol
        """
        market = self._current_market
        if not market or not self._ws:
            return 0.0

        depth = self.config.OBI_DEPTH

        def _book_imbalance(token_id: str) -> float:
            """Compute single-token OBI. Falls back to REST if WS book is empty."""
            book = self._ws.get_book(token_id)
            bids = book["bids"][:depth]
            asks = book["asks"][:depth]

            # WS book empty — use REST orderbook as fallback (called at most once per tick)
            if not bids and not asks:
                try:
                    from bot.polymarket import get_orderbook
                    rest = get_orderbook(token_id)
                    bids = rest.get("bids", [])[:depth]
                    asks = rest.get("asks", [])[:depth]
                except Exception:
                    return 0.0

            bid_vol = sum(float(b.get("size", 0)) for b in bids)
            ask_vol = sum(float(a.get("size", 0)) for a in asks)
            total = bid_vol + ask_vol
            return (bid_vol - ask_vol) / total if total > 0 else 0.0

        up_imb = _book_imbalance(market.up_token_id)
        down_imb = _book_imbalance(market.down_token_id)

        # Net OBI: UP_pressure - DOWN_pressure, normalized to [-1, +1]
        self._last_obi = (up_imb - down_imb) / 2.0
        return self._last_obi

    # ─── Signal: Confidence Score ─────────────────────────────────────────────

    def _compute_confidence(self, tfi: float, obi: float) -> tuple[float, str]:
        """Composite confidence score [0-100] and trade direction.

        Algorithm:
        1. Normalize TFI to [0,1] using OFI_THRESHOLD as saturation point
        2. OBI magnitude is already [0,1]
        3. Weight: TFI_WEIGHT * tfi_mag + OBI_WEIGHT * obi_mag → base score
        4. Direction agreement multiplier: same sign = ×1.0, diverging = ×0.15
        5. Binance multiplier (if enabled): agree = ×BOOST, disagree = ×PENALTY

        Returns (score 0-100, direction "UP"/"DOWN"/"NONE")
        """
        cfg = self.config

        tfi_mag = min(1.0, abs(tfi) / max(1.0, cfg.OFI_THRESHOLD))
        obi_mag = min(1.0, abs(obi))

        tfi_dir = 1 if tfi > 0 else (-1 if tfi < 0 else 0)
        obi_dir = 1 if obi > 0 else (-1 if obi < 0 else 0)

        base = (cfg.TFI_WEIGHT * tfi_mag + cfg.OBI_WEIGHT * obi_mag) * 100

        # Determine direction + agreement multiplier
        if tfi_dir == 0 and obi_dir == 0:
            return 0.0, "NONE"
        elif tfi_dir == obi_dir:
            score = base * 1.0
            direction = "UP" if tfi_dir > 0 else "DOWN"
        elif tfi_dir == 0:
            # Only OBI signal — less confidence
            score = base * 0.60
            direction = "UP" if obi_dir > 0 else "DOWN"
        elif obi_dir == 0:
            # Only TFI signal — less confidence
            score = base * 0.60
            direction = "UP" if tfi_dir > 0 else "DOWN"
        else:
            # Diverging signals — heavily penalized, no clear direction
            score = base * 0.15
            direction = "NONE"

        # Binance lead-lag multiplier
        if cfg.BINANCE_ENABLED and self._binance and self._binance.connected:
            binfo = self._binance.get_signal()
            bs = binfo["signal"]
            if bs != 0 and direction != "NONE":
                signal_dir = 1 if direction == "UP" else -1
                if bs == signal_dir:
                    score *= cfg.BINANCE_AGREE_BOOST
                else:
                    score *= cfg.BINANCE_DISAGREE_PENALTY

        self._last_confidence = min(100.0, round(score, 1))
        self._last_direction = direction
        return self._last_confidence, direction

    # ─── Price getters (WS with REST fallback) ───────────────────────────────

    def _get_up_ask(self) -> float | None:
        market = self._current_market
        if not market:
            return None
        if self._ws and self._ws.connected and self._ws.has_data(market.up_token_id):
            return self._ws.best_ask(market.up_token_id)
        price = get_market_price(market.up_token_id, side="SELL")
        return price if 0.01 < price < 0.99 else None

    def _get_down_ask(self) -> float | None:
        market = self._current_market
        if not market:
            return None
        if self._ws and self._ws.connected and self._ws.has_data(market.down_token_id):
            return self._ws.best_ask(market.down_token_id)
        price = get_market_price(market.down_token_id, side="SELL")
        return price if 0.01 < price < 0.99 else None

    # ─── State Machine ────────────────────────────────────────────────────────

    def _tick(self, market: MarketInfo):
        """One tick through the state machine.
        Computes TFI, OBI, confidence score, then dispatches to state handler.
        """
        self.ticks += 1

        tfi, tfi_book_n, tfi_trade_n = self._compute_tfi()
        obi = self._compute_obi()
        confidence, direction = self._compute_confidence(tfi, obi)

        up_ask = self._get_up_ask()
        down_ask = self._get_down_ask()

        remaining = self._seconds_remaining_in_window()
        combined_str = "%.3f" % (up_ask + down_ask) if up_ask and down_ask else "n/a"
        ws_status = "WS" if (self._ws and self._ws.connected) else "REST"

        binance_str = ""
        if self.config.BINANCE_ENABLED and self._binance:
            binfo = self._binance.get_signal()
            binance_str = " bnb=%+.4f(s=%d)" % (binfo["momentum_3m"], binfo["signal"])

        self._log(
            "TICK window=%d | state=%s tfi=%+.1f(b%d/t%d) obi=%+.3f conf=%.0f "
            "up_ask=%s down_ask=%s combined=%s remain=%ds [%s]%s"
            % (
                self._current_window, self.state,
                tfi, tfi_book_n, tfi_trade_n, obi, confidence,
                "%.3f" % up_ask if up_ask else "none",
                "%.3f" % down_ask if down_ask else "none",
                combined_str, remaining, ws_status, binance_str,
            )
        )

        if self.state == IDLE:
            self._tick_idle(market, tfi, obi, confidence, direction, up_ask, down_ask, remaining)
        elif self.state == LEG1_OPEN:
            self._tick_leg1_open(market, up_ask, down_ask, remaining)

    def _tick_idle(
        self,
        market: MarketInfo,
        tfi: float,
        obi: float,
        confidence: float,
        direction: str,
        up_ask: float | None,
        down_ask: float | None,
        remaining: int,
    ):
        """IDLE: instant arb if combined < threshold, else directional bet on confidence."""
        cfg = self.config

        if remaining < cfg.MIN_WINDOW_REMAINING_S:
            return
        if self._trades_this_window >= cfg.MAX_TRADES_PER_WINDOW:
            return
        if up_ask is None or down_ask is None:
            return

        combined = up_ask + down_ask

        # ── Path 1: instant riskless arb ─────────────────────────────────
        if combined < cfg.MAX_COMBINED_COST:
            gross = 1.0 - combined
            fee = (cfg.BET_SIZE * 2) * cfg.POLYMARKET_FEE
            min_shares = min(cfg.BET_SIZE / up_ask, cfg.BET_SIZE / down_ask)
            estimated_net = round(gross * min_shares - fee, 4)
            self._log("INSTANT_ARB combined=%.3f gross=%.4f est_net=$%.4f — buying both sides"
                      % (combined, gross, estimated_net))
            self._log_decision("INSTANT_ARB", combined=combined, estimated_net=estimated_net)
            self._execute_instant_arb(market, up_ask, down_ask)
            return

        # ── Path 2: confidence-based leg1 entry ──────────────────────────
        if confidence < cfg.CONFIDENCE_THRESHOLD:
            if self.ticks % 6 == 0:
                self._log_decision("SKIP", reason="LOW_CONFIDENCE",
                                   score=confidence, threshold=cfg.CONFIDENCE_THRESHOLD,
                                   tfi=tfi, obi=obi, dir=direction)
            return

        if direction == "NONE":
            self._log_decision("SKIP", reason="DIVERGENT_SIGNALS",
                               score=confidence, tfi=tfi, obi=obi)
            return

        leg1_price = up_ask if direction == "UP" else down_ask
        leg1_token = market.up_token_id if direction == "UP" else market.down_token_id

        if leg1_price is None or leg1_price <= 0:
            return

        if leg1_price > cfg.LEG1_MAX_PRICE:
            self._log_decision("SKIP", reason="LEG1_TOO_EXPENSIVE",
                               price=leg1_price, max=cfg.LEG1_MAX_PRICE)
            return

        shares = cfg.BET_SIZE / leg1_price
        leg1 = Leg(
            side=direction,
            token_id=leg1_token,
            price=leg1_price,
            size=round(shares, 2),
            cost=round(cfg.BET_SIZE, 4),
            timestamp=time.time(),
            window_id=self._current_window,
        )
        self.current_position = ArbPosition(leg1=leg1, window_id=self._current_window)
        self.state = LEG1_OPEN
        self._trades_this_window += 1

        self._log_decision("ENTER_LEG1", side=direction, score=confidence,
                           tfi=tfi, obi=obi, price=leg1_price)
        self._log("LEG1 %s @ %.3f ($%.2f, %.1f shares) | conf=%.0f tfi=%+.1f obi=%+.3f remain=%ds"
                  % (direction, leg1_price, cfg.BET_SIZE, shares,
                     confidence, tfi, obi, remaining))

    def _tick_leg1_open(
        self,
        market: MarketInfo,
        up_ask: float | None,
        down_ask: float | None,
        remaining: int,
    ):
        """LEG1_OPEN: hunt for cheap opposite side + Binance OFI stop-loss."""
        pos = self.current_position
        if pos is None:
            self.state = IDLE
            return

        leg1 = pos.leg1
        opposite_side = "DOWN" if leg1.side == "UP" else "UP"
        opp_ask = down_ask if opposite_side == "DOWN" else up_ask
        opp_token = market.down_token_id if opposite_side == "DOWN" else market.up_token_id

        if opp_ask is None:
            return

        combined = leg1.price + opp_ask
        elapsed = time.time() - leg1.timestamp

        self._log("  HUNTING leg2=%s opp_ask=%.3f combined=%.3f target<%.3f elapsed=%.0fs"
                  % (opposite_side, opp_ask, combined, self.config.MAX_COMBINED_COST, elapsed))

        # ── Leg 2 opportunity ─────────────────────────────────────────────
        if combined < self.config.MAX_COMBINED_COST and opp_ask <= self.config.LEG2_MAX_PRICE:
            shares = self.config.BET_SIZE / opp_ask
            leg2 = Leg(
                side=opposite_side,
                token_id=opp_token,
                price=opp_ask,
                size=round(shares, 2),
                cost=round(self.config.BET_SIZE, 4),
                timestamp=time.time(),
                window_id=self._current_window,
            )
            pos.leg2 = leg2
            pos.status = "complete"

            total_cost_price = leg1.price + leg2.price
            gross_per_share = 1.0 - total_cost_price
            min_shares = min(leg1.size, leg2.size)
            gross_dollar = gross_per_share * min_shares
            total_notional = leg1.cost + leg2.cost
            fee_dollar = total_notional * self.config.POLYMARKET_FEE
            net_profit = round(gross_dollar - fee_dollar, 4)

            pos.profit = net_profit
            self.capital += net_profit
            self.total_profit += net_profit
            self.arbs_completed += 1

            self._log(
                "LEG2 %s @ %.3f | COMPLETE combined=%.3f gross=$%.4f fee=$%.4f "
                "net=$%.4f capital=$%.2f"
                % (opposite_side, opp_ask, combined,
                   gross_dollar, fee_dollar, net_profit, self.capital)
            )
            self._log_decision("COMPLETE_LEG2", side=opposite_side,
                               combined=combined, net=net_profit)

            self.positions.append(pos)
            self._save_trade(self._position_to_dict(pos))
            self.current_position = None
            self.state = IDLE
            return

        # ── Binance OFI stop-loss ─────────────────────────────────────────
        cfg = self.config
        if (elapsed > cfg.STOP_LOSS_MIN_ELAPSED_S
                and cfg.BINANCE_ENABLED
                and self._binance and self._binance.connected):
            binance_ofi = self._binance.ofi
            # If Binance OFI is strongly against our leg1 direction → cut loss early
            if leg1.side == "UP" and binance_ofi < cfg.BINANCE_OFI_STOP_LOSS:
                self._log("STOP_LOSS: Binance OFI=%.3f strongly bearish vs UP leg" % binance_ofi)
                self._abandon_position("binance_ofi_stop_loss (ofi=%.3f)" % binance_ofi)
                return
            elif leg1.side == "DOWN" and binance_ofi > -cfg.BINANCE_OFI_STOP_LOSS:
                self._log("STOP_LOSS: Binance OFI=%.3f strongly bullish vs DOWN leg" % binance_ofi)
                self._abandon_position("binance_ofi_stop_loss (ofi=%.3f)" % binance_ofi)
                return

        # ── Timeout ───────────────────────────────────────────────────────
        if elapsed > cfg.LEG2_TIMEOUT_S:
            # Don't abandon — let it resolve directionally at window end
            self._log("LEG2 timeout (%.0fs) — holding leg1 to window resolution" % elapsed)
            return

        # ── Window expiring — resolve directionally ────────────────────────
        if remaining < cfg.WINDOW_EXPIRY_ABANDON_S:
            self._log("Window expiring (%ds) — resolving leg1 directionally" % remaining)
            self._resolve_position()

    def _resolve_position(self):
        """Resolve a directional position at window end.
        Checks final token bid price to determine WIN or LOSE.
        """
        pos = self.current_position
        if pos is None:
            self.state = IDLE
            return

        leg = pos.leg1

        # Get final token bid (what market pays us now)
        exit_price = None
        if self._ws and self._ws.connected and self._ws.has_data(leg.token_id):
            exit_price = self._ws.best_bid(leg.token_id)
        if not exit_price:
            try:
                p = get_market_price(leg.token_id, side="BUY")
                exit_price = p if 0.01 < p < 0.99 else None
            except Exception:
                pass

        exit_price = exit_price or 0.0
        pos.exit_price = exit_price

        if exit_price > 0.80:
            # Token converging to $1 → we won
            gross = (1.0 - leg.price) * leg.size
            fee = leg.cost * self.config.POLYMARKET_FEE
            pos.profit = round(gross - fee, 4)
            pos.status = "win"
            self.wins += 1
        elif exit_price > 0.20:
            # Uncertain — mark-to-market
            pnl = (exit_price - leg.price) * leg.size
            pos.profit = round(pnl, 4)
            pos.status = "win" if pnl > 0 else "lose"
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
        else:
            # Token converging to $0 → we lost
            pos.profit = round(-leg.cost, 4)
            pos.status = "lose"
            self.losses += 1

        self.capital += pos.profit
        self.total_profit += pos.profit

        self._log("%s %s | entry=%.3f exit=%.3f profit=$%+.4f capital=$%.2f"
                  % (pos.status.upper(), leg.side,
                     leg.price, exit_price, pos.profit, self.capital))
        self._log_decision(pos.status.upper(), side=leg.side,
                           entry=leg.price, exit=exit_price, profit=pos.profit)

        self.positions.append(pos)
        self._save_trade(self._position_to_dict(pos))
        self.current_position = None
        self.state = IDLE

    def _execute_instant_arb(
        self, market: MarketInfo, up_ask: float, down_ask: float
    ):
        """Buy both sides atomically when combined < MAX_COMBINED_COST."""
        up_shares = self.config.BET_SIZE / up_ask
        down_shares = self.config.BET_SIZE / down_ask

        leg1 = Leg("UP", market.up_token_id, up_ask,
                   round(up_shares, 2), self.config.BET_SIZE, time.time(), self._current_window)
        leg2 = Leg("DOWN", market.down_token_id, down_ask,
                   round(down_shares, 2), self.config.BET_SIZE, time.time(), self._current_window)

        combined = up_ask + down_ask
        gross_per_share = 1.0 - combined
        min_shares = min(up_shares, down_shares)
        gross_dollar = gross_per_share * min_shares
        # Correct fee: notional-based
        total_notional = leg1.cost + leg2.cost
        fee_dollar = total_notional * self.config.POLYMARKET_FEE
        net_profit = round(gross_dollar - fee_dollar, 4)

        pos = ArbPosition(leg1=leg1, leg2=leg2, status="complete",
                          profit=net_profit, window_id=self._current_window)
        self.capital += net_profit
        self.total_profit += net_profit
        self.arbs_completed += 1
        self._trades_this_window += 1

        self._log("INSTANT_ARB UP@%.3f + DOWN@%.3f = %.3f | gross=$%.4f fee=$%.4f net=$%.4f capital=$%.2f"
                  % (up_ask, down_ask, combined, gross_dollar, fee_dollar, net_profit, self.capital))

        self.positions.append(pos)
        self._save_trade(self._position_to_dict(pos))

    def _abandon_position(self, reason: str):
        """Abandon a position early (stop-loss / window change without resolution).
        Marks at current bid if available, else records full loss.
        """
        pos = self.current_position
        if pos is None:
            self.state = IDLE
            return

        leg = pos.leg1
        # Try to get a mark price for a more accurate P&L
        mark_bid = None
        if self._ws and self._ws.connected and self._ws.has_data(leg.token_id):
            mark_bid = self._ws.best_bid(leg.token_id)

        pos.exit_price = mark_bid or 0.0
        if mark_bid:
            pos.profit = round((mark_bid - leg.price) * leg.size, 4)
        else:
            pos.profit = round(-leg.cost, 4)

        pos.status = "abandoned"
        self.capital += pos.profit
        self.total_profit += pos.profit
        self.arbs_abandoned += 1

        self._log("ABANDONED %s@%.3f mark=%.3f pnl=$%+.4f | reason=%s capital=$%.2f"
                  % (leg.side, leg.price, pos.exit_price, pos.profit, reason, self.capital))
        self._log_decision("ABANDON", side=leg.side, price=leg.price,
                           pnl=pos.profit, reason=reason)

        self.positions.append(pos)
        self._save_trade(self._position_to_dict(pos))
        self.current_position = None
        self.state = IDLE

    async def _on_window_change(self, new_window: int):
        """Handle 15-min window transition — resolve open position before switching market."""
        if self.current_position is not None:
            self._log("Window ending — resolving position...")
            await asyncio.sleep(3)   # brief pause for Polymarket prices to settle
            self._resolve_position()

        self._current_window = new_window
        self._trades_this_window = 0
        self._tfi_book_events.clear()
        self._tfi_trade_events.clear()
        self._next_window_subscribed = False
        self._log("=== NEW WINDOW %d ===" % new_window)

        if self._next_market:
            self._current_market = self._next_market
            self._next_market = None
            self._log("Using pre-fetched market for window %d" % new_window)
        else:
            market = await asyncio.to_thread(find_market, new_window)
            self._current_market = market

        market = self._current_market
        if market and self._ws and self._ws.connected:
            await self._ws.resubscribe(market.up_token_id, market.down_token_id)
            self._log("WS resubscribed: UP=%s DOWN=%s"
                      % (market.up_token_id[:16], market.down_token_id[:16]))

    async def _pre_subscribe_next_window(self):
        """Pre-fetch next window market and WS-subscribe 30s before transition."""
        if self._next_window_subscribed:
            return

        next_window = self._current_window + 900
        self._log("PRE_SUBSCRIBE fetching market for next window %d" % next_window)

        market = await asyncio.to_thread(find_market, next_window)
        if not market:
            self._log("PRE_SUBSCRIBE no market found for window %d yet" % next_window)
            return

        self._next_market = market
        self._next_window_subscribed = True

        if self._ws and self._ws.connected:
            await self._ws.subscribe(market.up_token_id, market.down_token_id)
            self._log("PRE_SUBSCRIBE WS subscribed: UP=%s DOWN=%s"
                      % (market.up_token_id[:16], market.down_token_id[:16]))

    def _position_to_dict(self, pos: ArbPosition) -> dict:
        leg = pos.leg1
        d = {
            "window_id": pos.window_id,
            "status": pos.status,
            "profit": round(pos.profit, 4),
            "capital_after": round(self.capital, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Directional fields
            "side": leg.side,
            "entry_price": leg.price,
            "exit_price": pos.exit_price,
            "shares": leg.size,
            "bet_size": leg.cost,
        }
        if pos.leg2:
            # Instant arb: also include leg2 data for dashboard compat
            d["leg2_side"] = pos.leg2.side
            d["leg2_price"] = pos.leg2.price
            d["combined_cost"] = round(leg.price + pos.leg2.price, 4)
        return d

    # ─── Main Loop ────────────────────────────────────────────────────────────

    async def run(self, duration_minutes: int = 0):
        """Main async loop — WebSocket orderbook + Binance feed."""
        cfg = self.config

        self._log("=" * 60)
        self._log("  LEGGING ARB BOT PRO v2 — Polymarket BTC 15min")
        self._log("  Strategy: leg1 on signal, hunt leg2; resolve directionally if no leg2")
        self._log("  Capital: $%.2f | Bet: $%.2f/position" % (self.capital, cfg.BET_SIZE))
        self._log("  Confidence threshold: %.0f | Max leg1 price: $%.2f"
                  % (cfg.CONFIDENCE_THRESHOLD, cfg.LEG1_MAX_PRICE))
        self._log("  TFI weight: %.2f | OBI weight: %.2f | Depth: %d"
                  % (cfg.TFI_WEIGHT, cfg.OBI_WEIGHT, cfg.OBI_DEPTH))
        self._log("  Instant arb threshold: $%.3f | Leg2 timeout: %ds"
                  % (cfg.MAX_COMBINED_COST, cfg.LEG2_TIMEOUT_S))
        self._log("  Binance enabled: %s | OFI stop-loss: %.2f" % (cfg.BINANCE_ENABLED, cfg.BINANCE_OFI_STOP_LOSS))
        self._log("=" * 60)

        self._current_window = self._window_id()
        start_time = time.time()

        # ── Binance feed ──────────────────────────────────────────────────
        if cfg.BINANCE_ENABLED:
            from bot.binance_feed import BinanceFeed
            self._binance = BinanceFeed(log_fn=self._log)
            await self._binance.connect()

        # ── Polymarket WebSocket ──────────────────────────────────────────
        self._ws = ClobWebSocket(
            on_price_change=self._on_ws_price_change,
            on_trade=self._on_ws_trade,
            log_fn=self._log,
        )
        await self._ws.connect()

        market = await asyncio.to_thread(find_market, self._current_window)
        self._current_market = market
        if market and self._ws.connected:
            await self._ws.subscribe(market.up_token_id, market.down_token_id)
            self._log("Subscribed: UP=%s DOWN=%s"
                      % (market.up_token_id[:16], market.down_token_id[:16]))

        try:
            while not self._shutdown:
                try:
                    window_ts = self._window_id()

                    if window_ts != self._current_window:
                        await self._on_window_change(window_ts)
                        market = self._current_market
                    else:
                        remaining = self._seconds_remaining_in_window()
                        if remaining <= cfg.PRE_SUBSCRIBE_S:
                            await self._pre_subscribe_next_window()

                        if not self._current_market:
                            market = await asyncio.to_thread(find_market, window_ts)
                            self._current_market = market
                            if market and self._ws and self._ws.connected:
                                await self._ws.subscribe(
                                    market.up_token_id, market.down_token_id)
                        else:
                            market = self._current_market

                    if market is None:
                        self._log("NO_MARKET window=%d — waiting..." % window_ts)
                        await asyncio.sleep(cfg.POLL_INTERVAL_S)
                        continue

                    # Auto-reconnect Polymarket WS
                    if not self._ws.connected:
                        self._log("WS disconnected, reconnecting...")
                        await self._ws.connect()
                        if self._ws.connected and market:
                            await self._ws.subscribe(
                                market.up_token_id, market.down_token_id)

                    # Auto-reconnect Binance
                    if cfg.BINANCE_ENABLED and self._binance and not self._binance.connected:
                        self._log("[BinanceFeed] Disconnected, reconnecting...")
                        await self._binance.connect()

                    self._tick(market)

                except Exception as e:
                    self._log("ERROR: %s" % str(e))

                # Duration limit check
                if duration_minutes > 0:
                    if (time.time() - start_time) / 60 >= duration_minutes:
                        self._log("Duration limit reached")
                        break

                await asyncio.sleep(cfg.POLL_INTERVAL_S)

        finally:
            self._log("Shutting down gracefully...")
            if self._ws:
                await self._ws.disconnect()
            if self._binance:
                await self._binance.disconnect()
            if self._log_file:
                self._log_file.close()

        self.print_stats()

    def print_stats(self):
        """Print final session summary."""
        decided = self.wins + self.losses
        win_rate = self.wins / decided * 100 if decided > 0 else 0
        self._log("")
        self._log("=" * 60)
        self._log("  LEGGING ARB PRO v2 — SESSION SUMMARY")
        self._log("=" * 60)
        self._log("  Capital:      $%.2f → $%.2f" % (self.initial_capital, self.capital))
        self._log("  ROI:          %+.2f%%" % ((self.capital / self.initial_capital - 1) * 100))
        self._log("  Net P&L:      $%+.4f" % self.total_profit)
        self._log("  Win/Loss:     %d/%d (%.0f%% win rate)" % (self.wins, self.losses, win_rate))
        self._log("  Instant arbs: %d" % self.arbs_completed)
        self._log("  Abandoned:    %d" % self.arbs_abandoned)
        self._log("  Ticks:        %d (%.0f min)"
                  % (self.ticks, self.ticks * self.config.POLL_INTERVAL_S / 60))

        completed = [p for p in self.positions if p.status == "complete"]
        if completed:
            costs = [p.leg1.price + (p.leg2.price if p.leg2 else 0) for p in completed]
            self._log("  Avg combined: $%.3f" % (sum(costs) / len(costs)))

        self._log("=" * 60)
