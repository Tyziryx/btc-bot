"""
Paper trading engine V2 - runs the V2 Pro model live without placing real orders.

Connects to Binance WebSocket for real-time 1min klines, computes 41 multi-timeframe
features at minute 0 of each 15-min window, runs the calibrated model, fetches REAL
Polymarket prices, then checks the actual outcome at minute 15.
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
    # Cat 1-9: Core features (removed dead first-candle features)
    "momentum_5m", "momentum_15m", "momentum_30m", "acceleration_5m",
    "trend_1h", "trend_4h", "ema_cross_9_21", "ema_cross_21_50", "price_vs_ema50",
    "volatility_15m", "volatility_1h", "volatility_ratio", "bollinger_width", "z_score",
    "rsi_14", "rsi_extreme",
    "volume_ratio_5m", "volume_trend",
    "prev1_was_up", "prev1_delta", "prev1_volume", "streak_3", "reversal_signal",
    "hour_sin", "hour_cos", "is_us_session", "is_asia_session",
    "funding_rate",
    # Cat 10: Hurst exponent (market regime)
    "hurst_500", "hurst_1000", "hurst_regime",
    # Cat 11: Realized volatility ratio
    "rv_ratio", "funding_rv_divergence",
    # Cat 12: Point of Control distance
    "poc_distance",
    # Cat 13: Seasonal profile
    "seasonal_mean", "seasonal_wr", "seasonal_z",
]


def _hurst_exponent(returns: np.ndarray, min_lag: int = 10, max_lag: int = 100) -> float:
    """Compute Hurst exponent via log-log regression on return dispersion.

    H > 0.6 = trending, H < 0.4 = mean-reverting, H ≈ 0.5 = random.
    Returns 0.5 (neutral) on any error or insufficient data.
    """
    try:
        n = len(returns)
        if n < max_lag + 1:
            return 0.5
        actual_max = min(max_lag, n // 2)
        if actual_max <= min_lag:
            return 0.5
        lags = list(range(min_lag, actual_max))
        tau = []
        for lag in lags:
            diff = returns[lag:] - returns[:-lag]
            tau.append(max(float(np.std(diff)), 1e-10))
        poly = np.polyfit(np.log(np.array(lags)), np.log(np.array(tau)), 1)
        h = float(poly[0])
        return max(0.05, min(0.95, h))
    except Exception:
        return 0.5


def _compute_poc(close_arr: np.ndarray, volume_arr: np.ndarray, bins: int = 100) -> float:
    """Point of Control: price level with highest traded volume."""
    try:
        if len(close_arr) < 10:
            return float(close_arr[-1])
        price_min, price_max = close_arr.min(), close_arr.max()
        if price_min >= price_max:
            return float(price_min)
        bin_edges = np.linspace(price_min, price_max, bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_idx = np.clip(np.digitize(close_arr, bin_edges[:-1]) - 1, 0, bins - 1)
        vol_by_bin = np.zeros(bins)
        for i in range(len(close_arr)):
            vol_by_bin[bin_idx[i]] += volume_arr[i]
        return float(bin_centers[np.argmax(vol_by_bin)])
    except Exception:
        return float(close_arr[-1])


def _estimate_entry_price(direction: str, btc_delta: float) -> float:
    """Estimate a conservative entry price when CLOB is empty.

    Based on observed Polymarket pricing behavior:
    - At minute 0: UP ~= 0.50
    - After 1 min: price moves roughly proportional to BTC delta
    - Market makers price aggressively — assume WORSE than mid

    We take the PESSIMISTIC side (higher price = less profit on win).
    """
    # Polymarket price sensitivity to BTC move (empirically ~50-80x)
    # Use 60x as conservative estimate
    sensitivity = 60.0

    if direction == "UP":
        # If BTC went up, UP token is more expensive
        estimated_mid = 0.50 + btc_delta * sensitivity
        # Add 2 cents for spread (we'd buy at the ask, not mid)
        entry = estimated_mid + 0.02
    else:
        # If BTC went down, DOWN token is more expensive
        estimated_mid = 0.50 - btc_delta * sensitivity
        entry = estimated_mid + 0.02

    # Clamp to realistic range
    return max(0.35, min(0.75, entry))


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

        # Minute 0 early entry tracking
        self._last_early_entry_window: int = 0

        # Seasonal profile (precomputed from training data)
        self._seasonal_profile: pd.DataFrame | None = None
        seasonal_path = os.path.join(self.config.DATA_DIR, "seasonal_profile.parquet")
        if os.path.exists(seasonal_path):
            self._seasonal_profile = pd.read_parquet(seasonal_path)
        else:
            # Try relative path
            if os.path.exists("data/seasonal_profile.parquet"):
                self._seasonal_profile = pd.read_parquet("data/seasonal_profile.parquet")

        # Log file (JSONL append-only)
        os.makedirs(self.config.DATA_DIR, exist_ok=True)
        self.log_path = os.path.join(self.config.DATA_DIR, "paper_trades.jsonl")

        # Persistent log file (survives restarts)
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
        self._log_file_path = os.path.join(logs_dir, "bot_%s_%s.log" % (start_ts, git_hash))
        self._log_file = open(self._log_file_path, "a", buffering=1)  # line-buffered
        self._bot_version = git_hash

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
        df_15min = df.resample("15min").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        self.prev_windows = []
        for ts in df_15min.index[-10:]:  # Keep last 10 windows
            row = df_15min.loc[ts]
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
        """Get minute position within 15-min window (0-14)."""
        ts_sec = ts_ms / 1000
        return int((ts_sec % 900) / 60)

    def _window_id(self, ts_ms: int) -> int:
        """Get window start timestamp (floored to 15min)."""
        ts_sec = ts_ms / 1000
        return int(ts_sec // 900) * 900

    def _compute_v2_features(self, df: pd.DataFrame, window_start_ts,
                              early_entry: bool = False) -> dict | None:
        """Compute the 41 V2 Pro features.

        Args:
            df: DataFrame of closed 1-min candles.
            window_start_ts: The 5-min window being predicted.
            early_entry: If True (minute 0 entry), zero out current-window features
                         since no candle from this window has closed yet.
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
        # At early_entry (minute 0): no candle from current window yet → neutral values
        if early_entry:
            feat["window_delta_m1"] = 0.0
            feat["first_candle_body"] = 0.0
            feat["first_candle_direction"] = 0.0
            feat["first_candle_volume"] = 1.0
        else:
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

        # Cat 10: Hurst exponent — market regime (trending vs mean-reverting)
        # Resample 1min → 15min returns: covers 45min-5h lags, relevant for BTC regime
        ret_arr = returns.iloc[max(0, pre-999):pre+1].dropna().values
        if len(ret_arr) >= 150:
            n15 = (len(ret_arr) // 15) * 15
            ret_15m = ret_arr[-n15:].reshape(-1, 15).sum(axis=1)
        else:
            ret_15m = ret_arr
        ret_short = ret_15m[-50:] if len(ret_15m) >= 50 else ret_15m
        feat["hurst_500"] = _hurst_exponent(ret_short, min_lag=3, max_lag=20)
        feat["hurst_1000"] = _hurst_exponent(ret_15m, min_lag=3, max_lag=30)
        feat["hurst_regime"] = feat["hurst_500"] - feat["hurst_1000"]

        # Cat 11: Realized volatility ratio (Parkinson estimator)
        # rv_ratio > 1 = micro vol elevated vs 1h baseline (volatile regime)
        hls_15m = np.log(high.iloc[pre-14:pre+1] / low.iloc[pre-14:pre+1]) ** 2
        hls_1h = np.log(high.iloc[pre-59:pre+1] / low.iloc[pre-59:pre+1]) ** 2
        park_denom = 4 * np.log(2)
        rv_15m = float(np.sqrt(hls_15m.mean() / park_denom)) if len(hls_15m) >= 15 else 0.001
        rv_1h = float(np.sqrt(hls_1h.mean() / park_denom)) if len(hls_1h) >= 60 else 0.001
        feat["rv_ratio"] = rv_15m / (rv_1h + 1e-10)
        feat["funding_rv_divergence"] = self.current_funding_rate / (rv_15m + 1e-8) * 1000

        # Cat 12: Point of Control distance (value area — 24h window or available)
        lookback = min(1440, pre)
        if lookback >= 50:
            close_poc = close.iloc[pre-lookback:pre+1].values
            vol_poc = volume.iloc[pre-lookback:pre+1].values
            poc_price = _compute_poc(close_poc, vol_poc)
            atr_4h = float(high.iloc[pre-239:pre+1].max() - low.iloc[pre-239:pre+1].min())
            feat["poc_distance"] = (float(close.iloc[pre]) - poc_price) / (atr_4h + 1e-10)
        else:
            feat["poc_distance"] = 0.0

        # Cat 13: Seasonal profile (intraday/intraweek historical win rates)
        if self._seasonal_profile is not None and hasattr(ts, 'hour'):
            hour_val = ts.hour
            dow_val = ts.dayofweek
            row = self._seasonal_profile[
                (self._seasonal_profile["hour"] == hour_val) &
                (self._seasonal_profile["dow"] == dow_val)
            ]
            if len(row) > 0:
                feat["seasonal_mean"] = float(row["seasonal_mean"].values[0])
                feat["seasonal_wr"] = float(row["seasonal_wr"].values[0])
                feat["seasonal_z"] = float(row["seasonal_z"].values[0])
            else:
                feat["seasonal_mean"] = 0.0
                feat["seasonal_wr"] = 0.5
                feat["seasonal_z"] = 0.0
        else:
            feat["seasonal_mean"] = 0.0
            feat["seasonal_wr"] = 0.5
            feat["seasonal_z"] = 0.0

        return feat

    def _is_window_boundary(self, ts):
        """Check if timestamp is at a 15-min boundary."""
        if hasattr(ts, 'minute'):
            return ts.minute % 15 == 0
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

    def _on_prediction(self, ts_ms: int, prob: float, confidence: float,
                       raw_prob: float = 0.0, cal_prob_raw: float = 0.0):
        """Handle a new prediction at minute 1."""
        self.windows_seen += 1
        window_id = self._window_id(ts_ms)

        # Cooldown after loss: skip this window
        if window_id <= self.cooldown_until_window:
            self._log("SKIP window=%d | cooldown after loss" % window_id)
            self.trades_skipped += 1
            return

        # Volatility gate: skip flat/quiet markets (coin flip territory)
        if len(self.candles) >= 15:
            recent_highs = [c["high"] for c in self.candles[-15:]]
            recent_lows = [c["low"] for c in self.candles[-15:]]
            recent_close = self.candles[-1]["close"]
            range_15m = (max(recent_highs) - min(recent_lows)) / recent_close
            if range_15m < self.config.MIN_RANGE_15M:
                self._log("SKIP window=%d | low_volatility range=%.4f < %.4f"
                          % (window_id, range_15m, self.config.MIN_RANGE_15M))
                self.trades_skipped += 1
                return

        # rv_ratio gate: skip when micro-vol is too low vs 1h baseline
        feat = getattr(self, '_last_feat', None)
        if feat and feat.get("rv_ratio", 1.0) < self.config.MIN_RV_RATIO:
            self._log("SKIP window=%d | low_rv_ratio=%.3f < %.2f"
                      % (window_id, feat["rv_ratio"], self.config.MIN_RV_RATIO))
            self.trades_skipped += 1
            return

        direction = "UP" if prob >= 0.5 else "DOWN"

        model_prob_for_side = prob if direction == "UP" else (1 - prob)

        # Fetch REAL Polymarket market price (CLOB API, not Gamma indicative)
        market = None
        feat = getattr(self, '_last_feat', None)
        try:
            from bot.polymarket import find_market
            market = find_market(window_id)
            if market is not None:
                source = market.up_source if direction == "UP" else market.down_source
                clob_price = market.up_price if direction == "UP" else market.down_price
                gamma_price = market.gamma_up if direction == "UP" else market.gamma_down
                clob_spread = market.up_spread if direction == "UP" else market.down_spread

                self._log(
                    "MARKET window=%d | up=%.4f(%s) down=%.4f(%s) gamma=%.4f/%.4f"
                    % (window_id, market.up_price, market.up_source,
                       market.down_price, market.down_source,
                       market.gamma_up or 0, market.gamma_down or 0))

                if clob_price > 0 and source in ("clob_ask", "clob_midpoint", "clob_last_trade"):
                    # REAL executable price from CLOB
                    entry_price = clob_price
                else:
                    # No CLOB price — estimate conservatively from BTC move
                    btc_delta = feat.get("window_delta_m1", 0) if feat else 0
                    entry_price = _estimate_entry_price(direction, btc_delta)
                    source = "estimated"
                    self._log("PRICE_EST btc_delta=%.5f -> estimated_entry=%.3f (no CLOB)"
                              % (btc_delta, entry_price))

                # Log comparison of all sources + CLOB delta from fair
                estimated = _estimate_entry_price(
                    direction, feat.get("window_delta_m1", 0) if feat else 0)
                clob_delta = abs(entry_price - 0.50) if entry_price else 0
                self._log("PRICE_COMPARE clob=%.3f gamma=%.3f est=%.3f used=%.3f(%s) spread=%s clob_delta=%.3f"
                          % (clob_price or 0, gamma_price or 0, estimated,
                             entry_price, source,
                             "%.3f" % clob_spread if clob_spread else "n/a",
                             clob_delta))

                # Reject extreme prices (too close to 0 or 1 = no edge available)
                if entry_price < 0.15 or entry_price > 0.85:
                    self._log("SKIP window=%d | extreme_price=%.3f" % (window_id, entry_price))
                    self.trades_skipped += 1
                    return

                # Max entry price: if CLOB already repriced above 0.58, market has moved
                # Ideal entry is at minute 0 when CLOB ≈ 0.50. Skip late repriced markets.
                if entry_price > self.config.MAX_ENTRY_PRICE:
                    self._log("SKIP window=%d | entry=%.3f > MAX_ENTRY_PRICE=%.2f (late entry)"
                              % (window_id, entry_price, self.config.MAX_ENTRY_PRICE))
                    self.trades_skipped += 1
                    return

                # Overround sanity check: UP + DOWN should be ≈ 1.0
                # >5% overround = CLOB is unbalanced (different MMs, stale asks)
                overround = market.up_price + market.down_price - 1.0
                if abs(overround) > 0.05:
                    self._log("SKIP window=%d | overround=%.3f (>0.05, unbalanced CLOB)"
                              % (window_id, overround))
                    self.trades_skipped += 1
                    return
            else:
                entry_price = 0.55  # Conservative fallback (worse than 0.50)
                self._log("MARKET window=%d | no Polymarket data, using fallback=0.55" % window_id)
        except Exception as e:
            entry_price = 0.55
            self._log("MARKET window=%d | Polymarket error: %s, using fallback=0.55" % (window_id, e))

        # Edge = model probability - market price
        edge = model_prob_for_side - entry_price

        # Cap edge at 12% — no model has >12% edge on BTC 5-min
        # High edge is almost always a pricing anomaly or clamp artifact
        if edge > 0.15:
            self._log("SKIP window=%d | edge_too_high=%.3f (>0.15, pricing anomaly)"
                      % (window_id, edge))
            self.trades_skipped += 1
            return

        # Cap perceived edge for bet sizing (prevents oversizing on anomalies)
        edge_for_sizing = min(edge, 0.12)

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
            self._log("SKIP window=%d | edge=%.4f < %.2f (model=%.4f market=%.4f)"
                      % (window_id, edge, self.config.MIN_EDGE, model_prob_for_side, entry_price))
            self.trades_skipped += 1
            return

        # Trend guard: filter counter-trend bets
        if len(self.candles) >= 240:
            closes_1h = [c["close"] for c in self.candles[-60:]]
            closes_4h = [c["close"] for c in self.candles[-240:]]
            trend_1h = (closes_1h[-1] - closes_1h[0]) / closes_1h[0]
            trend_4h = (closes_4h[-1] - closes_4h[0]) / closes_4h[0]
            against_1h = (direction == "DOWN" and trend_1h > 0.001) or \
                         (direction == "UP" and trend_1h < -0.001)
            against_4h = (direction == "DOWN" and trend_4h > 0.001) or \
                         (direction == "UP" and trend_4h < -0.001)
            # Both trends against → hard skip
            if against_1h and against_4h:
                self._log("SKIP window=%d | double_trend_against %s t1h=%.4f t4h=%.4f"
                          % (window_id, direction, trend_1h, trend_4h))
                self.trades_skipped += 1
                return
            # 1h against → require 2x edge
            if against_1h and edge < self.config.MIN_EDGE * 2.0:
                self._log("SKIP window=%d | trend_guard %s against_1h=%.4f edge=%.4f < %.4f"
                          % (window_id, direction, trend_1h, edge, self.config.MIN_EDGE * 2.0))
                self.trades_skipped += 1
                return

        # Bet size = 2% of capital (use capped edge for sizing)
        bet_size = self._compute_bet_size(edge_for_sizing, entry_price)
        if bet_size <= 0:
            self._log("SKIP window=%d | bet_size=0" % window_id)
            self.trades_skipped += 1
            return

        # Determine price source for logging
        if market is not None:
            price_source = market.up_source if direction == "UP" else market.down_source
            if price_source == "none":
                price_source = "estimated"
            gamma_ref = market.gamma_up if direction == "UP" else market.gamma_down
        else:
            price_source = "fallback"
            gamma_ref = None

        # Resolve any existing pending prediction before overwriting
        if self.pending_prediction is not None:
            old_pred = self.pending_prediction
            old_window = old_pred["window_id"]
            w_candles = [
                c for c in self.candles
                if self._window_id(c["timestamp"]) == old_window
            ]
            if len(w_candles) >= 12:
                w_open = w_candles[0]["open"]
                w_close = w_candles[-1]["close"]
                self._resolve_prediction(w_open, w_close)
            else:
                self._log("EXPIRED window=%d | %s (overwritten by new prediction, %d candles)"
                          % (old_window, old_pred["direction"], len(w_candles)))
                self.pending_prediction = None

        # Record pending prediction
        self.pending_prediction = {
            "window_id": window_id,
            "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
            "direction": direction,
            "prob": round(float(prob), 6),
            "raw_prob": round(float(raw_prob), 6),
            "cal_prob_unclamped": round(float(cal_prob_raw), 6),
            "confidence": round(float(confidence), 6),
            "edge": round(float(edge), 6),
            "entry_price": round(float(entry_price), 4),
            "price_source": price_source,
            "gamma_price": round(float(gamma_ref), 4) if gamma_ref else None,
            "bet_size": float(bet_size),
            "capital_before": round(self.capital, 2),
        }

        self._log(
            "PREDICT window=%d | %s prob=%.4f edge=%.4f entry=%.2f bet=$%.2f capital=$%.2f"
            % (window_id, direction, model_prob_for_side, edge, entry_price, bet_size, self.capital)
        )
        self._log("  RISK consec_loss=%d daily_pnl=$%.2f daily_trades=%d drift=%s"
                  % (self.consecutive_losses, self.daily_pnl,
                     self.daily_trades_count, self.drift.summary()))

    def _resolve_prediction(self, window_open: float, window_close: float):
        """Resolve a pending prediction with actual outcome."""
        if self.pending_prediction is None:
            return

        pred = self.pending_prediction

        # Draw threshold: if BTC barely moved, treat as no-trade (refund)
        btc_delta = abs(window_close - window_open) / window_open if window_open > 0 else 0
        if btc_delta < 0.001:
            self._log("DRAW window=%d | %s btc_delta=%.5f < 0.1%% — refund"
                      % (pred["window_id"], pred["direction"], btc_delta))
            self.pending_prediction = None
            self.trades_taken += 1
            self.daily_trades_count += 1
            # Log as draw (no PnL impact)
            trade = {
                "window_id": pred["window_id"],
                "timestamp": pred["timestamp"],
                "direction": pred["direction"],
                "result": "DRAW",
                "btc_delta": round(btc_delta, 6),
                "pnl": 0.0,
                "capital": round(self.capital, 2),
            }
            self.trades.append(trade)
            self._save_trade(trade)
            return

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
            self.cooldown_until_window = pred["window_id"] + 900 * self.config.COOLDOWN_AFTER_LOSS
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
        btc_delta = (window_close - window_open) / window_open * 100
        result_line = "%s %s %-4s | BTC %.2f -> %.2f (%+.3f%%) | entry=$%.2f bet=$%.2f pnl=%s$%.2f" % (
            icon, "WIN " if won else "LOSS", pred["direction"],
            window_open, window_close, btc_delta, pred["entry_price"],
            pred["bet_size"], "+" if pnl >= 0 else "", abs(pnl))
        dash_line = "  Capital: $%.2f (%+.1f%%) | W/L: %d/%d (%.0f%%) | PnL: %s$%.2f | DD: %.1f%%" % (
            self.capital, roi, wins, losses, wr,
            "+" if total_pnl >= 0 else "-", abs(total_pnl), dd)

        print()
        print("  " + result_line)
        print("  " + dash_line)
        self._log("RESULT " + result_line)
        self._log(dash_line)
        if won:
            gross = pred["bet_size"] * (1 - pred["entry_price"]) / pred["entry_price"]
            fee = gross * 0.02
            payout_line = "Payout: gross=$%.4f fee=$%.4f net=$%.4f" % (gross, fee, pnl)
            print("    " + payout_line)
            self._log(payout_line)
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
        """Print timestamped log message and write to persistent log file."""
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = "[%s] %s" % (now, msg)
        print(line)
        if hasattr(self, "_log_file") and self._log_file:
            now_full = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            self._log_file.write("[%s] %s\n" % (now_full, msg))

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
        last_early_entry_window = 0  # Track which window got an early entry

        # Write header to persistent log file
        self._log("=" * 58)
        self._log("BTC PAPER TRADER V2 PRO - START")
        self._log("Version:    %s" % self._bot_version)
        self._log("Log file:   %s" % self._log_file_path)
        self._log("Model:      V2 Pro (41 features @ minute 0 early entry, 15min windows)")
        self._log("Sizing:     2%% of capital per trade")
        self._log("Fees:       2%% Polymarket fee on wins")
        self._log("Confidence: >= %.2f  |  Min edge: >= %.2f" % (
            self.config.MIN_CONFIDENCE, self.config.MIN_EDGE))
        self._log("Capital:    $%.2f" % self.capital)
        self._log("Risk:       %.0f%% daily stop | %.0f%% max DD | %d loss circuit breaker" % (
            self.config.DAILY_STOP_LOSS * 100, self.config.MAX_DRAWDOWN * 100,
            self.config.CIRCUIT_BREAKER_LOSSES))
        self._log("=" * 58)

        # Pre-load candles for feature warmup (1000 for Hurst 1000 + deep memory features)
        try:
            self._fetch_recent_candles(self.config.WARMUP_CANDLES)
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

                        ts_ms = kline["t"]
                        minute_pos = self._minute_in_window(ts_ms)
                        current_window = self._window_id(ts_ms)

                        # === EARLY ENTRY at minute 0 (PRIORITY 1) ===
                        # Trigger prediction as soon as a new 5-min window opens,
                        # BEFORE the first candle closes — CLOB is still at ~$0.50.
                        # Features are computed from closed candles (history only).
                        if (not kline.get("x", False) and   # candle is open
                                minute_pos == 0 and           # start of new window
                                current_window > last_early_entry_window and
                                len(self.candles) >= 250):
                            last_early_entry_window = current_window
                            self._log("EARLY window=%d | minute 0 trigger (CLOB ~$0.50)"
                                      % current_window)
                            try:
                                df = self._candles_to_df()
                                feat = self._compute_v2_features(
                                    df, current_window, early_entry=True)
                                if feat is not None:
                                    self._last_feat = feat
                                    X = pd.DataFrame([feat])[V2_FEATURE_NAMES]
                                    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
                                    raw_prob = self.model.predict_proba(X)[:, 1][0]
                                    iso_prob = float(self.calibrator.predict([raw_prob])[0])
                                    cal_prob = raw_prob * 0.7 + iso_prob * 0.3
                                    cal_prob_raw = cal_prob
                                    self._log("MODEL raw=%.4f cal=%.4f [EARLY@t=0] hurst=%.3f rv=%.3f poc=%.2f"
                                              % (raw_prob, cal_prob, feat["hurst_500"],
                                                 feat["rv_ratio"], feat["poc_distance"]))
                                    confidence = abs(cal_prob - 0.5) * 2
                                    self._on_prediction(ts_ms, cal_prob, confidence,
                                                        raw_prob=raw_prob, cal_prob_raw=cal_prob_raw)
                            except Exception as e:
                                self._log("ERROR early prediction: %s" % str(e))

                        # Only process closed candles for state updates
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

                        # Keep last 1100 candles (~18h for Hurst 1000 + margin)
                        if len(self.candles) > 1100:
                            self.candles = self.candles[-1100:]

                        # Track window transitions
                        if current_window != last_window_id:
                            # Resolve previous prediction — only if it belongs to a PAST window
                            # (early entry sets pending on the CURRENT window at minute 0,
                            #  so we must wait until the NEXT window to resolve it)
                            if self.pending_prediction is not None and last_window_id is not None:
                                pred_window = self.pending_prediction["window_id"]
                                if pred_window < current_window:
                                    w_candles = [
                                        c for c in self.candles
                                        if self._window_id(c["timestamp"]) == pred_window
                                    ]
                                    if len(w_candles) >= 12:
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

                        # Minute 1 fallback: if early entry didn't fire (e.g. bot
                        # restarted mid-window), still predict with window_delta_m1 data.
                        if minute_pos == 1 and len(self.candles) >= 250 and \
                                current_window > last_early_entry_window:
                            last_early_entry_window = current_window  # mark as entered
                            try:
                                df = self._candles_to_df()
                                feat = self._compute_v2_features(df, current_window)

                                if feat is None:
                                    self._log("SKIP: not enough history for features")
                                    continue

                                # Store features for price estimation in _on_prediction
                                self._last_feat = feat

                                # Log BTC context with new features
                                btc_price = df["close"].iloc[-1]
                                self._log(
                                    "FEATURES window=%d | BTC=$%.2f mom5=%.4f rsi=%.2f z=%.2f "
                                    "hurst=%.3f rv=%.3f poc=%.2f seas_wr=%.3f"
                                    % (current_window, btc_price,
                                       feat["momentum_5m"], feat["rsi_14"],
                                       feat["z_score"], feat["hurst_500"],
                                       feat["rv_ratio"], feat["poc_distance"],
                                       feat["seasonal_wr"]))

                                # Build feature vector in correct order
                                X = pd.DataFrame([feat])[V2_FEATURE_NAMES]
                                X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

                                # V2 model prediction + calibration
                                raw_prob = self.model.predict_proba(X)[:, 1][0]
                                iso_prob = float(self.calibrator.predict([raw_prob])[0])
                                cal_prob = raw_prob * 0.7 + iso_prob * 0.3
                                cal_prob_raw = cal_prob

                                # Log raw vs calibrated
                                self._log(
                                    "MODEL raw=%.4f cal=%.4f | accel=%.6f mom5=%.5f z=%.3f"
                                    % (raw_prob, cal_prob,
                                       feat["acceleration_5m"], feat["momentum_5m"],
                                       feat["z_score"]))

                                confidence = abs(cal_prob - 0.5) * 2
                                self._on_prediction(ts_ms, cal_prob, confidence,
                                                    raw_prob=raw_prob, cal_prob_raw=cal_prob_raw)
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
            window_start = window_ts.floor("15min")
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
                iso_prob = float(self.calibrator.predict([raw_prob])[0])
                cal_prob = raw_prob * 0.7 + iso_prob * 0.3
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
