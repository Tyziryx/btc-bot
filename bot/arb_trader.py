"""
Polymarket BTC 15-min Legging Arbitrage Bot (Paper Trading)

Strategy: buy YES and NO tokens at different times for combined cost < $1.
- OFI (Order Flow Imbalance) signals which side to buy first
- Wait for opposite side to cheapen, then complete the arb
- Guaranteed profit = $1 - total_cost - fees

No ML model needed. Pure orderbook mechanics.
"""

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.arb_config import ArbConfig
from bot.polymarket import find_market, get_orderbook, MarketInfo


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

        # OFI tracking
        self._ofi_buffer: deque[float] = deque(maxlen=7)  # 6 deltas + current
        self._prev_up_book: dict | None = None
        self._prev_down_book: dict | None = None
        self._last_ofi: float = 0.0

        # Window tracking
        self._current_window: int = 0
        self._trades_this_window: int = 0

        # Stats
        self.arbs_completed = 0
        self.arbs_abandoned = 0
        self.total_profit = 0.0
        self.ticks = 0

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

    @staticmethod
    def _best_ask(book: dict) -> float | None:
        """Extract best ask price from orderbook."""
        asks = book.get("asks", [])
        if not asks:
            return None
        return float(asks[0].get("price", 0))

    @staticmethod
    def _best_bid(book: dict) -> float | None:
        """Extract best bid price from orderbook."""
        bids = book.get("bids", [])
        if not bids:
            return None
        return float(bids[0].get("price", 0))

    # ─── OFI Calculation ───

    def _compute_ofi(self, up_book: dict, down_book: dict) -> float:
        """Compute Order Flow Imbalance from orderbook snapshots.

        OFI = sum(bid_volume_changes) - sum(ask_volume_changes)
        Positive OFI = buying pressure → buy UP first
        Negative OFI = selling pressure → buy DOWN first
        """
        if self._prev_up_book is None or self._prev_down_book is None:
            self._prev_up_book = up_book
            self._prev_down_book = down_book
            return 0.0

        ofi = 0.0

        # Process UP token orderbook
        ofi += self._book_delta(self._prev_up_book, up_book, side_sign=1.0)
        # Process DOWN token orderbook (inverted — DOWN bid pressure = bearish)
        ofi -= self._book_delta(self._prev_down_book, down_book, side_sign=1.0)

        self._prev_up_book = up_book
        self._prev_down_book = down_book

        self._ofi_buffer.append(ofi)
        self._last_ofi = sum(self._ofi_buffer)
        return self._last_ofi

    @staticmethod
    def _book_delta(prev: dict, curr: dict, side_sign: float = 1.0) -> float:
        """Compute bid/ask volume delta between two orderbook snapshots."""
        delta = 0.0

        # Bids: volume increase = buying pressure
        prev_bids = {b["price"]: float(b["size"]) for b in prev.get("bids", [])}
        curr_bids = {b["price"]: float(b["size"]) for b in curr.get("bids", [])}
        all_bid_prices = set(prev_bids) | set(curr_bids)
        for p in all_bid_prices:
            delta += (curr_bids.get(p, 0) - prev_bids.get(p, 0))

        # Asks: volume increase = selling pressure (negative for OFI)
        prev_asks = {a["price"]: float(a["size"]) for a in prev.get("asks", [])}
        curr_asks = {a["price"]: float(a["size"]) for a in curr.get("asks", [])}
        all_ask_prices = set(prev_asks) | set(curr_asks)
        for p in all_ask_prices:
            delta -= (curr_asks.get(p, 0) - prev_asks.get(p, 0))

        return delta * side_sign

    # ─── State Machine ───

    def _tick(self, market: MarketInfo, up_book: dict, down_book: dict):
        """Process one tick through the state machine."""
        self.ticks += 1
        window_id = self._window_id()

        # Window transition
        if window_id != self._current_window:
            self._on_window_change(window_id)

        # Compute OFI
        ofi = self._compute_ofi(up_book, down_book)

        # Get prices
        up_ask = self._best_ask(up_book)
        down_ask = self._best_ask(down_book)
        up_bid = self._best_bid(up_book)
        down_bid = self._best_bid(down_book)

        # Log state every tick
        remaining = self._seconds_remaining_in_window()
        self._log("TICK window=%d | state=%s ofi=%+.1f up_ask=%s down_ask=%s remain=%ds"
                  % (window_id, self.state,
                     ofi,
                     "%.3f" % up_ask if up_ask else "none",
                     "%.3f" % down_ask if down_ask else "none",
                     remaining))

        if self.state == IDLE:
            self._tick_idle(market, ofi, up_ask, down_ask, up_book, down_book, remaining)
        elif self.state == LEG1_OPEN:
            self._tick_leg1_open(market, up_ask, down_ask, remaining)

    def _tick_idle(self, market: MarketInfo, ofi: float,
                   up_ask: float | None, down_ask: float | None,
                   up_book: dict, down_book: dict, remaining: int):
        """IDLE state: look for OFI signal to open leg 1."""
        # Don't trade near window end
        if remaining < self.config.MIN_WINDOW_REMAINING_S:
            return

        # Already traded this window
        if self._trades_this_window >= self.config.MAX_TRADES_PER_WINDOW:
            return

        # Need both sides priced
        if up_ask is None or down_ask is None:
            return

        # Check if combined cost already allows riskless arb (rare but possible)
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

        # Get opposite ask price
        if opposite_side == "UP":
            opp_ask = up_ask
            opp_token = market.up_token_id
        else:
            opp_ask = down_ask
            opp_token = market.down_token_id

        if opp_ask is None:
            return

        # Check combined cost
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

            # Compute profit
            total_cost = leg1.price + leg2.price  # per-share cost
            gross_profit_per_share = 1.0 - total_cost
            fee = gross_profit_per_share * self.config.POLYMARKET_FEE if gross_profit_per_share > 0 else 0
            net_profit_per_share = gross_profit_per_share - fee

            # Scale to actual position size (use min shares)
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

        # In paper trading: leg1 resolves at window end
        # If our direction is right, we get $1/share. If wrong, we lose the bet.
        # For now, count as a loss of the spread (we bought at ask, value is unknown)
        pos.status = "abandoned"
        pos.profit = 0.0  # Paper: assume break-even (token resolves at random)
        self.arbs_abandoned += 1

        self._log("ABANDONED leg1=%s@%.3f | reason=%s (position resolves at window end)"
                  % (pos.leg1.side, pos.leg1.price, reason))

        self.positions.append(pos)
        self._save_trade(self._position_to_dict(pos))
        self.current_position = None
        self.state = IDLE

    def _on_window_change(self, new_window: int):
        """Handle 15-min window transition."""
        if self.current_position is not None:
            self._abandon_position("window_changed")

        self._current_window = new_window
        self._trades_this_window = 0
        self._ofi_buffer.clear()
        self._prev_up_book = None
        self._prev_down_book = None
        self._log("=== NEW WINDOW %d ===" % new_window)

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
        """Main polling loop."""
        self._log("=" * 58)
        self._log("  ARB TRADER — Polymarket BTC 15min Legging")
        self._log("  Capital: $%.2f | Bet: $%.2f/leg" % (self.capital, self.config.BET_SIZE))
        self._log("  OFI threshold: %.1f | Max combined: $%.2f"
                  % (self.config.OFI_THRESHOLD, self.config.MAX_COMBINED_COST))
        self._log("  Leg2 timeout: %ds | Leg2 max price: $%.2f"
                  % (self.config.LEG2_TIMEOUT_S, self.config.LEG2_MAX_PRICE))
        self._log("  Poll interval: %.1fs" % self.config.POLL_INTERVAL_S)
        self._log("=" * 58)

        self._current_window = self._window_id()
        start_time = time.time()

        while True:
            try:
                # Find current market
                window_ts = self._window_id()
                market = find_market(window_ts)

                if market is None:
                    self._log("NO_MARKET window=%d — waiting..." % window_ts)
                    await asyncio.sleep(self.config.POLL_INTERVAL_S)
                    continue

                # Fetch orderbooks
                up_book = get_orderbook(market.up_token_id)
                down_book = get_orderbook(market.down_token_id)

                # Run state machine
                self._tick(market, up_book, down_book)

            except Exception as e:
                self._log("ERROR: %s" % str(e))

            # Duration check
            if duration_minutes > 0:
                elapsed = (time.time() - start_time) / 60
                if elapsed >= duration_minutes:
                    self._log("Duration limit reached (%.0f min)" % elapsed)
                    break

            await asyncio.sleep(self.config.POLL_INTERVAL_S)

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
