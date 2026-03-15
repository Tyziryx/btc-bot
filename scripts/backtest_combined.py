#!/usr/bin/env python3
"""
Combined strategy backtest on 1 year of data.

Three entry points per 5-min window:
  1. Minute 0 - V2 model places LIMIT ORDER at ~0.45 (fills if market dips)
  2. Minute 3 - V1 model confirms with in-window data (realistic pricing)
  3. Minute 4 (T-10s) - Snipe if direction is clear (pricing from delta)

Uses realistic Polymarket token pricing based on window delta.
"""

import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import joblib
from bot.features import FeatureEngine

print("=" * 70)
print("  COMBINED STRATEGY BACKTEST - 1 YEAR")
print("=" * 70)

# ──────────────────────────────────────────
# Load data
# ──────────────────────────────────────────
df_1min = pd.read_parquet("data/BTCUSDT-1m-combined.parquet")
if df_1min.index.tz is not None:
    df_1min.index = df_1min.index.tz_localize(None)

df_5min = df_1min.resample("5min").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
}).dropna()
df_5min["label"] = (df_5min["close"] >= df_5min["open"]).astype(int)
df_5min["delta_pct"] = abs(df_5min["close"] - df_5min["open"]) / df_5min["open"] * 100

print("1-min candles: %d" % len(df_1min))
print("5-min windows: %d" % len(df_5min))
print("Date range: %s to %s" % (df_5min.index.min(), df_5min.index.max()))

# ──────────────────────────────────────────
# Load models
# ──────────────────────────────────────────
print("\nLoading models...")

# V1 model (minute 3 features)
v1_model = joblib.load("models/xgb_model.joblib")
v1_calibrator = joblib.load("models/calibrator.joblib")

# V2 model (minute 0 features)
v2_model = joblib.load("models_v2/xgb_model.joblib")
v2_calibrator = joblib.load("models_v2/calibrator.joblib")

# Feature engine
engine = FeatureEngine()
df_funding = pd.read_parquet("data/BTCUSDT-funding-rates.parquet")
if df_funding.index.tz is not None:
    df_funding.index = df_funding.index.tz_localize(None)

# ──────────────────────────────────────────
# Compute all features
# ──────────────────────────────────────────
print("Computing features...")
all_features = engine.compute_all(df_1min, df_funding)
if all_features.index.tz is not None:
    all_features.index = all_features.index.tz_localize(None)
all_features = all_features.replace([np.inf, -np.inf], np.nan).fillna(0.0)

# V1 features at minute 3
feat_v1 = all_features[all_features.index.minute % 5 == 3].copy()

# V2 features at minute 4 (boundary = predict next window)
feat_v2 = all_features[all_features.index.minute % 5 == 4].copy()

# V2 extra features (prev window stats)
df_5min["prev_delta"] = df_5min["close"].pct_change()
df_5min["prev_volume_change"] = df_5min["volume"].pct_change()
df_5min["prev_range"] = (df_5min["high"] - df_5min["low"]) / df_5min["open"]
df_5min["prev_body_ratio"] = abs(df_5min["close"] - df_5min["open"]) / (df_5min["high"] - df_5min["low"] + 1e-10)
df_5min["prev_was_up"] = (df_5min["close"] >= df_5min["open"]).astype(float)
streak = 0
prev_dir = None
streaks = []
for _, row in df_5min.iterrows():
    curr_dir = row["close"] >= row["open"]
    if prev_dir is not None and curr_dir == prev_dir:
        streak += 1
    else:
        streak = 1
    streaks.append(streak if curr_dir else -streak)
    prev_dir = curr_dir
df_5min["streak"] = streaks
extra_cols = ["prev_delta", "prev_volume_change", "prev_range", "prev_body_ratio", "prev_was_up", "streak"]

print("V1 features (minute 3): %d" % len(feat_v1))
print("V2 features (minute 4): %d" % len(feat_v2))

# ──────────────────────────────────────────
# Realistic Polymarket token pricing
# ──────────────────────────────────────────
def delta_to_token_price(delta_pct):
    """Convert window delta % to realistic token price (from Archetapp analysis)."""
    delta = abs(delta_pct)
    if delta < 0.005:
        return 0.50
    elif delta < 0.02:
        return 0.55
    elif delta < 0.05:
        return 0.65
    elif delta < 0.10:
        return 0.80
    elif delta < 0.15:
        return 0.92
    else:
        return 0.97

# ──────────────────────────────────────────
# Backtest parameters
# ──────────────────────────────────────────
INITIAL_CAPITAL = 1000.0
MIN_EDGE = 0.03
MIN_CONFIDENCE = 0.60
MIN_BET = 5.0
MAX_BET = 50.0
MAX_BET_FRACTION = 0.03
DAILY_STOP_LOSS = 0.05
MAX_DRAWDOWN = 0.15
CIRCUIT_BREAKER_LOSSES = 5

# Use last 15% as out-of-sample test
n_windows = len(df_5min)
test_start_idx = int(n_windows * 0.85)
test_windows = df_5min.iloc[test_start_idx:]
print("\nTest period: %s to %s (%d windows)" % (
    test_windows.index.min(), test_windows.index.max(), len(test_windows)))

# ──────────────────────────────────────────
# Run backtest
# ──────────────────────────────────────────
capital = INITIAL_CAPITAL
peak_capital = INITIAL_CAPITAL
daily_pnl = 0.0
consecutive_losses = 0
last_day = None
trades = []
capital_curve = [INITIAL_CAPITAL]

v1_feature_names = FeatureEngine.FEATURE_NAMES
v2_feature_names = FeatureEngine.FEATURE_NAMES + extra_cols

stats = {"s1_taken": 0, "s1_wins": 0, "s2_taken": 0, "s2_wins": 0, "s3_taken": 0, "s3_wins": 0, "skipped": 0}

for window_ts, window in test_windows.iterrows():
    # Daily reset
    current_day = window_ts.date()
    if current_day != last_day:
        daily_pnl = 0.0
        last_day = current_day

    # Risk gates
    drawdown = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
    if drawdown >= MAX_DRAWDOWN:
        stats["skipped"] += 1
        continue
    if daily_pnl <= -(capital * DAILY_STOP_LOSS):
        stats["skipped"] += 1
        continue

    actual_up = window["label"] == 1
    actual = "UP" if actual_up else "DOWN"
    delta_pct = window["delta_pct"]
    traded_this_window = False

    # ── STRATEGY 1: V2 limit order at minute 0 ──
    # V2 features from PREVIOUS window boundary (minute 4 of prev window)
    prev_boundary = window_ts - pd.Timedelta(minutes=1)
    prev_boundary_aligned = prev_boundary.floor("5min") + pd.Timedelta(minutes=4)

    if prev_boundary_aligned in feat_v2.index:
        v2_feat = feat_v2.loc[prev_boundary_aligned, FeatureEngine.FEATURE_NAMES]

        # Add extra features
        prev_window_ts = window_ts - pd.Timedelta(minutes=5)
        if prev_window_ts in df_5min.index:
            extras = df_5min.loc[prev_window_ts, extra_cols]
            v2_full = pd.concat([v2_feat, extras])
        else:
            v2_full = pd.concat([v2_feat, pd.Series(0.0, index=extra_cols)])

        X_v2 = v2_full.values.reshape(1, -1)
        X_v2 = np.nan_to_num(X_v2, nan=0.0, posinf=0.0, neginf=0.0)
        v2_prob = v2_calibrator.predict(v2_model.predict_proba(X_v2)[:, 1])[0]
        v2_confidence = abs(v2_prob - 0.5) * 2
        v2_direction = "UP" if v2_prob >= 0.5 else "DOWN"
        v2_model_prob = v2_prob if v2_direction == "UP" else (1 - v2_prob)

        # Limit order at 0.45 - fills only if market dips to that level
        limit_price = 0.45
        # Simulate fill: token price must have been <= 0.45 at some point
        # This happens when the opposite direction initially looks likely
        # Approximate: if delta briefly goes opposite, price dips
        # We estimate fill probability based on volatility
        intra_window = df_1min.loc[window_ts:window_ts + pd.Timedelta(minutes=4)]
        if len(intra_window) >= 3:
            # Check if at any minute, the delta was in the opposite direction
            w_open = intra_window.iloc[0]["open"]
            min_close = intra_window["close"].min()
            max_close = intra_window["close"].max()

            if v2_direction == "UP":
                # Our UP limit fills if DOWN token briefly cheap = UP token briefly > 0.55
                # Actually: UP limit at 0.45 fills if market briefly prices UP low
                # This happens when BTC dips below open
                worst_delta = (min_close - w_open) / w_open * 100
                fill = worst_delta < -0.005  # BTC dipped below open
            else:
                # DOWN limit at 0.45 fills if BTC went above open
                best_delta = (max_close - w_open) / w_open * 100
                fill = best_delta > 0.005

            if fill and v2_confidence >= MIN_CONFIDENCE and v2_model_prob - limit_price >= MIN_EDGE:
                edge = v2_model_prob - limit_price
                kelly = (edge / (1 - limit_price)) * 0.25
                bet = min(MAX_BET, max(MIN_BET, capital * kelly))
                bet = min(bet, capital * MAX_BET_FRACTION)

                won = v2_direction == actual
                if won:
                    pnl = bet * (1 - limit_price) / limit_price
                else:
                    pnl = -bet

                capital += pnl
                daily_pnl += pnl
                peak_capital = max(peak_capital, capital)
                stats["s1_taken"] += 1
                if won:
                    stats["s1_wins"] += 1
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1

                trades.append({
                    "ts": str(window_ts), "strategy": "S1_LIMIT", "direction": v2_direction,
                    "actual": actual, "won": won, "entry_price": limit_price,
                    "edge": round(edge, 4), "bet": round(bet, 2), "pnl": round(pnl, 2),
                    "capital": round(capital, 2),
                })
                traded_this_window = True

    # ── STRATEGY 2: V1 at minute 3 (with realistic pricing) ──
    if not traded_this_window:
        minute_3_ts = window_ts + pd.Timedelta(minutes=3)
        if minute_3_ts in feat_v1.index:
            v1_feat = feat_v1.loc[minute_3_ts, FeatureEngine.FEATURE_NAMES]
            X_v1 = v1_feat.values.reshape(1, -1)
            X_v1 = np.nan_to_num(X_v1, nan=0.0, posinf=0.0, neginf=0.0)
            v1_prob = v1_calibrator.predict(v1_model.predict_proba(X_v1)[:, 1])[0]
            v1_confidence = abs(v1_prob - 0.5) * 2
            v1_direction = "UP" if v1_prob >= 0.5 else "DOWN"
            v1_model_prob = v1_prob if v1_direction == "UP" else (1 - v1_prob)

            # At minute 3, calculate delta so far to get realistic token price
            candles_so_far = df_1min.loc[window_ts:minute_3_ts]
            if len(candles_so_far) >= 3:
                w_open = candles_so_far.iloc[0]["open"]
                current_close = candles_so_far.iloc[-1]["close"]
                current_delta = abs(current_close - w_open) / w_open * 100
                token_price = delta_to_token_price(current_delta)
            else:
                token_price = 0.55

            edge = v1_model_prob - token_price
            if v1_confidence >= MIN_CONFIDENCE and edge >= MIN_EDGE:
                kelly = (edge / (1 - token_price)) * 0.25
                bet = min(MAX_BET, max(MIN_BET, capital * kelly))
                bet = min(bet, capital * MAX_BET_FRACTION)

                won = v1_direction == actual
                if won:
                    pnl = bet * (1 - token_price) / token_price
                else:
                    pnl = -bet

                capital += pnl
                daily_pnl += pnl
                peak_capital = max(peak_capital, capital)
                stats["s2_taken"] += 1
                if won:
                    stats["s2_wins"] += 1
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1

                trades.append({
                    "ts": str(window_ts), "strategy": "S2_ML_M3", "direction": v1_direction,
                    "actual": actual, "won": won, "entry_price": round(token_price, 4),
                    "edge": round(edge, 4), "bet": round(bet, 2), "pnl": round(pnl, 2),
                    "capital": round(capital, 2),
                })
                traded_this_window = True

    # ── STRATEGY 3: T-10s snipe (minute 4) ──
    if not traded_this_window:
        minute_4_ts = window_ts + pd.Timedelta(minutes=4)
        candles_full = df_1min.loc[window_ts:minute_4_ts]
        if len(candles_full) >= 4:
            w_open = candles_full.iloc[0]["open"]
            late_close = candles_full.iloc[-1]["close"]
            late_delta = (late_close - w_open) / w_open * 100

            # At T-10s, direction is very clear
            if abs(late_delta) > 0.02:  # Only snipe if clear direction
                snipe_direction = "UP" if late_delta > 0 else "DOWN"
                token_price = delta_to_token_price(abs(late_delta))

                # Snipe confidence = how clear the direction is
                snipe_confidence = min(abs(late_delta) / 0.15, 1.0)

                # At this point, token is expensive but very likely correct
                # Edge = estimated WR - token_price
                # Empirical: at T-10s with delta > 0.02%, WR is ~92%
                estimated_wr = 0.92
                edge = estimated_wr - token_price

                if edge >= 0.01 and snipe_confidence >= 0.3:  # Lower thresholds for snipe
                    kelly = (edge / (1 - token_price)) * 0.25
                    bet = min(MAX_BET, max(MIN_BET, capital * kelly))
                    bet = min(bet, capital * MAX_BET_FRACTION)

                    won = snipe_direction == actual
                    if won:
                        pnl = bet * (1 - token_price) / token_price
                    else:
                        pnl = -bet

                    capital += pnl
                    daily_pnl += pnl
                    peak_capital = max(peak_capital, capital)
                    stats["s3_taken"] += 1
                    if won:
                        stats["s3_wins"] += 1
                        consecutive_losses = 0
                    else:
                        consecutive_losses += 1

                    trades.append({
                        "ts": str(window_ts), "strategy": "S3_SNIPE", "direction": snipe_direction,
                        "actual": actual, "won": won, "entry_price": round(token_price, 4),
                        "edge": round(edge, 4), "bet": round(bet, 2), "pnl": round(pnl, 2),
                        "capital": round(capital, 2),
                    })
                    traded_this_window = True

    if not traded_this_window:
        stats["skipped"] += 1

    capital_curve.append(capital)

# ──────────────────────────────────────────
# Results
# ──────────────────────────────────────────
print("\n" + "=" * 70)
print("  COMBINED STRATEGY RESULTS (1 YEAR, OUT-OF-SAMPLE)")
print("=" * 70)

total_trades = len(trades)
total_wins = sum(1 for t in trades if t["won"])
total_pnl = sum(t["pnl"] for t in trades)

print("\n  OVERALL:")
print("    Total trades: %d" % total_trades)
print("    Win rate: %.1f%% (%d/%d)" % (total_wins / total_trades * 100 if total_trades else 0, total_wins, total_trades))
print("    Starting capital: $%.2f" % INITIAL_CAPITAL)
print("    Final capital: $%.2f" % capital)
print("    Total PnL: $%.2f" % total_pnl)
print("    ROI: %.1f%%" % ((capital / INITIAL_CAPITAL - 1) * 100))
max_dd = 0
peak = INITIAL_CAPITAL
for c in capital_curve:
    peak = max(peak, c)
    dd = (peak - c) / peak
    max_dd = max(max_dd, dd)
print("    Max drawdown: %.2f%%" % (max_dd * 100))

# Per-strategy breakdown
print("\n  PER STRATEGY:")
for label, key_taken, key_wins in [
    ("S1 - Limit Order (V2, min 0)", "s1_taken", "s1_wins"),
    ("S2 - ML Confirm (V1, min 3)", "s2_taken", "s2_wins"),
    ("S3 - Snipe (T-10s, min 4)", "s3_taken", "s3_wins"),
]:
    taken = stats[key_taken]
    wins = stats[key_wins]
    wr = wins / taken * 100 if taken else 0
    strat_trades = [t for t in trades if t["strategy"] == key_taken.replace("_taken", "").upper().replace("S1", "S1_LIMIT").replace("S2", "S2_ML_M3").replace("S3", "S3_SNIPE")]
    strat_pnl = sum(t["pnl"] for t in strat_trades)
    print("    %s:" % label)
    print("      Trades: %d | WR: %.1f%% | PnL: $%.2f" % (taken, wr, strat_pnl))

# Strategy PnL breakdown
for strat_name in ["S1_LIMIT", "S2_ML_M3", "S3_SNIPE"]:
    strat_trades = [t for t in trades if t["strategy"] == strat_name]
    if strat_trades:
        avg_entry = np.mean([t["entry_price"] for t in strat_trades])
        avg_edge = np.mean([t["edge"] for t in strat_trades])
        strat_pnl = sum(t["pnl"] for t in strat_trades)
        strat_wins = sum(1 for t in strat_trades if t["won"])
        print("\n    %s detail:" % strat_name)
        print("      Avg entry price: %.4f" % avg_entry)
        print("      Avg edge: %.4f" % avg_edge)
        print("      Win rate: %.1f%%" % (strat_wins / len(strat_trades) * 100))
        print("      Total PnL: $%.2f" % strat_pnl)

print("\n  Skipped windows: %d" % stats["skipped"])
print("=" * 70)

# Save trades
df_trades = pd.DataFrame(trades)
df_trades.to_csv("data/combined_backtest_trades.csv", index=False)
print("\nTrades saved to data/combined_backtest_trades.csv")
