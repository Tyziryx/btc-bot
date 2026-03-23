"""
Polymarket BTC 15-min Legging Arbitrage Bot (Paper Trading)

Strategy: buy YES and NO tokens at different times for combined cost < $1.
- OFI (Order Flow Imbalance) from WebSocket price_change events
- Wait for opposite side to cheapen, then complete the arb
- Guaranteed profit = $1 - total_cost - fees

Uses Polymarket CLOB WebSocket for real-time orderbook data.
Falls back to REST /price on WS disconnect.
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


# ─── State constants ───
IDLE = "IDLE"
LEG1_OPEN = "LEG1_OPEN"


@dataclass
class Leg:
    """A single leg of an arb position."""
    side: str           # "UP" or "DOWN"
    token_id: str
    price: float        # entry price (best ask at time of fill)
    size: float         # shares = bet_size / price
    cost: float         # total $ spent
    timestamp: float    # unix timestamp
    window_id: int


@dataclass
class ArbPosition:
    """A complete or in-progress arb position."""
    leg1: Leg
    leg2: Leg | None = None
    status: str = "open"  # "open", "complete", "abandoned", "resolved"
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

        # OFI tracking — fed by WebSocket price_change events
        self._ofi_events: deque[tuple[float, float]] = deque()  # (timestamp, delta)
        self._last_ofi: float = 0.0

        # Current market info
        self._current_market: MarketInfo | None = None

        # Window tracking
        self._current_window: int = 0
        self._trades_this_window: int = 0

        # Stats
        self.arbs_completed = 0
        self.arbs_abandoned = 0
        self.total_profit = 0.0
        self.ticks = 0

        # WebSocket client
        self._ws: ClobWebSocket | None = None

        # Logging setup
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
        self._log_file_path = os.path.join(logs_dir, "arb_%s_%s.log" % (start_ts, git_hash))
        self._log_file = open(self._log_file_path, "a", buffering=1)

    # ─── Logging ───

    def _log(self, message: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = "%s %s" % (ts, message)
        print(line)
        self._log_file.write(line + "\n")

    def _save_trade(self, trade: dict):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(trade) + "\n")

    # ─── Helpers ───

    @staticmethod
    def _window_id(ts: float | None = None) -> int:
        """Current 15-min window start timestamp."""
        t = int(ts or time.time())
        return (t // 900) * 900

    def _seconds_remaining_in_window(self) -> int:
        now = int(time.time())
        window_end = self._current_window + 900
        return max(0, window_end - now)

    # ─── OFI from WebSocket events ───

    def _on_ws_price_change(self, asset_id: str, changes: list):
        """Callback from ClobWebSocket on price_change events.
        Accumulates OFI deltas in a sliding window.

        Each change: {"side": "BUY"|"SELL", "price": "0.52", "size": "150.0"}
        BUY side size increase = bid pressure (positive OFI)
        SELL side size increase = ask pressure (negative OFI)
        """
        now = time.time()
        market = self._current_market
        if not market:
            return

        for change in changes:
            side = change.get("side", "")
            size = float(change.get("size", 0))

            # Determine direction based on which token and side
            if side == "BUY":
                # Bid increase = buying pressure
                if asset_id == market.up_token_id:
                    delta = size   # UP buying = bullish
                else:
                    delta = -size  # DOWN buying = bearish
            else:
                # Ask increase = selling pressure
                if asset_id == market.up_token_id:
                    delta = -size  # UP selling = bearish
                else:
                    delta = size   # DOWN selling = bullish

            self._ofi_events.append((now, delta))

    def _compute_ofi(self) -> float:
        """Compute OFI from accumulated WebSocket events over sliding window."""
        now = time.time()
        cutoff = now - self.config.OFI_WINDOW_S

        # Prune old events
        while self._ofi_events and self._ofi_events[0][0] < cutoff:
            self._ofi_events.popleft()

        self._last_ofi = sum(delta for _, delta in self._ofi_events)
        return self._last_ofi

    def _on_ws_trade(self, asset_id: str, price: str, size: str):
        """Callback from ClobWebSocket on last_trade_price events."""
        self._log("TRADE %s price=%s size=%s" % (asset_id[:12], price, size))

    # ─── Price getters (WS with REST fallback) ───

    def _get_up_ask(self) -> float | None:
        """Get UP token best ask — WS first, REST fallback."""
        market = self._current_market
        if not market:
            return None

        if self._ws and self._ws.connected and self._ws.has_data(market.up_token_id):
            return self._ws.best_ask(market.up_token_id)

        # REST fallback
        price = get_market_price(market.up_token_id, side="SELL")
        return price if 0.01 < price < 0.99 else None

    def _get_down_ask(self) -> float | None:
        """Get DOWN token best ask — WS first, REST fallback."""
        market = self._current_market
        if not market:
            return None

        if self._ws and self._ws.connected and self._ws.has_data(market.down_token_id):
            return self._ws.best_ask(market.down_token_id)

        # REST fallback
        price = get_market_price(market.down_token_id, side="SELL")
        return price if 0.01 < price < 0.99 else None

    # ─── State Machine ───

    def _tick(self, market: MarketInfo):
        """Process one tick through the state machine.
        Window transitions are handled in run() before calling _tick().
        """
        self.ticks += 1

        # Compute OFI from accumulated WS events
        ofi = self._compute_ofi()

        # Get prices from WS local book (or REST fallback)
        up_ask = self._get_up_ask()
        down_ask = self._get_down_ask()

        # Log state every tick
        remaining = self._seconds_remaining_in_window()
        combined_str = "%.3f" % (up_ask + down_ask) if up_ask and down_ask else "n/a"
        ws_status = "WS" if (self._ws and self._ws.connected) else "REST"

        self._log("TICK window=%d | state=%s ofi=%+.1f up_ask=%s down_ask=%s combined=%s remain=%ds [%s]"
                  % (window_id, self.state,
                     ofi,
                     "%.3f" % up_ask if up_ask else "none",
                     "%.3f" % down_ask if down_ask else "none",
                     combined_str,
                     remaining,
                     ws_status))

        if self.state == IDLE:
            self._tick_idle(market, ofi, up_ask, down_ask, remaining)
        elif self.state == LEG1_OPEN:
            self._tick_leg1_open(market, up_ask, down_ask, remaining)

    def _tick_idle(self, market: MarketInfo, ofi: float,
                   up_ask: float | None, down_ask: float | None,
                   remaining: int):
        """IDLE state: look for OFI signal to open leg 1."""
        if remaining < self.config.MIN_WINDOW_REMAINING_S:
            return

        if self._trades_this_window >= self.config.MAX_TRADES_PER_WINDOW:
            return

        if up_ask is None or down_ask is None:
            return

        # Check if combined cost already allows riskless arb
        combined = up_ask + down_ask
        if combined < self.config.MAX_COMBINED_COST:
            self._log("INSTANT_ARB combined=%.3f — buying both sides" % combined)
            self._execute_instant_arb(market, up_ask, down_ask)
            return

        # OFI signal
        if abs(ofi) < self.config.OFI_THRESHOLD:
            return

        # OFI positive = buy UP first, negative = buy DOWN first
        if ofi > 0:
            leg1_side = "UP"
            leg1_price = up_ask
            leg1_token = market.up_token_id
        else:
            leg1_side = "DOWN"
            leg1_price = down_ask
            leg1_token = market.down_token_id

        if leg1_price is None or leg1_price <= 0:
            return

        # Price sanity: don't buy too expensive
        if leg1_price > 0.60:
            self._log("SKIP leg1 too expensive: %s @ %.3f" % (leg1_side, leg1_price))
            return

        # Execute leg 1 (paper)
        shares = self.config.BET_SIZE / leg1_price
        cost = self.config.BET_SIZE

        leg1 = Leg(
            side=leg1_side,
            token_id=leg1_token,
            price=leg1_price,
            size=round(shares, 2),
            cost=round(cost, 4),
            timestamp=time.time(),
            window_id=self._current_window,
        )

        self.current_position = ArbPosition(
            leg1=leg1,
            window_id=self._current_window,
        )
        self.state = LEG1_OPEN
        self._trades_this_window += 1

        self._log("LEG1 %s @ %.3f ($%.2f, %.1f shares) | ofi=%+.1f window=%d"
                  % (leg1_side, leg1_price, cost, shares, ofi, self._current_window))

    def _tick_leg1_open(self, market: MarketInfo,
                        up_ask: float | None, down_ask: float | None,
                        remaining: int):
        """LEG1_OPEN state: hunt for leg 2."""
        pos = self.current_position
        if pos is None:
            self.state = IDLE
            return

        leg1 = pos.leg1
        opposite_side = "DOWN" if leg1.side == "UP" else "UP"

        if opposite_side == "UP":
            opp_ask = up_ask
            opp_token = market.up_token_id
        else:
            opp_ask = down_ask
            opp_token = market.down_token_id

        if opp_ask is None:
            return

        combined = leg1.price + opp_ask
        elapsed = time.time() - leg1.timestamp

        self._log("  HUNTING leg2=%s opp_ask=%.3f combined=%.3f target<%.3f elapsed=%.0fs"
                  % (opposite_side, opp_ask, combined, self.config.MAX_COMBINED_COST, elapsed))

        # Leg 2 opportunity!
        if combined < self.config.MAX_COMBINED_COST and opp_ask <= self.config.LEG2_MAX_PRICE:
            shares = self.config.BET_SIZE / opp_ask
            cost = self.config.BET_SIZE

            leg2 = Leg(
                side=opposite_side,
                token_id=opp_token,
                price=opp_ask,
                size=round(shares, 2),
                cost=round(cost, 4),
                timestamp=time.time(),
                window_id=self._current_window,
            )
            pos.leg2 = leg2
            pos.status = "complete"

            total_cost = leg1.price + leg2.price
            gross_profit_per_share = 1.0 - total_cost
            fee = gross_profit_per_share * self.config.POLYMARKET_FEE if gross_profit_per_share > 0 else 0
            net_profit_per_share = gross_profit_per_share - fee

            min_shares = min(leg1.size, leg2.size)
            net_profit = round(net_profit_per_share * min_shares, 4)
            pos.profit = net_profit

            self.capital += net_profit
            self.total_profit += net_profit
            self.arbs_completed += 1

            self._log("LEG2 %s @ %.3f | COMPLETE combined=%.3f profit=$%.4f (%.1f%%) capital=$%.2f"
                      % (opposite_side, opp_ask, combined, net_profit,
                         net_profit_per_share * 100, self.capital))

            self.positions.append(pos)
            self._save_trade(self._position_to_dict(pos))
            self.current_position = None
            self.state = IDLE
            return

        # Timeout check
        if elapsed > self.config.LEG2_TIMEOUT_S:
            self._abandon_position("timeout (%.0fs)" % elapsed)
            return

        # Window about to expire
        if remaining < 30:
            self._abandon_position("window_expiring (%ds left)" % remaining)

    def _execute_instant_arb(self, market: MarketInfo,
                             up_ask: float, down_ask: float):
        """Buy both sides immediately when combined < threshold."""
        up_shares = self.config.BET_SIZE / up_ask
        down_shares = self.config.BET_SIZE / down_ask

        leg1 = Leg("UP", market.up_token_id, up_ask,
                    round(up_shares, 2), self.config.BET_SIZE, time.time(), self._current_window)
        leg2 = Leg("DOWN", market.down_token_id, down_ask,
                    round(down_shares, 2), self.config.BET_SIZE, time.time(), self._current_window)

        combined = up_ask + down_ask
        gross = 1.0 - combined
        fee = gross * self.config.POLYMARKET_FEE if gross > 0 else 0
        net_per_share = gross - fee
        min_shares = min(up_shares, down_shares)
        net_profit = round(net_per_share * min_shares, 4)

        pos = ArbPosition(leg1=leg1, leg2=leg2, status="complete",
                          profit=net_profit, window_id=self._current_window)

        self.capital += net_profit
        self.total_profit += net_profit
        self.arbs_completed += 1
        self._trades_this_window += 1

        self._log("INSTANT_ARB UP@%.3f + DOWN@%.3f = %.3f | profit=$%.4f capital=$%.2f"
                  % (up_ask, down_ask, combined, net_profit, self.capital))

        self.positions.append(pos)
        self._save_trade(self._position_to_dict(pos))

    def _abandon_position(self, reason: str):
        """Abandon a leg 1 position (no leg 2 found)."""
        pos = self.current_position
        if pos is None:
            self.state = IDLE
            return

        pos.status = "abandoned"
        pos.profit = 0.0
        self.arbs_abandoned += 1

        self._log("ABANDONED leg1=%s@%.3f | reason=%s (position resolves at window end)"
                  % (pos.leg1.side, pos.leg1.price, reason))

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
        self._ofi_events.clear()
        self._log("=== NEW WINDOW %d ===" % new_window)

        # Find new market and resubscribe WS
        market = find_market(new_window)
        self._current_market = market

        if market and self._ws and self._ws.connected:
            await self._ws.resubscribe(market.up_token_id, market.down_token_id)
            self._log("WS resubscribed to window %d tokens" % new_window)

    def _position_to_dict(self, pos: ArbPosition) -> dict:
        """Convert position to dict for JSONL logging."""
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
        return d

    # ─── Main Loop ───

    async def run(self, duration_minutes: int = 0):
        """Main loop with WebSocket orderbook feed."""
        self._log("=" * 58)
        self._log("  ARB TRADER — Polymarket BTC 15min Legging")
        self._log("  Mode: WebSocket CLOB (real orderbook)")
        self._log("  Capital: $%.2f | Bet: $%.2f/leg" % (self.capital, self.config.BET_SIZE))
        self._log("  OFI threshold: %.1f | Max combined: $%.2f"
                  % (self.config.OFI_THRESHOLD, self.config.MAX_COMBINED_COST))
        self._log("  Leg2 timeout: %ds | Leg2 max price: $%.2f"
                  % (self.config.LEG2_TIMEOUT_S, self.config.LEG2_MAX_PRICE))
        self._log("  Poll interval: %.1fs | OFI window: %ds"
                  % (self.config.POLL_INTERVAL_S, self.config.OFI_WINDOW_S))
        self._log("=" * 58)

        self._current_window = self._window_id()
        start_time = time.time()

        # Initialize WebSocket
        self._ws = ClobWebSocket(
            on_price_change=self._on_ws_price_change,
            on_trade=self._on_ws_trade,
            log_fn=self._log,
        )

        # Connect and subscribe to current market
        await self._ws.connect()

        market = find_market(self._current_window)
        self._current_market = market
        if market and self._ws.connected:
            await self._ws.subscribe(market.up_token_id, market.down_token_id)
            self._log("Subscribed to UP=%s DOWN=%s" % (
                market.up_token_id[:16], market.down_token_id[:16]))

        try:
            while True:
                try:
                    # Check for window change
                    window_ts = self._window_id()
                    if window_ts != self._current_window:
                        await self._on_window_change(window_ts)
                        market = self._current_market
                    else:
                        # Refresh market if we don't have one
                        if not self._current_market:
                            market = find_market(window_ts)
                            self._current_market = market
                            if market and self._ws and self._ws.connected:
                                await self._ws.subscribe(
                                    market.up_token_id, market.down_token_id)
                        else:
                            market = self._current_market

                    if market is None:
                        self._log("NO_MARKET window=%d — waiting..." % window_ts)
                        await asyncio.sleep(self.config.POLL_INTERVAL_S)
                        continue

                    # Auto-reconnect WS if disconnected
                    if not self._ws.connected:
                        self._log("WS disconnected, reconnecting...")
                        await self._ws.connect()
                        if self._ws.connected and market:
                            await self._ws.subscribe(
                                market.up_token_id, market.down_token_id)

                    # Run state machine tick (reads from WS local book)
                    self._tick(market)

                except Exception as e:
                    self._log("ERROR: %s" % str(e))

                # Duration check
                if duration_minutes > 0:
                    elapsed = (time.time() - start_time) / 60
                    if elapsed >= duration_minutes:
                        self._log("Duration limit reached (%.0f min)" % elapsed)
                        break

                await asyncio.sleep(self.config.POLL_INTERVAL_S)

        finally:
            if self._ws:
                await self._ws.disconnect()

        self.print_stats()

    def print_stats(self):
        """Print summary statistics."""
        self._log("")
        self._log("=" * 58)
        self._log("  ARB TRADING SUMMARY")
        self._log("=" * 58)
        self._log("  Capital:     $%.2f (started $%.2f)" % (self.capital, self.initial_capital))
        self._log("  ROI:         %+.2f%%" % ((self.capital / self.initial_capital - 1) * 100))
        self._log("  Total profit: $%.4f" % self.total_profit)
        self._log("  Completed:   %d arbs" % self.arbs_completed)
        self._log("  Abandoned:   %d legs" % self.arbs_abandoned)
        self._log("  Ticks:       %d (%.0f min)"
                  % (self.ticks, self.ticks * self.config.POLL_INTERVAL_S / 60))

        if self.arbs_completed > 0:
            avg = self.total_profit / self.arbs_completed
            self._log("  Avg profit:  $%.4f/arb" % avg)

        completed = [p for p in self.positions if p.status == "complete"]
        if completed:
            costs = [p.leg1.price + (p.leg2.price if p.leg2 else 0) for p in completed]
            self._log("  Avg combined: $%.3f" % (sum(costs) / len(costs)))

        self._log("=" * 58)
