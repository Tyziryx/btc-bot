#!/usr/bin/env python3
"""
Build pro-level training data with multi-timeframe features.

Trains at minute 1 of each window - the sweet spot where:
  - We have 1 minute of current window data (some signal)
  - Market price is still ~0.52-0.55 (affordable)
  - Multi-timeframe features give us the real edge

Features categories:
  1. Current window (1 minute of data) - micro signal
  2. Previous window stats - recent context
  3. Multi-timeframe trend (15min, 1h, 4h) - macro context
  4. Volatility regime - adapt timing
  5. Time/cyclical - market behavior patterns
"""

import sys
sys.path.insert(0, ".")

import pandas as pd
import numpy as np
import ta

print("=" * 70)
print("  BUILDING PRO TRAINING DATA (minute 1, multi-timeframe)")
print("=" * 70)

# Load raw data
df = pd.read_parquet("data/BTCUSDT-1m-combined.parquet")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

df_funding = pd.read_parquet("data/BTCUSDT-funding-rates.parquet")
if df_funding.index.tz is not None:
    df_funding.index = df_funding.index.tz_localize(None)

print("Loaded %d 1-min candles: %s to %s" % (len(df), df.index.min(), df.index.max()))

# ──────────────────────────────────────────
# Build 5min labels
# ──────────────────────────────────────────
df_5min = df.resample("5min").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
}).dropna()
df_5min["label"] = (df_5min["close"] >= df_5min["open"]).astype(int)
print("5-min windows: %d | UP=%.4f" % (len(df_5min), df_5min["label"].mean()))

# ──────────────────────────────────────────
# Compute features at minute 1 of each window
# ──────────────────────────────────────────
close = df["close"]
open_ = df["open"]
high = df["high"]
low = df["low"]
volume = df["volume"]
returns = close.pct_change()

# Pre-compute technical indicators on full 1-min data
ema9 = close.ewm(span=9, adjust=False).mean()
ema21 = close.ewm(span=21, adjust=False).mean()
ema50 = close.ewm(span=50, adjust=False).mean()
sma20 = close.rolling(20).mean()
std20 = close.rolling(20).std()
rsi = ta.momentum.rsi(close, window=14) / 100.0

# Take features at minute 1 of each 5-min window
minute_1_mask = df.index.minute % 5 == 1
feat_times = df.index[minute_1_mask]
print("Feature timestamps (minute 1): %d" % len(feat_times))

features = []
labels = []
timestamps = []

for ts in feat_times:
    # Find corresponding 5-min window
    window_start = ts - pd.Timedelta(minutes=1)  # minute 0
    window_start = window_start.floor("5min")

    # Get label
    if window_start not in df_5min.index:
        continue
    label = df_5min.loc[window_start, "label"]

    # Get data available at minute 1
    # We have: all history + first candle of current window
    loc = df.index.get_loc(ts)
    if loc < 300:  # Need at least 5 hours of history
        continue

    c = close.iloc[loc]      # Current close (at minute 1)
    o = open_.iloc[loc]      # Current open
    h = high.iloc[loc]       # Current high
    l = low.iloc[loc]        # Current low
    v = volume.iloc[loc]     # Current volume
    w_open = df.loc[window_start, "open"] if window_start in df.index else c  # Window open price

    feat = {}

    # ── CAT 1: Current window micro-signal (1 minute of data) ──
    feat["window_delta_m1"] = (c - w_open) / w_open  # How much moved in 1st minute
    feat["first_candle_body"] = abs(c - o) / (h - l + 1e-10)  # Body ratio of 1st candle
    feat["first_candle_direction"] = 1.0 if c >= o else -1.0
    feat["first_candle_volume"] = v / (volume.iloc[loc-5:loc].mean() + 1e-10)  # Relative volume

    # ── CAT 2: Recent momentum (BEFORE current candle to avoid leakage) ──
    # Use loc-1 as anchor: the close just before the current window's minute 1
    pre = loc - 1  # last candle before current one
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

    # ── CAT 5: RSI & overbought/oversold (BEFORE current candle) ──
    feat["rsi_14"] = rsi.iloc[pre] if not np.isnan(rsi.iloc[pre]) else 0.5
    feat["rsi_extreme"] = 1.0 if feat["rsi_14"] > 0.70 or feat["rsi_14"] < 0.30 else 0.0

    # ── CAT 6: Volume profile (BEFORE current candle) ──
    feat["volume_ratio_5m"] = volume.iloc[pre] / (volume.iloc[pre-5:pre].mean() + 1e-10)
    feat["volume_trend"] = volume.iloc[pre-5:pre+1].mean() / (volume.iloc[pre-30:pre-5].mean() + 1e-10)

    # ── CAT 7: Previous windows context ──
    prev_w1 = window_start - pd.Timedelta(minutes=5)
    prev_w2 = window_start - pd.Timedelta(minutes=10)
    prev_w3 = window_start - pd.Timedelta(minutes=15)

    if prev_w1 in df_5min.index:
        pw = df_5min.loc[prev_w1]
        feat["prev1_was_up"] = float(pw["label"])
        feat["prev1_delta"] = (pw["close"] - pw["open"]) / pw["open"]
        feat["prev1_volume"] = pw["volume"]
    else:
        feat["prev1_was_up"] = 0.5
        feat["prev1_delta"] = 0.0
        feat["prev1_volume"] = 0.0

    # Streak
    streak = 0
    for i, prev_ts in enumerate([prev_w1, prev_w2, prev_w3]):
        if prev_ts in df_5min.index:
            if df_5min.loc[prev_ts, "label"] == 1:
                streak += 1
            else:
                streak -= 1
        else:
            break
    feat["streak_3"] = streak

    # Reversal pattern: 2+ same direction often reverses
    feat["reversal_signal"] = 1.0 if abs(streak) >= 2 else 0.0

    # ── CAT 8: Time features ──
    hour = ts.hour + ts.minute / 60.0
    feat["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    feat["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    feat["is_us_session"] = 1.0 if 14 <= ts.hour <= 21 else 0.0  # US market hours (UTC)
    feat["is_asia_session"] = 1.0 if 0 <= ts.hour <= 8 else 0.0

    # ── CAT 9: Funding rate ──
    funding_idx = df_funding.index[df_funding.index <= ts]
    if len(funding_idx) > 0:
        feat["funding_rate"] = df_funding.loc[funding_idx[-1], "funding_rate"]
    else:
        feat["funding_rate"] = 0.0

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
print("DONE!")
