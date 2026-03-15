#!/usr/bin/env python3
"""
Pro backtest - V2 model at minute 1 with realistic pricing.

$2 min bet, percentage returns, realistic token pricing at minute 1.
"""

import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import joblib

print("=" * 70)
print("  PRO BACKTEST - V2 @ MINUTE 1 - REALISTIC PRICING")
print("=" * 70)

# Load data
df = pd.read_parquet("data/BTCUSDT-1m-combined.parquet")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

df_5min = df.resample("5min").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
}).dropna()
df_5min["label"] = (df_5min["close"] >= df_5min["open"]).astype(int)

# Load V2 Pro model
model = joblib.load("models_v2/xgb_model.joblib")
calibrator = joblib.load("models_v2/calibrator.joblib")

# Load features
X = pd.read_parquet("data/training_features_v2.parquet")
y = pd.read_parquet("data/training_labels_v2.parquet")["label"]
X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

# Test set = last 15%
n = len(X)
test_start = int(n * 0.85)
X_test = X.iloc[test_start:]
y_test = y.iloc[test_start:]

print("Test period: %s to %s" % (X_test.index.min(), X_test.index.max()))
print("Windows: %d\n" % len(X_test))

# Get predictions
raw_probs = model.predict_proba(X_test)[:, 1]
cal_probs = calibrator.predict(raw_probs)

# ──────────────────────────────────────────
# Token price at minute 1 (realistic)
# At minute 1, the market has seen 1 candle.
# Token price = 0.50 + premium based on first minute delta
# Much cheaper than minute 3 (0.80-0.95)
# ──────────────────────────────────────────
def token_price_at_minute_1(first_min_delta_pct):
    """Realistic token price at minute 1 based on first candle move."""
    d = abs(first_min_delta_pct)
    if d < 0.005:
        return 0.50   # No move yet, coin flip
    elif d < 0.01:
        return 0.52   # Tiny move
    elif d < 0.02:
        return 0.55   # Small move
    elif d < 0.04:
        return 0.58   # Moderate move
    elif d < 0.06:
        return 0.62   # Clear move
    elif d < 0.10:
        return 0.68   # Strong move
    else:
        return 0.75   # Very strong move (rare at minute 1)

# Get first-minute deltas for each test window
first_min_deltas = []
for window_ts in X_test.index:
    if window_ts in df.index:
        w_open = df.loc[window_ts, "open"]
        min1_ts = window_ts + pd.Timedelta(minutes=1)
        if min1_ts in df.index:
            min1_close = df.loc[min1_ts, "close"]
            delta = (min1_close - w_open) / w_open * 100
        else:
            delta = 0.0
    else:
        delta = 0.0
    first_min_deltas.append(delta)

first_min_deltas = np.array(first_min_deltas)

# ──────────────────────────────────────────
# Backtest
# ──────────────────────────────────────────
INITIAL_CAPITAL = 100.0
MIN_BET = 2.0  # Polymarket minimum
MIN_EDGE = 0.05
MIN_CONFIDENCE = 0.30  # Lower threshold - model is well calibrated
DAILY_STOP_LOSS = 0.05
MAX_DRAWDOWN = 0.15

capital = INITIAL_CAPITAL
peak_capital = INITIAL_CAPITAL
daily_pnl = 0.0
last_day = None
consecutive_losses = 0
trades = []
capital_curve = [INITIAL_CAPITAL]

for i in range(len(X_test)):
    prob = cal_probs[i]
    actual = y_test.iloc[i]
    window_ts = X_test.index[i]
    delta = first_min_deltas[i]

    # Daily reset
    current_day = window_ts.date() if hasattr(window_ts, 'date') else None
    if current_day != last_day:
        daily_pnl = 0.0
        last_day = current_day

    # Risk gates
    drawdown = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
    if drawdown >= MAX_DRAWDOWN or daily_pnl <= -(capital * DAILY_STOP_LOSS):
        capital_curve.append(capital)
        continue
    if consecutive_losses >= 5:
        consecutive_losses = 0  # Reset after skip
        capital_curve.append(capital)
        continue

    # Direction & confidence
    direction = "UP" if prob >= 0.5 else "DOWN"
    model_prob = prob if direction == "UP" else (1 - prob)
    confidence = abs(prob - 0.5) * 2

    # Token price at minute 1
    entry_price = token_price_at_minute_1(delta)

    # Edge = what model thinks - what market charges
    edge = model_prob - entry_price

    if edge < MIN_EDGE or confidence < MIN_CONFIDENCE:
        capital_curve.append(capital)
        continue

    # Bet size = 2% of capital (scales with gains)
    bet = capital * 0.02
    bet = max(MIN_BET, bet)  # Minimum $2
    bet = min(bet, 50.0)     # Cap at $50 to stay safe
    if capital < MIN_BET:
        break

    # Resolution
    won = (direction == "UP" and actual == 1) or (direction == "DOWN" and actual == 0)

    if won:
        # Buy at entry_price, token pays $1
        # Shares bought = bet / entry_price
        # Payout = shares * $1 = bet / entry_price
        # Profit = payout - bet = bet * (1/entry_price - 1) = bet * (1 - entry_price) / entry_price
        pnl = bet * (1 - entry_price) / entry_price
        consecutive_losses = 0
    else:
        pnl = -bet
        consecutive_losses += 1

    capital += pnl
    daily_pnl += pnl
    peak_capital = max(peak_capital, capital)

    trades.append({
        "ts": str(window_ts),
        "direction": direction,
        "actual": "UP" if actual == 1 else "DOWN",
        "won": won,
        "prob": round(float(model_prob), 4),
        "entry_price": round(entry_price, 4),
        "edge": round(float(edge), 4),
        "bet": bet,
        "pnl": round(pnl, 4),
        "capital": round(capital, 2),
        "return_pct": round(pnl / bet * 100, 1),
    })
    capital_curve.append(capital)

# ──────────────────────────────────────────
# Results
# ──────────────────────────────────────────
total = len(trades)
wins = sum(1 for t in trades if t["won"])
losses = total - wins
total_pnl = sum(t["pnl"] for t in trades)

max_dd = 0
peak = INITIAL_CAPITAL
for c in capital_curve:
    peak = max(peak, c)
    dd = (peak - c) / peak
    max_dd = max(max_dd, dd)

# Monthly breakdown
df_trades = pd.DataFrame(trades)
if not df_trades.empty:
    df_trades["month"] = pd.to_datetime(df_trades["ts"]).dt.to_period("M")

print("=" * 70)
print("  RESULTS ($2 FLAT BET, REALISTIC PRICING @ MINUTE 1)")
print("=" * 70)
print()
print("  Period: %s to %s" % (X_test.index.min(), X_test.index.max()))
print("  Total trades: %d" % total)
print("  Wins: %d | Losses: %d" % (wins, losses))
print("  Win rate: %.1f%%" % (wins / total * 100 if total else 0))
print()
print("  Starting capital: $%.2f" % INITIAL_CAPITAL)
print("  Final capital: $%.2f" % capital)
print("  Total PnL: $%.2f" % total_pnl)
print("  ROI: %.1f%%" % ((capital / INITIAL_CAPITAL - 1) * 100))
print("  Max drawdown: %.2f%%" % (max_dd * 100))
print()

if not df_trades.empty:
    print("  Avg entry price: %.4f" % df_trades["entry_price"].mean())
    print("  Avg edge: %.4f" % df_trades["edge"].mean())
    print("  Avg return per trade: %.1f%%" % df_trades["return_pct"].mean())
    print("  Avg PnL per trade: $%.4f" % (total_pnl / total))
    print()

    # Per-entry-price breakdown
    print("  BREAKDOWN BY ENTRY PRICE:")
    for price in sorted(df_trades["entry_price"].unique()):
        mask = df_trades["entry_price"] == price
        p_trades = df_trades[mask]
        p_wins = p_trades["won"].sum()
        p_total = len(p_trades)
        p_pnl = p_trades["pnl"].sum()
        print("    Entry $%.2f: %4d trades, WR=%.1f%%, PnL=$%.2f" % (
            price, p_total, p_wins / p_total * 100, p_pnl))

    # Monthly performance
    print()
    print("  MONTHLY PERFORMANCE:")
    for month, group in df_trades.groupby("month"):
        m_wins = group["won"].sum()
        m_total = len(group)
        m_pnl = group["pnl"].sum()
        print("    %s: %4d trades, WR=%.1f%%, PnL=$%.2f" % (
            month, m_total, m_wins / m_total * 100, m_pnl))

print()
print("=" * 70)

# Daily stats
if not df_trades.empty:
    df_trades["date"] = pd.to_datetime(df_trades["ts"]).dt.date
    daily = df_trades.groupby("date").agg(
        trades=("won", "count"),
        wins=("won", "sum"),
        pnl=("pnl", "sum"),
    )
    profitable_days = (daily["pnl"] > 0).sum()
    total_days = len(daily)
    print("  Profitable days: %d/%d (%.1f%%)" % (
        profitable_days, total_days, profitable_days / total_days * 100))
    print("  Avg trades/day: %.1f" % daily["trades"].mean())
    print("  Avg PnL/day: $%.2f" % daily["pnl"].mean())
    print("  Best day: $%.2f" % daily["pnl"].max())
    print("  Worst day: $%.2f" % daily["pnl"].min())
    print("=" * 70)

# Save
df_trades.to_csv("data/pro_backtest_trades.csv", index=False)
print("\nTrades saved to data/pro_backtest_trades.csv")
