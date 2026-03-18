#!/usr/bin/env python3
"""
Build pro-level training data with multi-timeframe features.

Features categories:
  1. Current window (1 minute of data) - micro signal
  2. Previous window stats - recent context
  3. Multi-timeframe trend (15min, 1h, 4h) - macro context
  4. Volatility regime - adapt timing
  5. Time/cyclical - market behavior patterns
  6. Hurst exponent - market regime (trending vs mean-reverting)
  7. Realized volatility ratio - micro vs macro vol regime
  8. Point of Control distance - institutional value area
  9. Seasonal win rate - intraday/intraweek patterns
"""

import sys
sys.path.insert(0, ".")

import pandas as pd
import numpy as np
import ta

print("=" * 70)
print("  BUILDING PRO TRAINING DATA V2 (with deep memory features)")
print("=" * 70)


# ──────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────

def _hurst_exponent(returns: np.ndarray, min_lag: int = 10, max_lag: int = 100) -> float:
    """Compute Hurst exponent via log-log regression on return dispersion.

    H > 0.6 = trending market (momentum favored)
    H < 0.4 = mean-reverting market (contrarian favored)
    H ≈ 0.5 = random walk (no edge from regime)
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
            std = float(np.std(diff))
            tau.append(max(std, 1e-10))
        poly = np.polyfit(np.log(np.array(lags)), np.log(np.array(tau)), 1)
        h = float(poly[0])
        if h < 0.01 or h > 0.99:
            return 0.5  # extreme = unreliable, return neutral
        return h
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


# ──────────────────────────────────────────
# Load raw data
# ──────────────────────────────────────────
df = pd.read_parquet("data/BTCUSDT-1m-combined.parquet")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

df_funding = pd.read_parquet("data/BTCUSDT-funding-rates.parquet")
if df_funding.index.tz is not None:
    df_funding.index = df_funding.index.tz_localize(None)

print("Loaded %d 1-min candles: %s to %s" % (len(df), df.index.min(), df.index.max()))

# ──────────────────────────────────────────
# Build 15min labels
# ──────────────────────────────────────────
df_15min = df.resample("15min").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
}).dropna()
df_15min["label"] = (df_15min["close"] >= df_15min["open"]).astype(int)
print("15-min windows: %d | UP=%.4f" % (len(df_15min), df_15min["label"].mean()))

# ──────────────────────────────────────────
# Pre-compute seasonal profile from full dataset
# (hour × day_of_week → historical win rate for 15-min windows)
# ──────────────────────────────────────────
print("Computing seasonal profile...")
df_seasonal = df_15min.copy()
df_seasonal["hour"] = df_seasonal.index.hour
df_seasonal["dow"] = df_seasonal.index.dayofweek  # 0=Monday

seasonal_profile = df_seasonal.groupby(["dow", "hour"])["label"].agg(
    seasonal_mean=lambda x: x.mean() - 0.5,  # center around 0
    seasonal_wr="mean",
    seasonal_std="std",
).reset_index()
seasonal_profile["seasonal_z"] = (
    seasonal_profile["seasonal_mean"] / (seasonal_profile["seasonal_std"] + 1e-8)
)

# Save for live use
seasonal_profile.to_parquet("data/seasonal_profile.parquet", index=False)
print("Seasonal profile: %d (dow, hour) combinations saved" % len(seasonal_profile))

# ──────────────────────────────────────────
# Pre-compute technical indicators on full 1-min data
# ──────────────────────────────────────────
close = df["close"]
open_ = df["open"]
high = df["high"]
low = df["low"]
volume = df["volume"]
returns = close.pct_change()

ema9 = close.ewm(span=9, adjust=False).mean()
ema21 = close.ewm(span=21, adjust=False).mean()
ema50 = close.ewm(span=50, adjust=False).mean()
sma20 = close.rolling(20).mean()
std20 = close.rolling(20).std()
rsi = ta.momentum.rsi(close, window=14) / 100.0

# Pre-compute Parkinson HL vol (rolling)
hl_sq = np.log(high / low) ** 2
park_15 = hl_sq.rolling(15).mean()
park_60 = hl_sq.rolling(60).mean()

# Take features at minute 1 of each 15-min window
minute_1_mask = df.index.minute % 15 == 1
feat_times = df.index[minute_1_mask]
print("Feature timestamps (minute 1): %d" % len(feat_times))

features = []
labels = []
timestamps = []

for ts in feat_times:
    # Find corresponding 15-min window
    window_start = ts - pd.Timedelta(minutes=1)
    window_start = window_start.floor("15min")

    # Get label
    if window_start not in df_15min.index:
        continue
    label = df_15min.loc[window_start, "label"]

    # Get data available at minute 1
    loc = df.index.get_loc(ts)
    if loc < 1000:  # Need 1000+ candles for Hurst 1000
        continue

    c = close.iloc[loc]
    o = open_.iloc[loc]
    h = high.iloc[loc]
    l = low.iloc[loc]
    v = volume.iloc[loc]
    w_open = df.loc[window_start, "open"] if window_start in df.index else c

    feat = {}
    pre = loc - 1  # Last candle before current one (no leakage)

    # ── CAT 1: Current window micro-signal ──
    # Zeroed to match minute 0 live entry (model must learn WITHOUT these)
    feat["window_delta_m1"] = 0.0
    feat["first_candle_body"] = 0.0
    feat["first_candle_direction"] = 0.0
    feat["first_candle_volume"] = 1.0

    # ── CAT 2: Recent momentum (BEFORE current candle to avoid leakage) ──
    feat["momentum_5m"] = (close.iloc[pre] - close.iloc[pre-5]) / close.iloc[pre-5]
    feat["momentum_15m"] = (close.iloc[pre] - close.iloc[pre-15]) / close.iloc[pre-15]
    feat["momentum_30m"] = (close.iloc[pre] - close.iloc[pre-30]) / close.iloc[pre-30]
    feat["acceleration_5m"] = returns.iloc[pre-5:pre+1].diff().iloc[-1]

    # ── CAT 3: Multi-timeframe trend (BEFORE current candle) ──
    feat["trend_1h"] = (close.iloc[pre] - close.iloc[pre-60]) / close.iloc[pre-60]
    feat["trend_4h"] = (close.iloc[pre] - close.iloc[pre-240]) / close.iloc[pre-240]
    feat["ema_cross_9_21"] = (ema9.iloc[pre] - ema21.iloc[pre]) / ema21.iloc[pre]
    feat["ema_cross_21_50"] = (ema21.iloc[pre] - ema50.iloc[pre]) / ema50.iloc[pre]
    feat["price_vs_ema50"] = (close.iloc[pre] - ema50.iloc[pre]) / ema50.iloc[pre]

    # ── CAT 4: Volatility regime (BEFORE current candle) ──
    feat["volatility_15m"] = returns.iloc[pre-15:pre+1].std()
    feat["volatility_1h"] = returns.iloc[pre-60:pre+1].std()
    feat["volatility_ratio"] = feat["volatility_15m"] / (feat["volatility_1h"] + 1e-10)
    bb_width = (std20.iloc[pre] * 4) / (sma20.iloc[pre] + 1e-10)
    feat["bollinger_width"] = bb_width
    feat["z_score"] = (close.iloc[pre] - sma20.iloc[pre]) / (std20.iloc[pre] + 1e-10)

    # ── CAT 5: RSI ──
    feat["rsi_14"] = rsi.iloc[pre] if not np.isnan(rsi.iloc[pre]) else 0.5
    feat["rsi_extreme"] = 1.0 if feat["rsi_14"] > 0.70 or feat["rsi_14"] < 0.30 else 0.0

    # ── CAT 6: Volume profile ──
    feat["volume_ratio_5m"] = volume.iloc[pre] / (volume.iloc[pre-5:pre].mean() + 1e-10)
    feat["volume_trend"] = volume.iloc[pre-5:pre+1].mean() / (volume.iloc[pre-30:pre-5].mean() + 1e-10)

    # ── CAT 7: Previous windows context ──
    prev_w1 = window_start - pd.Timedelta(minutes=15)
    prev_w2 = window_start - pd.Timedelta(minutes=30)
    prev_w3 = window_start - pd.Timedelta(minutes=45)

    if prev_w1 in df_15min.index:
        pw = df_15min.loc[prev_w1]
        feat["prev1_was_up"] = float(pw["label"])
        feat["prev1_delta"] = (pw["close"] - pw["open"]) / pw["open"]
        vol_window = []
        for j in range(1, 11):
            prev_check = window_start - pd.Timedelta(minutes=15 * j)
            if prev_check in df_15min.index:
                vol_window.append(df_15min.loc[prev_check, "volume"])
        avg_vol = np.mean(vol_window) if vol_window else 1.0
        feat["prev1_volume"] = pw["volume"] / (avg_vol + 1e-10)
    else:
        feat["prev1_was_up"] = 0.5
        feat["prev1_delta"] = 0.0
        feat["prev1_volume"] = 1.0

    streak = 0
    for prev_ts in [prev_w1, prev_w2, prev_w3]:
        if prev_ts in df_15min.index:
            streak += 1 if df_15min.loc[prev_ts, "label"] == 1 else -1
        else:
            break
    feat["streak_3"] = streak
    feat["reversal_signal"] = 1.0 if abs(streak) >= 2 else 0.0

    # ── CAT 8: Time features ──
    hour = ts.hour + ts.minute / 60.0
    feat["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    feat["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    feat["is_us_session"] = 1.0 if 14 <= ts.hour <= 21 else 0.0
    feat["is_asia_session"] = 1.0 if 0 <= ts.hour <= 8 else 0.0

    # ── CAT 9: Funding rate ──
    funding_idx = df_funding.index[df_funding.index <= ts]
    if len(funding_idx) > 0:
        feat["funding_rate"] = float(df_funding.loc[funding_idx[-1], "funding_rate"])
    else:
        feat["funding_rate"] = 0.0

    # ── CAT 10: Hurst exponent (market regime) ──
    # Use 5-min resampled returns to avoid 1-min microstructure noise
    ret_vals = returns.iloc[pre-999:pre+1].dropna().values
    if len(ret_vals) >= 100:
        n5 = (len(ret_vals) // 5) * 5
        ret_5m = ret_vals[-n5:].reshape(-1, 5).sum(axis=1)
    else:
        ret_5m = ret_vals
    ret_5m_short = ret_5m[-100:] if len(ret_5m) >= 100 else ret_5m
    feat["hurst_500"] = _hurst_exponent(ret_5m_short, min_lag=5, max_lag=40)
    feat["hurst_1000"] = _hurst_exponent(ret_5m, min_lag=5, max_lag=80)
    feat["hurst_regime"] = feat["hurst_500"] - feat["hurst_1000"]
    # Positive = local market more trending than macro → continuation expected
    # Negative = regime rotation in progress

    # ── CAT 11: Realized volatility ratio (Parkinson) ──
    rv_15m = float(np.sqrt(park_15.iloc[pre] / (4 * np.log(2))))
    rv_1h = float(np.sqrt(park_60.iloc[pre] / (4 * np.log(2))))
    feat["rv_ratio"] = rv_15m / (rv_1h + 1e-10)
    # >1 = short-term vol elevated vs 1h baseline → volatile micro regime
    # <0.5 = quiet market → low signal strength

    # Funding / RV divergence (squeeze indicator)
    feat["funding_rv_divergence"] = feat["funding_rate"] / (rv_15m + 1e-8) * 1000
    # High positive = funding up + vol low → crowded longs, squeeze risk UP

    # ── CAT 12: Point of Control distance (value area) ──
    # Use last 24h (1440 1-min candles) as the value area window
    lookback = min(1440, pre)
    close_poc_arr = close.iloc[pre-lookback:pre+1].values
    vol_poc_arr = volume.iloc[pre-lookback:pre+1].values
    poc_price = _compute_poc(close_poc_arr, vol_poc_arr)
    # True 4h range: max high - min low over 240 candles (not mean of 1-min ranges)
    atr_4h = float(high.iloc[pre-239:pre+1].max() - low.iloc[pre-239:pre+1].min())
    feat["poc_distance"] = (float(close.iloc[pre]) - poc_price) / (atr_4h + 1e-10)
    # >+2 = BTC far above POC → mean reversion probable → signal DOWN
    # <-2 = BTC far below POC → bounce probable → signal UP

    # ── CAT 13: Seasonal profile (intraday/intraweek patterns) ──
    hour_val = ts.hour
    dow_val = ts.dayofweek
    row = seasonal_profile[
        (seasonal_profile["hour"] == hour_val) & (seasonal_profile["dow"] == dow_val)
    ]
    if len(row) > 0:
        feat["seasonal_mean"] = float(row["seasonal_mean"].values[0])
        feat["seasonal_wr"] = float(row["seasonal_wr"].values[0])
        feat["seasonal_z"] = float(row["seasonal_z"].values[0])
    else:
        feat["seasonal_mean"] = 0.0
        feat["seasonal_wr"] = 0.5
        feat["seasonal_z"] = 0.0

    features.append(feat)
    labels.append(label)
    timestamps.append(window_start)

# Build DataFrames
X = pd.DataFrame(features, index=timestamps)
y = pd.Series(labels, index=timestamps, name="label")

# Clean
X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

print("\nFinal dataset:")
print("  Samples: %d" % len(X))
print("  Features: %d" % X.shape[1])
print("  Feature names: %s" % list(X.columns))
print("  Label dist: UP=%.4f DOWN=%.4f" % (y.mean(), 1 - y.mean()))
print("  Date range: %s to %s" % (X.index.min(), X.index.max()))

# Save
X.to_parquet("data/training_features_v2.parquet")
pd.DataFrame({"label": y}).to_parquet("data/training_labels_v2.parquet")

print("\nSaved to data/training_features_v2.parquet")
print("Saved to data/seasonal_profile.parquet")
print("DONE!")
