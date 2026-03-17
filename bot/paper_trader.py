"""
Paper trading engine V2 - runs the V2 Pro model live without placing real orders.

Connects to Binance WebSocket for real-time 1min klines, computes 32 multi-timeframe
features at minute 1 of each 5-min window, runs the calibrated model, fetches REAL
Polymarket prices, then checks the actual outcome at minute 5.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import requests
import ta
import websockets

from bot.config import Config


# V2 Pro feature names (must match build_training_data_v2.py)
V2_FEATURE_NAMES = [
    "window_delta_m1", "first_candle_body", "first_candle_direction", "first_candle_volume",
    "momentum_5m", "momentum_15m", "momentum_30m", "acceleration_5m",
    "trend_1h", "trend_4h", "ema_cross_9_21", "ema_cross_21_50", "price_vs_ema50",
    "volatility_15m", "volatility_1h", "volatility_ratio", "bollinger_width", "z_score",
    "rsi_14", "rsi_extreme",
    "volume_ratio_5m", "volume_trend",
    "prev1_was_up", "prev1_delta", "prev1_volume", "streak_3", "reversal_signal",
    "hour_sin", "hour_cos", "is_us_session", "is_asia_session",
    "funding_rate",
]


class PaperTrader:
    def __init__(self, config: Config | None = None, capital: float = 100.0):
        self.config = config or Config()

        # Load V2 Pro model
        v2_dir = os.path.join(os.path.dirname(self.config.MODELS_DIR), "models_v2")
        if not os.path.exists(v2_dir):
            v2_dir = "models_v2"
        self.model = joblib.load(os.path.join(v2_dir, "xgb_model.joblib"))
        self.calibrator = joblib.load(os.path.join(v2_dir, "calibrator.joblib"))

        # State
        self.capital = capital
        self.initial_capital = capital
        self.peak_capital = capital
        self.candles: list[dict] = []
        self.trades: list[dict] = []
        self.pending_prediction: dict | None = None
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.daily_start_capital = capital
        self.paused_until = 0.0

        # Trade frequency limits
        self.daily_trades_count = 0
        self.hourly_trades: list[float] = []
        self.cooldown_until_window = 0

        # Funding rate (fetched live from Binance)
        self.current_funding_rate = 0.0
        self.last_funding_fetch = 0.0

        # Previous 5-min window results (for streak/context features)
        self.prev_windows: list[dict] = []

        # Drift detector
        from bot.drift_detector import DriftDetector
        self.drift = DriftDetector(window=100)

        # Log file (JSONL append-only)
        os.makedirs(self.config.DATA_DIR, exist_ok=True)
        self.log_path = os.path.join(self.config.DATA_DIR, "paper_trades.jsonl")

        # Stats
        self.windows_seen = 0
        self.trades_taken = 0
        self.trades_skipped = 0

    def _fetch_recent_candles(self, limit: int = 300):
        """Pre-load recent 1min candles from Binance REST API for instant warmup.
        Need 300 candles (5 hours) for trend_4h and EMA warmup.
        """
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": "BTCUSDT", "interval": "1m", "limit": limit}
        self._log("Fetching last %d candles from Binance REST API..." % limit)
        resp = requests.get(url, params=params, timeout=15)
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

        # Build previous window history from loaded candles
        self._rebuild_prev_windows()
        self._log("Loaded %d historical candles (warmup ready)" % len(self.candles))

    def _rebuild_prev_windows(self):
        """Rebuild previous 5-min window results from loaded candles."""
        if len(self.candles) < 10:
            return

        df = self._candles_to_df()
        df_5min = df.resample("5min").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        self.prev_windows = []
        for ts in df_5min.index[-10:]:  # Keep last 10 windows
            row = df_5min.loc[ts]
            self.prev_windows.append({
                "ts": ts,
                "open": row["open"],
                "close": row["close"],
                "volume": row["volume"],
                "was_up": 1.0 if row["close"] >= row["open"] else 0.0,
                "delta": (row["close"] - row["open"]) / row["open"],
            })

    def _candles_to_df(self) -> pd.DataFrame:
        """Convert candle list to DataFrame."""
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

    def _compute_v2_features(self, df: pd.DataFrame, window_start_ts) -> dict | None:
        """Compute the 32 V2 Pro features at minute 1 of a window.

        Matches the feature computation in build_training_data_v2.py exactly.
        """
        close = df["close"]
        open_ = df["open"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        returns = close.pct_change()

        # We need the last row to be at minute 1 of the current window
        loc = len(close) - 1
        if loc < 250:  # Need enough history for trend_4h (240 candles)
            return None

        c = close.iloc[loc]
        o = open_.iloc[loc]
        h = high.iloc[loc]
        l = low.iloc[loc]
        v = volume.iloc[loc]

        # Window open price (minute 0 of this window)
        w_open = c  # fallback
        if loc >= 1:
            # The candle before the current one should be minute 0
            w_open = open_.iloc[loc - 1] if self._is_window_boundary(df.index[loc - 1]) else open_.iloc[loc]
            # Better: use the actual window start price
            for i in range(loc, max(loc - 2, -1), -1):
                ts = df.index[i]
                if hasattr(ts, 'minute') and ts.minute % 5 == 0:
                    w_open = open_.iloc[i]
                    break

        feat = {}

        # Pre-compute technical indicators
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        rsi = ta.momentum.rsi(close, window=14) / 100.0

        # Cat 1: Current window micro-signal
        feat["window_delta_m1"] = (c - w_open) / w_open
        feat["first_candle_body"] = abs(c - o) / (h - l + 1e-10)
        feat["first_candle_direction"] = 1.0 if c >= o else -1.0
        feat["first_candle_volume"] = v / (volume.iloc[loc-5:loc].mean() + 1e-10)

        # Cat 2: Recent momentum (BEFORE current candle to match training)
        pre = loc - 1  # last candle before current one
        feat["momentum_5m"] = (close.iloc[pre] - close.iloc[pre-5]) / close.iloc[pre-5]
        feat["momentum_15m"] = (close.iloc[pre] - close.iloc[pre-15]) / close.iloc[pre-15]
        feat["momentum_30m"] = (close.iloc[pre] - close.iloc[pre-30]) / close.iloc[pre-30]
        feat["acceleration_5m"] = returns.iloc[pre-5:pre+1].diff().iloc[-1]

        # Cat 3: Multi-timeframe trend (BEFORE current candle)
        feat["trend_1h"] = (close.iloc[pre] - close.iloc[pre-60]) / close.iloc[pre-60]
        feat["trend_4h"] = (close.iloc[pre] - close.iloc[pre-240]) / close.iloc[pre-240]
        feat["ema_cross_9_21"] = (ema9.iloc[pre] - ema21.iloc[pre]) / ema21.iloc[pre]
        feat["ema_cross_21_50"] = (ema21.iloc[pre] - ema50.iloc[pre]) / ema50.iloc[pre]
        feat["price_vs_ema50"] = (close.iloc[pre] - ema50.iloc[pre]) / ema50.iloc[pre]

        # Cat 4: Volatility regime (BEFORE current candle)
        feat["volatility_15m"] = returns.iloc[pre-15:pre+1].std()
        feat["volatility_1h"] = returns.iloc[pre-60:pre+1].std()
        feat["volatility_ratio"] = feat["volatility_15m"] / (feat["volatility_1h"] + 1e-10)
        bb_width = (std20.iloc[pre] * 4) / (sma20.iloc[pre] + 1e-10)
        feat["bollinger_width"] = bb_width
        feat["z_score"] = (close.iloc[pre] - sma20.iloc[pre]) / (std20.iloc[pre] + 1e-10)

        # Cat 5: RSI (BEFORE current candle)
        rsi_val = rsi.iloc[pre] if not np.isnan(rsi.iloc[pre]) else 0.5
        feat["rsi_14"] = rsi_val
        feat["rsi_extreme"] = 1.0 if rsi_val > 0.70 or rsi_val < 0.30 else 0.0

        # Cat 6: Volume profile (BEFORE current candle)
        feat["volume_ratio_5m"] = volume.iloc[pre] / (volume.iloc[pre-5:pre].mean() + 1e-10)
        feat["volume_trend"] = volume.iloc[pre-5:pre+1].mean() / (volume.iloc[pre-30:pre-5].mean() + 1e-10)

        # Cat 7: Previous windows context
        if len(self.prev_windows) >= 1:
            pw = self.prev_windows[-1]
            feat["prev1_was_up"] = pw["was_up"]
            feat["prev1_delta"] = pw["delta"]
            # Normalize volume by recent average (prevents absolute value drift)
            if len(self.prev_windows) >= 2:
                avg_vol = np.mean([w["volume"] for w in self.prev_windows[-10:]]) or 1.0
                feat["prev1_volume"] = pw["volume"] / (avg_vol + 1e-10)
            else:
                feat["prev1_volume"] = 1.0
        else:
            feat["prev1_was_up"] = 0.5
            feat["prev1_delta"] = 0.0
            feat["prev1_volume"] = 1.0

        # Streak (last 3 windows)
        streak = 0
        for i in range(min(3, len(self.prev_windows))):
            pw = self.prev_windows[-(i+1)]
            if pw["was_up"] == 1.0:
                streak += 1
            else:
                streak -= 1
        feat["streak_3"] = streak
        feat["reversal_signal"] = 1.0 if abs(streak) >= 2 else 0.0

        # Cat 8: Time features
        ts = df.index[loc]
        if hasattr(ts, 'hour'):
            hour = ts.hour + ts.minute / 60.0
        else:
            hour = 12.0
        feat["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        feat["hour_cos"] = np.cos(2 * np.pi * hour / 24)
        feat["is_us_session"] = 1.0 if hasattr(ts, 'hour') and 14 <= ts.hour <= 21 else 0.0
        feat["is_asia_session"] = 1.0 if hasattr(ts, 'hour') and 0 <= ts.hour <= 8 else 0.0

        # Cat 9: Funding rate (live from Binance Futures)
        feat["funding_rate"] = self.current_funding_rate

        return feat

    def _is_window_boundary(self, ts):
        """Check if timestamp is at a 5-min boundary."""
        if hasattr(ts, 'minute'):
            return ts.minute % 5 == 0
        return False

    def _fetch_funding_rate(self) -> float:
        """Fetch latest funding rate from Binance Futures API."""
        try:
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": "BTCUSDT", "limit": 1},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0]["fundingRate"])
        except Exception as e:
            self._log("WARNING: Could not fetch funding rate: %s" % e)
        return 0.0

    def _compute_bet_size(self, edge: float, entry_price: float) -> float:
        """2% of capital per trade with Kelly adjustment."""
        if edge <= 0:
            return 0.0

        # Base: 2% of capital
        bet = self.capital * 0.02
        bet = max(self.config.MIN_BET, bet)
        bet = min(bet, self.config.MAX_BET)

        if self.capital < self.config.MIN_BET:
            return 0.0

        return round(bet, 2)

    def _check_risk_gates(self) -> str | None:
        """Check risk management gates. Returns reason if blocked, None if OK."""
        now = time.time()
        if now < self.paused_until:
            remaining = int(self.paused_until - now)
            return "circuit_breaker (paused %ds)" % remaining

        # Daily stop loss based on start-of-day capital
        daily_limit = -(self.daily_start_capital * self.config.DAILY_STOP_LOSS)
        if self.daily_pnl <= daily_limit:
            return "daily_stop_loss (%.2f / limit %.2f)" % (self.daily_pnl, daily_limit)

        drawdown = (self.peak_capital - self.capital) / self.peak_capital if self.peak_capital > 0 else 0
        if drawdown >= self.config.MAX_DRAWDOWN:
            return "max_drawdown (%.2f%%)" % (drawdown * 100)

        # Trade frequency limits
        if self.daily_trades_count >= self.config.MAX_TRADES_PER_DAY:
            return "max_daily_trades (%d)" % self.daily_trades_count

        recent_hour = [t for t in self.hourly_trades if t > now - 3600]
        self.hourly_trades = recent_hour
        if len(recent_hour) >= self.config.MAX_TRADES_PER_HOUR:
            return "max_hourly_trades (%d)" % len(recent_hour)

        # Drift detector: stop if model is critically degraded
        drift_info = self.drift.check()
        if drift_info.get("should_stop"):
            return "drift_critical (WR=%.1f%%)" % (drift_info["win_rate"] * 100)

        return None

    def _on_prediction(self, ts_ms: int, prob: float, confidence: float):
        """Handle a new prediction at minute 1."""
        self.windows_seen += 1
        window_id = self._window_id(ts_ms)

        # Cooldown after loss: skip this window
        if window_id <= self.cooldown_until_window:
            self._log("SKIP window=%d | cooldown after loss" % window_id)
            self.trades_skipped += 1
            return

        direction = "UP" if prob >= 0.5 else "DOWN"

        model_prob_for_side = prob if direction == "UP" else (1 - prob)

        # Fetch REAL Polymarket market price
        market = None
        try:
            from bot.polymarket import find_market, check_liquidity
            market = find_market(window_id)
            if market is not None:
                market_price = market.up_price if direction == "UP" else market.down_price
                entry_price = market_price

                # Binary market sanity check: up + down should be ≈ 1.0
                # Overround = (up + down) - 1.0 — the market maker's margin
                overround = market.up_price + market.down_price - 1.0
                self._log(
                    "MARKET window=%d | up=%.4f down=%.4f overround=%.4f (REAL Polymarket)"
                    % (window_id, market.up_price, market.down_price, overround)
                )

                # Reject if prices are clearly broken (overround > 10% = stale/bad data)
                if abs(overround) > 0.10:
                    self._log("SKIP window=%d | bad_prices: overround=%.3f (>0.10)" % (window_id, overround))
                    self.trades_skipped += 1
                    return

                # Reject extreme prices (too close to 0 or 1 = no edge available)
                if market_price < 0.15 or market_price > 0.85:
                    self._log("SKIP window=%d | extreme_price=%.3f" % (window_id, market_price))
                    self.trades_skipped += 1
                    return

                # Optional CLOB liquidity check (informational, not blocking for 5-min markets)
                token_id = market.up_token_id if direction == "UP" else market.down_token_id
                liq = check_liquidity(token_id)
                self._log("LIQUIDITY source=%s spread=%.3f depth=$%.0f" % (
                    liq.get("source", "?"), liq["spread"], liq["depth"]))
            else:
                entry_price = 0.52
                self._log("MARKET window=%d | no Polymarket data, using fallback=0.52" % window_id)
        except Exception as e:
            entry_price = 0.52
            self._log("MARKET window=%d | Polymarket error: %s, using fallback=0.52" % (window_id, e))

        # Edge = model probability - market price
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

        # Edge gate
        if edge < self.config.MIN_EDGE:
            self._log("SKIP window=%d | edge=%.4f < %.2f" % (window_id, edge, self.config.MIN_EDGE))
            self.trades_skipped += 1
            return

        # Bet size = 2% of capital
        bet_size = self._compute_bet_size(edge, entry_price)
        if bet_size <= 0:
            self._log("SKIP window=%d | bet_size=0" % window_id)
            self.trades_skipped += 1
            return

        # Record pending prediction
        self.pending_prediction = {
            "window_id": window_id,
            "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
            "direction": direction,
            "prob": round(float(prob), 6),
            "confidence": round(float(confidence), 6),
            "edge": round(float(edge), 6),
            "entry_price": round(float(entry_price), 4),
            "bet_size": float(bet_size),
            "capital_before": round(self.capital, 2),
        }

        self._log(
            "PREDICT window=%d | %s prob=%.4f edge=%.4f entry=%.2f bet=$%.2f capital=$%.2f"
            % (window_id, direction, model_prob_for_side, edge, entry_price, bet_size, self.capital)
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
            # Polymarket: buy at entry_price, pays $1 on win, minus 2% fee on profit
            gross_pnl = pred["bet_size"] * (1 - pred["entry_price"]) / pred["entry_price"]
            fee = gross_pnl * 0.02  # Polymarket 2% fee on winnings
            pnl = round(gross_pnl - fee, 4)
            self.consecutive_losses = 0
        else:
            pnl = -pred["bet_size"]
            self.consecutive_losses += 1
            # Cooldown: skip next N windows after a loss
            self.cooldown_until_window = pred["window_id"] + 300 * self.config.COOLDOWN_AFTER_LOSS
            if self.consecutive_losses >= self.config.CIRCUIT_BREAKER_LOSSES:
                self.paused_until = time.time() + self.config.CIRCUIT_BREAKER_PAUSE_MIN * 60
                self._log(
                    "CIRCUIT BREAKER: %d consecutive losses, pausing %d min"
                    % (self.consecutive_losses, self.config.CIRCUIT_BREAKER_PAUSE_MIN)
                )

        self.capital += pnl
        self.daily_pnl += pnl
        self.peak_capital = max(self.peak_capital, self.capital)
        self.trades_taken += 1
        self.daily_trades_count += 1
        self.hourly_trades.append(time.time())

        # Update drift detector
        self.drift.update(won)

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

        # Print clean trade result + mini dashboard
        wins = sum(1 for t in self.trades if t["won"])
        losses = self.trades_taken - wins
        wr = wins / self.trades_taken * 100 if self.trades_taken else 0
        total_pnl = sum(t["pnl"] for t in self.trades)
        roi = (self.capital / self.initial_capital - 1) * 100
        dd = (self.peak_capital - self.capital) / self.peak_capital * 100 if self.peak_capital > 0 else 0

        icon = "+" if won else "X"
        print()
        print("  %s %s %-4s | BTC %.2f -> %.2f | entry=$%.2f bet=$%.2f pnl=%s$%.2f"
              % (icon, "WIN " if won else "LOSS", pred["direction"],
                 window_open, window_close, pred["entry_price"],
                 pred["bet_size"], "+" if pnl >= 0 else "", abs(pnl)))
        print("    Capital: $%.2f (%+.1f%%) | W/L: %d/%d (%.0f%%) | PnL: %s$%.2f | DD: %.1f%%"
              % (self.capital, roi, wins, losses, wr,
                 "+" if total_pnl >= 0 else "-", abs(total_pnl), dd))
        print()

        # Full dashboard every 10 trades
        if self.trades_taken % 10 == 0:
            self.print_stats()

        # Update previous windows history
        self.prev_windows.append({
            "ts": pred["window_id"],
            "open": window_open,
            "close": window_close,
            "volume": 0.0,  # Not tracked per window in live
            "was_up": 1.0 if actual_up else 0.0,
            "delta": (window_close - window_open) / window_open,
        })
        if len(self.prev_windows) > 10:
            self.prev_windows = self.prev_windows[-10:]

        self.pending_prediction = None

    def _save_trade(self, trade: dict):
        """Append trade as single JSONL line (append-only, crash-safe)."""
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
        with open(self.log_path, "a") as f:
            f.write(json.dumps(clean) + "\n")

    def _log(self, msg: str):
        """Print timestamped log message."""
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print("[%s] %s" % (now, msg))

    def _print_trade_line(self, trade: dict):
        """Print a clean one-line trade result."""
        icon = "+" if trade["won"] else "-"
        status = "WIN " if trade["won"] else "LOSS"
        print(
            "  %s %s %-4s | entry=$%.2f edge=%.2f | bet=$%.2f pnl=%s$%.2f | capital=$%.2f"
            % (
                icon, status, trade["direction"],
                trade["entry_price"], trade["edge"],
                trade["bet_size"],
                "+" if trade["pnl"] >= 0 else "",
                abs(trade["pnl"]),
                trade["capital_after"],
            )
        )

    def print_stats(self):
        """Print full performance dashboard."""
        wins = sum(1 for t in self.trades if t["won"])
        losses = self.trades_taken - wins
        total_pnl = sum(t["pnl"] for t in self.trades)
        roi = (self.capital / self.initial_capital - 1) * 100
        dd = (self.peak_capital - self.capital) / self.peak_capital * 100 if self.peak_capital > 0 else 0

        print()
        print("=" * 58)
        print("  PAPER TRADING DASHBOARD - V2 Pro")
        print("=" * 58)
        print("  Capital:    $%.2f  (started $%.2f)" % (self.capital, self.initial_capital))
        print("  ROI:        %+.1f%%" % roi)
        print("  Total PnL:  %s$%.2f" % ("+" if total_pnl >= 0 else "-", abs(total_pnl)))
        print("  Peak:       $%.2f  |  Drawdown: %.1f%%" % (self.peak_capital, dd))
        print("-" * 58)
        print("  Trades:     %d  |  Wins: %d  |  Losses: %d" % (self.trades_taken, wins, losses))
        if self.trades_taken > 0:
            wr = wins / self.trades_taken * 100
            avg_win = sum(t["pnl"] for t in self.trades if t["won"]) / wins if wins else 0
            avg_loss = sum(t["pnl"] for t in self.trades if not t["won"]) / losses if losses else 0
            print("  Win Rate:   %.1f%%" % wr)
            print("  Avg Win:    +$%.2f  |  Avg Loss: -$%.2f" % (avg_win, abs(avg_loss)))
            if avg_loss != 0:
                print("  Profit Factor: %.2f" % (avg_win * wins / (abs(avg_loss) * losses) if losses else float('inf')))
        print("  Skipped:    %d  |  Windows: %d" % (self.trades_skipped, self.windows_seen))
        print("  Drift:      %s" % self.drift.summary())
        print("  Funding:    %.6f" % self.current_funding_rate)
        print("-" * 58)

        if self.trades:
            print("  LAST 5 TRADES:")
            for t in self.trades[-5:]:
                self._print_trade_line(t)

        print("=" * 58)
        print()

    async def run(self, duration_minutes: int = 0):
        """
        Connect to Binance WebSocket and run paper trading with V2 Pro model.
        Predicts at minute 1 of each 5-min window.
        """
        url = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
        start_time = time.time()
        last_window_id = None

        print()
        print("=" * 58)
        print("  BTC PAPER TRADER V2 PRO")
        print("=" * 58)
        print("  Model:      V2 Pro (32 features @ minute 1)")
        print("  Sizing:     2%% of capital per trade")
        print("  Fees:       2%% Polymarket fee on wins")
        print("  Confidence: >= %.2f  |  Min edge: >= %.2f" % (
            self.config.MIN_CONFIDENCE, self.config.MIN_EDGE))
        print("  Capital:    $%.2f" % self.capital)
        print("  Risk:       %.0f%% daily stop | %.0f%% max DD | %d loss circuit breaker" % (
            self.config.DAILY_STOP_LOSS * 100, self.config.MAX_DRAWDOWN * 100,
            self.config.CIRCUIT_BREAKER_LOSSES))
        print("=" * 58)
        print()

        # Pre-load 300 candles (5 hours) for feature warmup
        try:
            self._fetch_recent_candles(300)
        except Exception as e:
            self._log("WARNING: Could not fetch historical candles: %s" % str(e))

        # Fetch initial funding rate
        self.current_funding_rate = self._fetch_funding_rate()
        self.last_funding_fetch = time.time()
        self._log("Funding rate: %.6f" % self.current_funding_rate)

        self._log("Press Ctrl+C to stop\n")

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    self._log("Connected to Binance WebSocket")

                    async for message in ws:
                        data = json.loads(message)
                        kline = data.get("k", {})

                        if not kline.get("x", False):
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

                        # Keep last 350 candles (~6 hours for trend_4h + margin)
                        if len(self.candles) > 350:
                            self.candles = self.candles[-350:]

                        ts_ms = kline["t"]
                        minute_pos = self._minute_in_window(ts_ms)
                        current_window = self._window_id(ts_ms)

                        # Track window transitions
                        if current_window != last_window_id:
                            # Resolve previous prediction
                            if self.pending_prediction is not None and last_window_id is not None:
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

                            # Reset daily counters at midnight UTC
                            ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                            if ts_dt.hour == 0 and ts_dt.minute < 5:
                                self.daily_pnl = 0.0
                                self.daily_start_capital = self.capital
                                self.daily_trades_count = 0

                            # Refresh funding rate every 4 hours
                            if time.time() - self.last_funding_fetch > 4 * 3600:
                                self.current_funding_rate = self._fetch_funding_rate()
                                self.last_funding_fetch = time.time()
                                self._log("Funding rate: %.6f" % self.current_funding_rate)

                        # At minute 1: compute V2 Pro features and predict
                        if minute_pos == 1 and len(self.candles) >= 250:
                            try:
                                df = self._candles_to_df()
                                feat = self._compute_v2_features(df, current_window)

                                if feat is None:
                                    self._log("SKIP: not enough history for features")
                                    continue

                                # Build feature vector in correct order
                                X = pd.DataFrame([feat])[V2_FEATURE_NAMES]
                                X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

                                # V2 model prediction + calibration
                                raw_prob = self.model.predict_proba(X)[:, 1][0]
                                cal_prob = float(self.calibrator.predict([raw_prob])[0])

                                confidence = abs(cal_prob - 0.5) * 2
                                self._on_prediction(ts_ms, cal_prob, confidence)
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
        """Run paper trading on historical data using V2 Pro model."""
        self._log("Running V2 Pro paper trading on historical data...")
        self._log("%d 1-min candles, %d 5-min windows" % (len(df_1min), len(df_labels)))

        for window_ts in df_labels.index:
            window_start = window_ts.floor("5min")
            minute_1 = window_start + pd.Timedelta(minutes=1)
            lookback_start = minute_1 - pd.Timedelta(minutes=300)

            # Slice data available at minute 1
            available = df_1min.loc[lookback_start:minute_1]
            if len(available) < 250:
                continue

            try:
                self.candles = []
                for _, row in available.iterrows():
                    self.candles.append({
                        "timestamp": int(row.name.timestamp() * 1000) if hasattr(row.name, 'timestamp') else 0,
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                    })

                df = self._candles_to_df() if not isinstance(available, pd.DataFrame) else available
                feat = self._compute_v2_features(available, window_start)

                if feat is None:
                    continue

                X = pd.DataFrame([feat])[V2_FEATURE_NAMES]
                X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

                raw_prob = self.model.predict_proba(X)[:, 1][0]
                cal_prob = float(self.calibrator.predict([raw_prob])[0])
                confidence = abs(cal_prob - 0.5) * 2

                ts_ms = int(minute_1.timestamp() * 1000)
                self._on_prediction(ts_ms, cal_prob, confidence)

                if self.pending_prediction is not None:
                    window_end = window_start + pd.Timedelta(minutes=4)
                    w_data = df_1min.loc[window_start:window_end]
                    if len(w_data) >= 4:
                        w_open = w_data.iloc[0]["open"]
                        w_close = w_data.iloc[-1]["close"]
                        self._resolve_prediction(w_open, w_close)
            except Exception as e:
                self._log("ERROR at %s: %s" % (window_ts, e))
                self.pending_prediction = None

        self.print_stats()
