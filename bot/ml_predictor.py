"""
ML-based directional predictor for Polymarket BTC 15-min markets.

Computes the same v2 features used in training (build_training_data_v2.py)
and runs the saved XGBoost model for live inference.

Usage:
    predictor = MLPredictor()
    predictor.load_history()   # once at startup
    predictor.update_candle(candle_dict)  # on each closed 1m candle
    pred = predictor.predict(ts)  # returns {'direction': 'UP'|'DOWN', 'prob': float}
"""

import os
import logging
from collections import deque
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import joblib

logger = logging.getLogger(__name__)

# ── Hurst exponent helper ─────────────────────────────────────────────────────

def _hurst_exponent(price_arr: np.ndarray, min_lag: int = 3, max_lag: int = 20) -> float:
    try:
        n = len(price_arr)
        if n < max_lag + 1:
            return 0.5
        actual_max = min(max_lag, n // 2)
        if actual_max <= min_lag:
            return 0.5
        lags = list(range(min_lag, actual_max))
        tau = []
        for lag in lags:
            diff = price_arr[lag:] - price_arr[:-lag]
            std = float(np.std(diff))
            tau.append(max(std, 1e-10))
        poly = np.polyfit(np.log(np.array(lags)), np.log(np.array(tau)), 1)
        h = float(poly[0])
        return max(0.05, min(0.95, h))
    except Exception:
        return 0.5


def _compute_poc(close_arr: np.ndarray, volume_arr: np.ndarray, bins: int = 100) -> float:
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


class MLPredictor:
    """
    Live ML predictor using v2 feature set + XGBoost.

    Call load_history() once at startup, then update_candle() on each
    closed 1-min Binance candle. Call predict() at each new 15-min window.
    """

    MODEL_PATH = "data/models/v3_xgb_model.joblib"
    DATA_DIR = "data"
    # Must match training_features_v2 column order exactly
    FEATURE_COLS = [
        'momentum_5m', 'momentum_15m', 'momentum_30m', 'acceleration_5m',
        'trend_1h', 'trend_4h', 'ema_cross_9_21', 'ema_cross_21_50',
        'price_vs_ema50', 'volatility_15m', 'volatility_1h', 'volatility_ratio',
        'bollinger_width', 'z_score', 'rsi_14', 'rsi_extreme',
        'volume_ratio_5m', 'volume_trend', 'prev1_was_up', 'prev1_delta',
        'prev1_volume', 'streak_3', 'reversal_signal', 'hour_sin', 'hour_cos',
        'is_us_session', 'is_asia_session', 'funding_rate', 'hurst_500',
        'hurst_1000', 'hurst_regime', 'rv_ratio', 'funding_rv_divergence',
        'poc_distance', 'seasonal_mean', 'seasonal_wr', 'seasonal_z',
    ]
    # Need at least 1050 candles for Hurst 1000 + warmup
    BUFFER_SIZE = 1500

    def __init__(self, log_fn=None):
        self._log = log_fn or (lambda msg: print("[MLPredictor] %s" % msg))

        # Candle buffer: each entry is (open_time_ms, open, high, low, close, volume)
        self._candles: deque = deque(maxlen=self.BUFFER_SIZE)

        # Pre-computed rolling indicators (updated incrementally)
        self._model = None
        self._scaler = None
        self._calibrator = None
        self._feature_cols = None

        # Seasonal profile (loaded from parquet)
        self._seasonal: pd.DataFrame | None = None

        # Last funding rate (updated from parquet at startup + periodically)
        self._funding_rate: float = 0.0

        # Previous 15-min window results (for streak/prev1 features)
        # Key: window_ts (floored to 15min), value: {'was_up': bool, 'delta': float, 'volume': float}
        self._window_history: dict = {}

        self._loaded = False

    def load_model(self) -> bool:
        """Load the saved XGBoost model. Returns True on success."""
        if not os.path.exists(self.MODEL_PATH):
            self._log("Model not found at %s — ML mode disabled" % self.MODEL_PATH)
            return False
        try:
            bundle = joblib.load(self.MODEL_PATH)
            self._model = bundle['model']
            self._scaler = bundle['scaler']
            self._calibrator = bundle.get('calibrator')
            self._feature_cols = bundle.get('feature_cols', self.FEATURE_COLS)
            metrics = bundle.get('metrics', {})
            self._log("Model loaded — AUC=%.3f, acc@thresh=%.1f%%" % (
                metrics.get('test_roc_auc', 0),
                metrics.get('best_thresh_accuracy', 0) * 100,
            ))
            return True
        except Exception as e:
            self._log("Model load failed: %s" % e)
            return False

    def load_history(self) -> int:
        """
        Load recent Binance 1m candles from parquet files into the buffer.
        Returns number of candles loaded.
        """
        candle_files = sorted([
            f for f in os.listdir(self.DATA_DIR)
            if f.startswith('BTCUSDT-1m-') and f.endswith('.parquet')
            and 'combined' not in f and 'labeled' not in f
        ])

        if not candle_files:
            self._log("No Binance 1m parquet files found in %s" % self.DATA_DIR)
            return 0

        # Load last 2 months to ensure we have enough history
        recent_files = candle_files[-2:]
        frames = []
        for fn in recent_files:
            path = os.path.join(self.DATA_DIR, fn)
            try:
                df = pd.read_parquet(path)
                frames.append(df)
            except Exception as e:
                self._log("Failed to load %s: %s" % (fn, e))

        if not frames:
            return 0

        combined = pd.concat(frames).sort_index()
        # Keep last BUFFER_SIZE candles
        tail = combined.tail(self.BUFFER_SIZE)

        for ts, row in tail.iterrows():
            self._candles.append({
                'ts': ts,
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'close': float(row.get('close', 0)),
                'volume': float(row.get('volume', 0)),
            })

        # Load seasonal profile
        sp_path = os.path.join(self.DATA_DIR, 'seasonal_profile.parquet')
        if os.path.exists(sp_path):
            self._seasonal = pd.read_parquet(sp_path)

        # Load latest funding rate
        fr_path = os.path.join(self.DATA_DIR, 'BTCUSDT-funding-rates.parquet')
        if os.path.exists(fr_path):
            df_fr = pd.read_parquet(fr_path)
            if len(df_fr) > 0:
                self._funding_rate = float(df_fr['funding_rate'].iloc[-1])

        self._loaded = True
        self._log("Loaded %d candles, seasonal=%s, funding=%.6f" % (
            len(self._candles),
            "OK" if self._seasonal is not None else "MISSING",
            self._funding_rate,
        ))
        return len(self._candles)

    def update_candle(self, candle: dict):
        """
        Feed a closed 1-min Binance candle.

        candle: {'ts': datetime, 'open': float, 'high': float,
                 'low': float, 'close': float, 'volume': float}
        """
        self._candles.append(candle)

        # Update window history when a 15-min window closes
        ts = candle.get('ts')
        if ts is None:
            return
        if hasattr(ts, 'minute') and ts.minute % 15 == 14:
            # This candle is the last candle of a 15-min window
            w_start = ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
            w_open = self._get_window_open(w_start)
            w_close = candle['close']
            w_delta = (w_close - w_open) / w_open if w_open > 0 else 0.0
            w_vol = self._get_window_volume(w_start)
            self._window_history[w_start] = {
                'was_up': w_close >= w_open,
                'delta': w_delta,
                'volume': w_vol,
            }

    def _get_window_open(self, window_start) -> float:
        """Get the open price of a 15-min window from candle buffer."""
        for c in self._candles:
            ts = c['ts']
            if hasattr(ts, 'minute') and abs((ts - window_start).total_seconds()) < 60:
                return c['open']
        return 0.0

    def _get_window_volume(self, window_start) -> float:
        """Sum volume for a 15-min window from candle buffer."""
        total = 0.0
        for c in self._candles:
            ts = c['ts']
            if hasattr(ts, 'replace'):
                w = ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
                if w == window_start:
                    total += c['volume']
        return total

    def predict(self, window_ts: datetime) -> dict | None:
        """
        Compute v2 features for the given window timestamp and run the model.

        window_ts: start of the 15-min window (UTC, floored to 15 min)

        Returns:
            {'direction': 'UP'|'DOWN', 'prob': float, 'confidence': float}
            or None if not enough data
        """
        if self._model is None or not self._loaded:
            return None

        candles = list(self._candles)
        n = len(candles)

        if n < 250:
            self._log("Not enough candle history (%d < 250)" % n)
            return None

        # Convert to arrays for fast computation
        closes = np.array([c['close'] for c in candles], dtype=np.float64)
        opens = np.array([c['open'] for c in candles], dtype=np.float64)
        highs = np.array([c['high'] for c in candles], dtype=np.float64)
        lows = np.array([c['low'] for c in candles], dtype=np.float64)
        volumes = np.array([c['volume'] for c in candles], dtype=np.float64)

        pre = n - 1  # Index of the last available candle (before current window opens)
        if pre < 60:
            return None

        feat = {}

        # ── Momentum ─────────────────────────────────────────────────────────
        def safe_pct(new_idx, old_idx):
            if old_idx < 0 or old_idx >= n or new_idx < 0 or new_idx >= n:
                return 0.0
            old = closes[old_idx]
            if old == 0:
                return 0.0
            return (closes[new_idx] - old) / old

        feat['momentum_5m'] = safe_pct(pre, pre - 5)
        feat['momentum_15m'] = safe_pct(pre, pre - 15)
        feat['momentum_30m'] = safe_pct(pre, pre - 30)

        # Acceleration: difference of 5-bar returns at pre and pre-1
        ret_prev = (closes[pre] - closes[pre-1]) / closes[pre-1] if closes[pre-1] > 0 else 0.0
        ret_5ago = (closes[pre-4] - closes[pre-5]) / closes[pre-5] if pre >= 5 and closes[pre-5] > 0 else 0.0
        feat['acceleration_5m'] = ret_prev - ret_5ago

        # ── Multi-timeframe trend ─────────────────────────────────────────────
        feat['trend_1h'] = safe_pct(pre, pre - 60) if pre >= 60 else 0.0
        feat['trend_4h'] = safe_pct(pre, pre - 240) if pre >= 240 else 0.0

        # EMA crossovers
        def ema(arr, span):
            alpha = 2.0 / (span + 1)
            ema_val = arr[0]
            for v in arr[1:]:
                ema_val = alpha * v + (1 - alpha) * ema_val
            return ema_val

        ema9 = ema(closes[max(0, pre-50):pre+1], 9)
        ema21 = ema(closes[max(0, pre-70):pre+1], 21)
        ema50_val = ema(closes[max(0, pre-100):pre+1], 50)

        feat['ema_cross_9_21'] = (ema9 - ema21) / (ema21 + 1e-10)
        feat['ema_cross_21_50'] = (ema21 - ema50_val) / (ema50_val + 1e-10)
        feat['price_vs_ema50'] = (closes[pre] - ema50_val) / (ema50_val + 1e-10)

        # ── Volatility ─────────────────────────────────────────────────────────
        returns_15 = np.diff(closes[pre-16:pre+1]) / closes[pre-16:pre]
        returns_60 = np.diff(closes[pre-61:pre+1]) / closes[pre-61:pre]
        vol_15 = float(np.std(returns_15)) if len(returns_15) > 1 else 0.01
        vol_60 = float(np.std(returns_60)) if len(returns_60) > 1 else 0.01
        feat['volatility_15m'] = vol_15
        feat['volatility_1h'] = vol_60
        feat['volatility_ratio'] = vol_15 / (vol_60 + 1e-10)

        # Bollinger
        sma20 = np.mean(closes[pre-20:pre+1])
        std20 = np.std(closes[pre-20:pre+1])
        feat['bollinger_width'] = (std20 * 4) / (sma20 + 1e-10)
        feat['z_score'] = (closes[pre] - sma20) / (std20 + 1e-10)

        # ── RSI ───────────────────────────────────────────────────────────────
        def compute_rsi(prices, period=14):
            if len(prices) < period + 1:
                return 0.5
            diffs = np.diff(prices[-(period+1):])
            gains = np.where(diffs > 0, diffs, 0)
            losses = np.where(diffs < 0, -diffs, 0)
            avg_gain = np.mean(gains) if np.any(gains) else 0.0
            avg_loss = np.mean(losses) if np.any(losses) else 1e-10
            rs = avg_gain / avg_loss
            return rs / (1 + rs)

        rsi_val = compute_rsi(closes[pre-20:pre+1])
        feat['rsi_14'] = rsi_val
        feat['rsi_extreme'] = 1.0 if rsi_val > 0.70 or rsi_val < 0.30 else 0.0

        # ── Volume ─────────────────────────────────────────────────────────────
        avg_vol_5 = np.mean(volumes[pre-5:pre]) if pre >= 5 else volumes[pre]
        feat['volume_ratio_5m'] = volumes[pre] / (avg_vol_5 + 1e-10)
        avg_recent = np.mean(volumes[pre-5:pre+1]) if pre >= 5 else volumes[pre]
        avg_older = np.mean(volumes[pre-30:pre-5]) if pre >= 30 else avg_recent
        feat['volume_trend'] = avg_recent / (avg_older + 1e-10)

        # ── Previous window context ───────────────────────────────────────────
        prev_w1 = window_ts - timedelta(minutes=15)
        prev_w2 = window_ts - timedelta(minutes=30)
        prev_w3 = window_ts - timedelta(minutes=45)

        def normalize_ts(ts):
            """Remove timezone for comparison."""
            if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                return ts.replace(tzinfo=None)
            return ts

        prev_w1_n = normalize_ts(prev_w1)

        prev1_info = self._window_history.get(prev_w1_n)
        if prev1_info:
            feat['prev1_was_up'] = 1.0 if prev1_info['was_up'] else 0.0
            feat['prev1_delta'] = prev1_info['delta']
            vol_window = [
                self._window_history[normalize_ts(window_ts - timedelta(minutes=15*j))]['volume']
                for j in range(1, 11)
                if normalize_ts(window_ts - timedelta(minutes=15*j)) in self._window_history
            ]
            avg_vol_hist = np.mean(vol_window) if vol_window else 1.0
            feat['prev1_volume'] = prev1_info['volume'] / (avg_vol_hist + 1e-10)
        else:
            # Not enough history yet — use neutral values
            feat['prev1_was_up'] = 0.5
            feat['prev1_delta'] = 0.0
            feat['prev1_volume'] = 1.0

        streak = 0
        for w_ts in [prev_w1_n,
                     normalize_ts(prev_w2),
                     normalize_ts(prev_w3)]:
            info = self._window_history.get(w_ts)
            if info:
                streak += 1 if info['was_up'] else -1
            else:
                break
        feat['streak_3'] = float(streak)
        feat['reversal_signal'] = 1.0 if abs(streak) >= 2 else 0.0

        # ── Time features ─────────────────────────────────────────────────────
        wts = window_ts
        if hasattr(wts, 'tzinfo') and wts.tzinfo is not None:
            wts = wts.replace(tzinfo=None)
        hour = wts.hour + wts.minute / 60.0
        feat['hour_sin'] = float(np.sin(2 * np.pi * hour / 24))
        feat['hour_cos'] = float(np.cos(2 * np.pi * hour / 24))
        feat['is_us_session'] = 1.0 if 14 <= wts.hour <= 21 else 0.0
        feat['is_asia_session'] = 1.0 if 0 <= wts.hour <= 8 else 0.0

        # ── Funding rate ─────────────────────────────────────────────────────
        feat['funding_rate'] = self._funding_rate

        # ── Hurst exponent ────────────────────────────────────────────────────
        price_arr = closes[max(0, pre-999):pre+1]
        if len(price_arr) >= 50:
            price_15m = price_arr[14::15]
        else:
            price_15m = price_arr

        price_short = price_15m[-50:] if len(price_15m) >= 50 else price_15m
        feat['hurst_500'] = _hurst_exponent(price_short, min_lag=3, max_lag=20)
        feat['hurst_1000'] = _hurst_exponent(price_15m, min_lag=3, max_lag=30)
        feat['hurst_regime'] = feat['hurst_500'] - feat['hurst_1000']

        # ── Realized volatility ratio (Parkinson) ────────────────────────────
        def parkinson_vol(h_arr, l_arr):
            if len(h_arr) == 0:
                return 1e-8
            hl_sq = np.log(h_arr / (l_arr + 1e-10)) ** 2
            return float(np.sqrt(np.mean(hl_sq) / (4 * np.log(2))))

        rv_15m = parkinson_vol(highs[pre-15:pre+1], lows[pre-15:pre+1])
        rv_1h = parkinson_vol(highs[pre-60:pre+1], lows[pre-60:pre+1])
        feat['rv_ratio'] = rv_15m / (rv_1h + 1e-10)
        feat['funding_rv_divergence'] = self._funding_rate / (rv_15m + 1e-8) * 1000

        # ── POC distance ──────────────────────────────────────────────────────
        lookback = min(1440, pre)
        poc_price = _compute_poc(
            closes[pre-lookback:pre+1],
            volumes[pre-lookback:pre+1]
        )
        atr_4h = float(highs[pre-239:pre+1].max() - lows[pre-239:pre+1].min()) if pre >= 240 else 1.0
        feat['poc_distance'] = (float(closes[pre]) - poc_price) / (atr_4h + 1e-10)

        # ── Seasonal profile ──────────────────────────────────────────────────
        if self._seasonal is not None:
            hour_val = wts.hour
            dow_val = wts.weekday()
            row = self._seasonal[
                (self._seasonal['hour'] == hour_val) & (self._seasonal['dow'] == dow_val)
            ]
            if len(row) > 0:
                feat['seasonal_mean'] = float(row['seasonal_mean'].values[0])
                feat['seasonal_wr'] = float(row['seasonal_wr'].values[0])
                feat['seasonal_z'] = float(row['seasonal_z'].values[0])
            else:
                feat['seasonal_mean'] = 0.0
                feat['seasonal_wr'] = 0.5
                feat['seasonal_z'] = 0.0
        else:
            feat['seasonal_mean'] = 0.0
            feat['seasonal_wr'] = 0.5
            feat['seasonal_z'] = 0.0

        # ── Run model ─────────────────────────────────────────────────────────
        try:
            feat_array = np.array(
                [feat.get(col, 0.0) for col in self.FEATURE_COLS],
                dtype=np.float32
            ).reshape(1, -1)

            # Handle NaN/inf
            feat_array = np.nan_to_num(feat_array, nan=0.0, posinf=10.0, neginf=-10.0)

            feat_scaled = self._scaler.transform(feat_array)
            prob_raw = self._model.predict_proba(feat_scaled)[0, 1]

            if self._calibrator is not None:
                prob = float(self._calibrator.predict([prob_raw])[0])
            else:
                prob = float(prob_raw)

            direction = 'UP' if prob > 0.5 else 'DOWN'
            confidence = max(prob, 1 - prob)

            return {
                'direction': direction,
                'prob': prob,
                'confidence': confidence,
                'features': {k: round(v, 4) for k, v in feat.items()},
            }

        except Exception as e:
            self._log("Prediction error: %s" % e)
            return None

    @property
    def ready(self) -> bool:
        """True if model and history are loaded and ready for inference."""
        return self._model is not None and self._loaded and len(self._candles) >= 250
