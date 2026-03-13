"""Run backtest on trained model with full metrics report."""
import sys
sys.path.insert(0, ".")

import pandas as pd
import numpy as np
from bot.config import Config
from bot.model import BotModel
from bot.backtest import BacktestEngine

cfg = Config()

print("=== Loading model ===")
model = BotModel()
model.load(cfg.MODELS_DIR)
print(f"Model metrics from training: AUC={model.metrics.get('auc_roc', 'N/A')}")

print("\n=== Loading test data ===")
X = pd.read_parquet(f"{cfg.DATA_DIR}/training_features.parquet")
y = pd.read_parquet(f"{cfg.DATA_DIR}/training_labels.parquet")["label"]

# Use last 15% as out-of-sample (same as model test set)
n = len(X)
test_start = int(n * 0.85)
X_test = X.iloc[test_start:]
y_test = y.iloc[test_start:]
print(f"Test samples: {len(X_test)}")

# Get calibrated probabilities
probas = model.predict_calibrated(X_test)

backtest_data = pd.DataFrame({
    "prob_calibrated": probas,
    "label": y_test.values,
}, index=X_test.index)

print("\n=== Running Backtest (capital=$100) ===")
engine = BacktestEngine(initial_capital=100.0)
results = engine.run(backtest_data)

print(f"\n{'='*50}")
print(f"BACKTEST RESULTS")
print(f"{'='*50}")
print(f"Total trades:        {results['total_trades']}")
print(f"Win rate:            {results['win_rate']:.2%}")
print(f"Final capital:       ${results['final_capital']:.2f}")
print(f"ROI:                 {results['roi']:.2%}")
print(f"Max drawdown:        {results['max_drawdown']:.2%}")
print(f"Profit factor:       {results['profit_factor']:.2f}")
print(f"Sharpe ratio:        {results['sharpe_ratio']:.2f}")

if results['total_trades'] > 0:
    avg_bet = np.mean([t['bet_size'] for t in results['trades']])
    avg_pnl = np.mean([t['pnl'] for t in results['trades']])
    print(f"Avg bet size:        ${avg_bet:.2f}")
    print(f"Avg P&L per trade:   ${avg_pnl:.4f}")

print(f"\n=== Production Readiness ===")
checks = {
    "Win rate > 57%": results["win_rate"] > 0.57 if results["total_trades"] > 0 else False,
    "Profit factor > 1.15": results["profit_factor"] > 1.15 if results["total_trades"] > 0 else False,
    "Max drawdown < 10%": results["max_drawdown"] < 0.10,
    "Sharpe > 1.0": results["sharpe_ratio"] > 1.0 if results["total_trades"] > 0 else False,
    "Trades > 20": results["total_trades"] > 20,
}
all_pass = True
for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {check}")
    if not passed:
        all_pass = False

if all_pass:
    print("\n*** BOT IS PRODUCTION READY ***")
else:
    print("\nBot needs more work before production.")
