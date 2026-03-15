"""
Paper trading engine - runs the full ML pipeline live without placing real orders.

Connects to Binance WebSocket for real-time 1min klines, computes features at
minute 3 of each 5-min window, runs the model, then checks the actual outcome
at minute 5. Logs everything to a JSON file for performance analysis.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import websockets

from bot.config import Config
from bot.features import FeatureEngine
from bot.model import BotModel


class PaperTrader:
    def __init__(self, config: Config | None = None, capital: float = 100.0):
        self.config = config or Config()
        self.model = BotModel()
        self.model.load(self.config.MODELS_DIR)
        self.features = FeatureEngine()

        # State
        self.capital = capital
        self.initial_capital = capital
        self.candles: list[dict] = []
        self.trades: list[dict] = []
        self.pending_prediction: dict | None = None
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.paused_until = 0.0

        # Log file
        os.makedirs(self.config.DATA_DIR, exist_ok=True)
        self.log_path = os.path.join(self.config.DATA_DIR, "paper_trades.json")

        # Stats
        self.windows_seen = 0
        self.trades_taken = 0
        self.trades_skipped = 0

    def _fetch_recent_candles(self, limit: int = 60):
        """Pre-load recent 1min candles from Binance REST API for instant warmup."""
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": "BTCUSDT", "interval": "1m", "limit": limit}
        self._log("Fetching last %d candles from Binance REST API..." % limit)
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for k in data[:-1]:  # Skip the last one (still open)
            candle = {
                "timestamp": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "taker_buy_volume": float(k[9]),
            }
            self.candles.append(candle)

        self._log("Loaded %d historical candles (warmup ready)" % len(self.candles))

    def _candles_to_df(self) -> pd.DataFrame:
        """Convert candle list to DataFrame matching features.py format."""
        df = pd.DataFrame(self.candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        df = df.sort_index()
        return df

    def _minute_in_window(self, ts_ms: int) -> int:
        """Get minute position within 5-min window (0-4)."""
        ts_sec = ts_ms / 1000
        return int((ts_sec % 300) / 60)

    def _window_id(self, ts_ms: int) -> int:
        """Get window start timestamp (floored to 5min)."""
        ts_sec = ts_ms / 1000
        return int(ts_sec // 300) * 300

    def _compute_kelly_bet_realistic(self, edge: float, entry_price: float) -> float:
        """Quarter-Kelly position sizing with realistic Polymarket odds.

        On Polymarket binary markets:
        - You pay `entry_price` for a token
        - Win: token pays $1, profit = (1 - entry_price)
        - Lose: token pays $0, loss = entry_price
        - Odds (b) = (1 - entry_price) / entry_price

        Kelly: f = (bp - q) / b where p=win_prob, q=1-p, b=odds
        Simplified for binary: f = edge / (1 - entry_price)
        """
        if edge <= 0:
            return 0.0

        # Payout ratio (how much you win per dollar risked)
        b = (1 - entry_price) / entry_price
        # Kelly fraction
        kelly = edge / (1 - entry_price)
        quarter_kelly = kelly * 0.25

        bet = self.capital * quarter_kelly
        bet = max(self.config.MIN_BET, min(bet, self.config.MAX_BET))
        bet = min(bet, self.capital * self.config.MAX_BET_FRACTION)

        return round(bet, 2)

    def _check_risk_gates(self) -> str | None:
        """Check risk management gates. Returns reason if blocked, None if OK."""
        now = time.time()
        if now < self.paused_until:
            remaining = int(self.paused_until - now)
            return "circuit_breaker (paused %ds)" % remaining

        if self.daily_pnl <= -(self.capital * self.config.DAILY_STOP_LOSS):
            return "daily_stop_loss (%.2f)" % self.daily_pnl

        drawdown = (self.initial_capital - self.capital) / self.initial_capital
        if drawdown >= self.config.MAX_DRAWDOWN:
            return "max_drawdown (%.2f%%)" % (drawdown * 100)

        return None

    def _on_prediction(self, ts_ms: int, prob: float, confidence: float):
        """Handle a new prediction at minute 3."""
        self.windows_seen += 1
        window_id = self._window_id(ts_ms)
        direction = "UP" if prob >= 0.5 else "DOWN"

        # Simulate realistic Polymarket market price.
        # The market is ~50/50 with slight bias toward UP (flat = UP).
        # Market price hovers around 0.50-0.52. We simulate 0.51 for YES.
        market_price = 0.51
        # Our entry price is the market price for the side we're buying
        entry_price = market_price if direction == "UP" else (1 - market_price)

        # Edge = our model prob - market price
        # (what we think it's worth - what we pay)
        model_prob_for_side = prob if direction == "UP" else (1 - prob)
        edge = model_prob_for_side - entry_price

        # Risk gates
        risk_block = self._check_risk_gates()
        if risk_block:
            self._log("SKIP window=%d | reason=%s" % (window_id, risk_block))
            self.trades_skipped += 1
            return

        # Confidence gate
        if confidence < self.config.MIN_CONFIDENCE:
            self._log(
                "SKIP window=%d | confidence=%.4f < %.2f"
                % (window_id, confidence, self.config.MIN_CONFIDENCE)
            )
            self.trades_skipped += 1
            return

        # Edge gate: our model probability must exceed market price + min_edge
        if edge < self.config.MIN_EDGE:
            self._log("SKIP window=%d | edge=%.4f < %.2f" % (window_id, edge, self.config.MIN_EDGE))
            self.trades_skipped += 1
            return

        # Calculate bet using Kelly with the actual edge
        bet_size = self._compute_kelly_bet_realistic(edge, entry_price)
        if bet_size <= 0:
            self._log("SKIP window=%d | bet_size=0" % window_id)
            self.trades_skipped += 1
            return

        # Record pending prediction (will be resolved at window close)
        self.pending_prediction = {
            "window_id": window_id,
            "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
            "direction": direction,
            "prob": round(float(prob), 6),
            "confidence": round(float(confidence), 6),
            "edge": round(float(edge), 6),
            "entry_price": round(float(entry_price), 4),
            "market_price": market_price,
            "bet_size": float(bet_size),
            "capital_before": round(self.capital, 2),
        }

        self._log(
            "PREDICT window=%d | %s prob=%.4f edge=%.4f entry=%.2f bet=$%.2f capital=$%.2f"
            % (window_id, direction, prob, edge, entry_price, bet_size, self.capital)
        )

    def _resolve_prediction(self, window_open: float, window_close: float):
        """Resolve a pending prediction with actual outcome."""
        if self.pending_prediction is None:
            return

        pred = self.pending_prediction
        actual_up = window_close >= window_open
        actual = "UP" if actual_up else "DOWN"
        won = pred["direction"] == actual

        if won:
            # Polymarket: buy token at entry_price, pays $1 on win
            # Profit = bet_size * (1 - entry_price) / entry_price
            pnl = round(pred["bet_size"] * (1 - pred["entry_price"]) / pred["entry_price"], 4)
            self.consecutive_losses = 0
        else:
            # Loss = full bet amount
            pnl = -pred["bet_size"]
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.CIRCUIT_BREAKER_LOSSES:
                self.paused_until = time.time() + self.config.CIRCUIT_BREAKER_PAUSE_MIN * 60
                self._log(
                    "CIRCUIT BREAKER: %d consecutive losses, pausing %d min"
                    % (self.consecutive_losses, self.config.CIRCUIT_BREAKER_PAUSE_MIN)
                )

        self.capital += pnl
        self.daily_pnl += pnl
        self.trades_taken += 1

        trade = {
            **pred,
            "actual": actual,
            "won": won,
            "pnl": round(pnl, 4),
            "capital_after": round(self.capital, 2),
            "window_open_price": round(window_open, 2),
            "window_close_price": round(window_close, 2),
        }
        self.trades.append(trade)
        self._save_trade(trade)

        emoji = "WIN" if won else "LOSS"
        self._log(
            "%s window=%d | pred=%s actual=%s | pnl=$%.2f | capital=$%.2f | open=%.2f close=%.2f"
            % (emoji, pred["window_id"], pred["direction"], actual, pnl, self.capital,
               window_open, window_close)
        )

        self.pending_prediction = None

    def _save_trade(self, trade: dict):
        """Append trade to JSON log file."""
        # Convert numpy types to Python native for JSON serialization
        clean = {}
        for k, v in trade.items():
            if isinstance(v, (np.floating, np.float32, np.float64)):
                clean[k] = float(v)
            elif isinstance(v, (np.integer, np.int32, np.int64)):
                clean[k] = int(v)
            elif isinstance(v, np.bool_):
                clean[k] = bool(v)
            else:
                clean[k] = v

        trades = []
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r") as f:
                    trades = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                trades = []
        trades.append(clean)
        with open(self.log_path, "w") as f:
            json.dump(trades, f, indent=2)

    def _log(self, msg: str):
        """Print timestamped log message."""
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print("[%s] %s" % (now, msg))

    def print_stats(self):
        """Print current performance summary."""
        print("\n" + "=" * 60)
        print("  PAPER TRADING STATS")
        print("=" * 60)
        print("  Windows seen: %d" % self.windows_seen)
        print("  Trades taken: %d" % self.trades_taken)
        print("  Trades skipped: %d" % self.trades_skipped)

        if self.trades_taken > 0:
            wins = sum(1 for t in self.trades if t["won"])
            wr = wins / self.trades_taken * 100
            total_pnl = sum(t["pnl"] for t in self.trades)
            print("  Win rate: %.1f%% (%d/%d)" % (wr, wins, self.trades_taken))
            print("  Total PnL: $%.2f" % total_pnl)

        print("  Capital: $%.2f (started $%.2f)" % (self.capital, self.initial_capital))
        print("=" * 60 + "\n")

    async def run(self, duration_minutes: int = 0):
        """
        Connect to Binance WebSocket and run paper trading.

        Args:
            duration_minutes: How long to run (0 = indefinitely)
        """
        url = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
        start_time = time.time()
        last_window_id = None
        window_open_price = None

        self._log("Paper trader starting...")
        self._log("Model loaded from %s" % self.config.MODELS_DIR)
        self._log("Min confidence: %.2f | Min edge: %.2f" % (
            self.config.MIN_CONFIDENCE, self.config.MIN_EDGE))
        self._log("Starting capital: $%.2f" % self.capital)

        # Pre-load recent candles so we can predict immediately
        try:
            self._fetch_recent_candles(60)
        except Exception as e:
            self._log("WARNING: Could not fetch historical candles: %s" % str(e))

        self._log("Press Ctrl+C to stop\n")

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    self._log("Connected to Binance WebSocket")

                    async for message in ws:
                        data = json.loads(message)
                        kline = data.get("k", {})

                        if not kline.get("x", False):
                            # Kline not closed yet, skip
                            continue

                        # Store closed 1min candle
                        candle = {
                            "timestamp": kline["t"],
                            "open": float(kline["o"]),
                            "high": float(kline["h"]),
                            "low": float(kline["l"]),
                            "close": float(kline["c"]),
                            "volume": float(kline["v"]),
                            "taker_buy_volume": float(kline["V"]),
                        }
                        self.candles.append(candle)

                        # Keep last 60 candles (1 hour buffer for feature warmup)
                        if len(self.candles) > 60:
                            self.candles = self.candles[-60:]

                        ts_ms = kline["t"]
                        minute_pos = self._minute_in_window(ts_ms)
                        current_window = self._window_id(ts_ms)

                        # Track window open price
                        if current_window != last_window_id:
                            # New window started - resolve previous prediction
                            if self.pending_prediction is not None and last_window_id is not None:
                                # Find open/close of the predicted window
                                pred_window = self.pending_prediction["window_id"]
                                w_candles = [
                                    c for c in self.candles
                                    if self._window_id(c["timestamp"]) == pred_window
                                ]
                                if len(w_candles) >= 4:
                                    w_open = w_candles[0]["open"]
                                    w_close = w_candles[-1]["close"]
                                    self._resolve_prediction(w_open, w_close)
                                else:
                                    self._log(
                                        "SKIP resolution: only %d candles for window %d"
                                        % (len(w_candles), pred_window)
                                    )
                                    self.pending_prediction = None

                            last_window_id = current_window
                            window_open_price = candle["open"]
                            # Reset daily PnL at midnight UTC
                            ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                            if ts_dt.hour == 0 and ts_dt.minute < 5:
                                self.daily_pnl = 0.0

                        # At minute 3: compute features and predict
                        if minute_pos == 3 and len(self.candles) >= 30:
                            try:
                                df = self._candles_to_df()
                                feat = self.features.compute_live(df)
                                X = feat.to_frame().T
                                X.columns = FeatureEngine.FEATURE_NAMES

                                prob = self.model.predict_calibrated(X)[0]
                                confidence = abs(prob - 0.5) * 2

                                self._on_prediction(ts_ms, prob, confidence)
                            except Exception as e:
                                self._log("ERROR computing prediction: %s" % str(e))

                        # Duration check
                        if duration_minutes > 0:
                            elapsed = (time.time() - start_time) / 60
                            if elapsed >= duration_minutes:
                                self._log("Duration limit reached (%.0f min)" % elapsed)
                                self.print_stats()
                                return

            except websockets.exceptions.ConnectionClosed:
                self._log("WebSocket disconnected, reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                self._log("ERROR: %s - reconnecting in 10s..." % str(e))
                await asyncio.sleep(10)

    async def run_from_history(self, df_1min: pd.DataFrame, df_labels: pd.DataFrame):
        """
        Run paper trading on historical data (for fast validation).
        Simulates what would happen minute by minute.
        """
        self._log("Running paper trading on historical data...")
        self._log("%d 1-min candles, %d 5-min windows" % (len(df_1min), len(df_labels)))

        for window_ts in df_labels.index:
            # Get 1min candles up to minute 3 of this window
            window_start = window_ts.floor("5min")
            minute_3 = window_start + pd.Timedelta(minutes=3)
            lookback_start = minute_3 - pd.Timedelta(minutes=60)

            # Slice data available at minute 3
            available = df_1min.loc[lookback_start:minute_3]
            if len(available) < 30:
                continue

            try:
                feat = self.features.compute_live(available)
                X = feat.to_frame().T
                X.columns = FeatureEngine.FEATURE_NAMES

                prob = self.model.predict_calibrated(X)[0]
                confidence = abs(prob - 0.5) * 2

                ts_ms = int(minute_3.timestamp() * 1000)
                self._on_prediction(ts_ms, prob, confidence)

                if self.pending_prediction is not None:
                    # Get actual window open/close
                    window_end = window_start + pd.Timedelta(minutes=4)
                    w_data = df_1min.loc[window_start:window_end]
                    if len(w_data) >= 4:
                        w_open = w_data.iloc[0]["open"]
                        w_close = w_data.iloc[-1]["close"]
                        self._resolve_prediction(w_open, w_close)
            except Exception as e:
                self._log("ERROR at %s: %s" % (window_ts, str(e)))
                self.pending_prediction = None

        self.print_stats()
