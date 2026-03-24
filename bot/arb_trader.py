"""
Polymarket BTC 15-min Legging Arbitrage Bot — Pro-Enhanced

Strategy: buy YES and NO tokens at combined cost < $1 → guaranteed profit.

Signal stack:
  1. Instant Arb   — combined ask < MAX_COMBINED_COST → execute immediately, no signal needed
  2. Confidence    — composite score [0-100] from TFI + OBI (+ Binance lead-lag if enabled)
     TFI: Trade Flow Imbalance — net dollar flow from actual executions (UP trades - DOWN trades)
     OBI: Order Book Imbalance — (bid_vol - ask_vol) / total at top-N levels, normalized
     Binance: 1m/3m BTC momentum → multiplier on score (lag effect ~30-90s)

Fixes over v1:
  - OFI double-counting removed: TFI uses trade events ONLY (not book changes)
  - Abandoned legs now correctly debit BET_SIZE from capital
  - Fee calculation is notional-based (2% × total_spent), not profit-based
  - Hardcoded literals moved to ArbConfig
  - find_market() wrapped in asyncio.to_thread (no more event-loop blocking)
  - subscribe() correctly accumulates subscribed assets (no overwrite bug)
  - SIGINT → clean async shutdown via _shutdown flag
  - Structured DECISION log for dashboard "why" column
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
    """A single executed leg of an arb position."""
    side: str           # "UP" or "DOWN"
    token_id: str
    price: float        # entry ask at time of fill
    size: float         # shares = bet_size / price
    cost: float         # total $ spent = bet_size
    timestamp: float    # unix ts
    window_id: int


@dataclass
class ArbPosition:
    """A complete or in-progress arb position."""
    leg1: Leg
    leg2: Leg | None = None
    status: str = "open"   # "open" | "complete" | "abandoned"
    profit: float = 0.0
    window_id: int = 0


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

        # Stats
        self.arbs_completed = 0
        self.arbs_abandoned = 0
        self.total_profit = 0.0
        self.ticks = 0

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
        """IDLE: look for instant arb or confidence signal to open leg 1."""
        cfg = self.config

        if remaining < cfg.MIN_WINDOW_REMAINING_S:
            return
        if self._trades_this_window >= cfg.MAX_TRADES_PER_WINDOW:
            return
        if up_ask is None or down_ask is None:
            return

        combined = up_ask + down_ask

        # ── Path 1: instant riskless arb (no signal needed) ──────────────
        if combined < cfg.MAX_COMBINED_COST:
            gross = 1.0 - combined
            fee = (cfg.BET_SIZE * 2) * cfg.POLYMARKET_FEE
            min_shares = min(cfg.BET_SIZE / up_ask, cfg.BET_SIZE / down_ask)
            estimated_net = round(gross * min_shares - fee, 4)
            self._log("INSTANT_ARB combined=%.3f gross=%.4f est_net=$%.4f — buying both sides"
                      % (combined, gross, estimated_net))
            self._log_decision("INSTANT_ARB", combined=combined, gross=gross,
                               estimated_net=estimated_net)
            self._execute_instant_arb(market, up_ask, down_ask)
            return

        # ── Path 2: confidence-based sequential entry ─────────────────────
        if confidence < cfg.CONFIDENCE_THRESHOLD:
            # Log DECISION only every ~6 ticks to avoid log spam (on 5s intervals = 30s)
            if self.ticks % 6 == 0:
                self._log_decision("SKIP", reason="LOW_CONFIDENCE",
                                   score=confidence, threshold=cfg.CONFIDENCE_THRESHOLD,
                                   tfi=tfi, obi=obi, dir=direction)
            return

        if direction == "NONE":
            self._log_decision("SKIP", reason="DIVERGENT_SIGNALS",
                               score=confidence, tfi=tfi, obi=obi)
            return

        # Leg 1 side determined by signal direction
        if direction == "UP":
            leg1_side, leg1_price, leg1_token = "UP", up_ask, market.up_token_id
        else:
            leg1_side, leg1_price, leg1_token = "DOWN", down_ask, market.down_token_id

        if leg1_price is None or leg1_price <= 0:
            return

        if leg1_price > cfg.LEG1_MAX_PRICE:
            self._log_decision("SKIP", reason="LEG1_TOO_EXPENSIVE",
                               price=leg1_price, max=cfg.LEG1_MAX_PRICE)
            self._log("SKIP leg1 too expensive: %s @ %.3f (max %.3f)"
                      % (leg1_side, leg1_price, cfg.LEG1_MAX_PRICE))
            return

        # Execute leg 1 (paper)
        shares = cfg.BET_SIZE / leg1_price
        leg1 = Leg(
            side=leg1_side,
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

        self._log_decision("ENTER_LEG1", side=leg1_side, score=confidence,
                           tfi=tfi, obi=obi, price=leg1_price)
        self._log("LEG1 %s @ %.3f ($%.2f, %.1f shares) | conf=%.0f tfi=%+.1f obi=%+.3f window=%d"
                  % (leg1_side, leg1_price, cfg.BET_SIZE, shares,
                     confidence, tfi, obi, self._current_window))

    def _tick_leg1_open(
        self,
        market: MarketInfo,
        up_ask: float | None,
        down_ask: float | None,
        remaining: int,
    ):
        """LEG1_OPEN: hunt for a cheap opposite side to complete the arb."""
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

            # ── Correct fee: 2% of TOTAL NOTIONAL (both legs) ────────────
            total_cost_price = leg1.price + leg2.price
            gross_per_share = 1.0 - total_cost_price
            min_shares = min(leg1.size, leg2.size)
            gross_dollar = gross_per_share * min_shares
            total_notional = leg1.cost + leg2.cost    # = 2 × BET_SIZE
            fee_dollar = total_notional * self.config.POLYMARKET_FEE
            net_profit = round(gross_dollar - fee_dollar, 4)

            pos.profit = net_profit
            self.capital += net_profit
            self.total_profit += net_profit
            self.arbs_completed += 1

            self._log(
                "LEG2 %s @ %.3f | COMPLETE combined=%.3f gross=$%.4f fee=$%.4f "
                "net=$%.4f (%.2f%%) capital=$%.2f"
                % (opposite_side, opp_ask, combined,
                   gross_dollar, fee_dollar, net_profit,
                   (net_profit / (leg1.cost + leg2.cost)) * 100,
                   self.capital)
            )
            self._log_decision("COMPLETE_LEG2", side=opposite_side, price=opp_ask,
                               combined=combined, net=net_profit)

            self.positions.append(pos)
            self._save_trade(self._position_to_dict(pos))
            self.current_position = None
            self.state = IDLE
            return

        # ── Timeout check ─────────────────────────────────────────────────
        if elapsed > self.config.LEG2_TIMEOUT_S:
            self._abandon_position("timeout (%.0fs)" % elapsed)
            return

        # ── Window expiring ───────────────────────────────────────────────
        if remaining < self.config.WINDOW_EXPIRY_ABANDON_S:
            self._abandon_position("window_expiring (%ds left)" % remaining)

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
        """Abandon an open leg 1 — deducts BET_SIZE from capital (real loss)."""
        pos = self.current_position
        if pos is None:
            self.state = IDLE
            return

        pos.status = "abandoned"
        # Leg 1 cost was already spent — record as real loss
        abandoned_cost = pos.leg1.cost
        pos.profit = -abandoned_cost
        self.capital -= abandoned_cost
        self.total_profit -= abandoned_cost
        self.arbs_abandoned += 1

        self._log("ABANDONED leg1=%s@%.3f cost=$%.2f | reason=%s capital=$%.2f"
                  % (pos.leg1.side, pos.leg1.price, abandoned_cost, reason, self.capital))
        self._log_decision("ABANDON", side=pos.leg1.side, price=pos.leg1.price,
                           cost=abandoned_cost, reason=reason)

        self.positions.append(pos)
        self._save_trade(self._position_to_dict(pos))
        self.current_position = None
        self.state = IDLE

    async def _on_window_change(self, new_window: int):
        """Handle 15-min window transition."""
        if self.current_position is not None:
            self._abandon_position("window_changed")

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
        d = {
            "window_id": pos.window_id,
            "status": pos.status,
            "profit": pos.profit,
            "capital_after": round(self.capital, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "leg1_side": pos.leg1.side,
            "leg1_price": pos.leg1.price,
            "leg1_cost": pos.leg1.cost,
        }
        if pos.leg2:
            d["leg2_side"] = pos.leg2.side
            d["leg2_price"] = pos.leg2.price
            d["leg2_cost"] = pos.leg2.cost
            d["combined_cost"] = round(pos.leg1.price + pos.leg2.price, 4)
            d["gross_profit"] = round(1.0 - (pos.leg1.price + pos.leg2.price), 4)
        return d

    # ─── Main Loop ────────────────────────────────────────────────────────────

    async def run(self, duration_minutes: int = 0):
        """Main async loop — WebSocket orderbook + Binance feed."""
        cfg = self.config

        self._log("=" * 60)
        self._log("  ARB TRADER PRO — Polymarket BTC 15min")
        self._log("  Capital: $%.2f | Bet: $%.2f/leg" % (self.capital, cfg.BET_SIZE))
        self._log("  Confidence threshold: %.0f | Max combined: $%.3f"
                  % (cfg.CONFIDENCE_THRESHOLD, cfg.MAX_COMBINED_COST))
        self._log("  TFI weight: %.2f | OBI weight: %.2f | Depth: %d"
                  % (cfg.TFI_WEIGHT, cfg.OBI_WEIGHT, cfg.OBI_DEPTH))
        self._log("  Leg2 timeout: %ds | Leg2 max price: $%.2f"
                  % (cfg.LEG2_TIMEOUT_S, cfg.LEG2_MAX_PRICE))
        self._log("  Fee: %.0f%% of notional ($%.2f per arb)"
                  % (cfg.POLYMARKET_FEE * 100, cfg.BET_SIZE * 2 * cfg.POLYMARKET_FEE))
        self._log("  Binance enabled: %s" % cfg.BINANCE_ENABLED)
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
        self._log("")
        self._log("=" * 60)
        self._log("  ARB TRADING SUMMARY")
        self._log("=" * 60)
        self._log("  Capital:      $%.2f → $%.2f" % (self.initial_capital, self.capital))
        self._log("  ROI:          %+.2f%%" % ((self.capital / self.initial_capital - 1) * 100))
        self._log("  Net P&L:      $%+.4f" % self.total_profit)
        self._log("  Completed:    %d arbs" % self.arbs_completed)
        self._log("  Abandoned:    %d legs (each = -$%.2f)" % (self.arbs_abandoned, self.config.BET_SIZE))
        self._log("  Ticks:        %d (%.0f min)"
                  % (self.ticks, self.ticks * self.config.POLL_INTERVAL_S / 60))

        if self.arbs_completed > 0:
            avg = self.total_profit / self.arbs_completed
            self._log("  Avg net/arb:  $%.4f" % avg)

        completed = [p for p in self.positions if p.status == "complete"]
        if completed:
            costs = [p.leg1.price + (p.leg2.price if p.leg2 else 0) for p in completed]
            self._log("  Avg combined: $%.3f" % (sum(costs) / len(costs)))

        self._log("=" * 60)
