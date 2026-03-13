"""Train XGBoost model on prepared dataset with full validation report."""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from bot.config import Config
from bot.model import BotModel

cfg = Config()
cfg.ensure_dirs()

print("=== Loading training data ===")
X = pd.read_parquet(f"{cfg.DATA_DIR}/training_features.parquet")
y = pd.read_parquet(f"{cfg.DATA_DIR}/training_labels.parquet")["label"]
print(f"Samples: {len(X)}, Features: {X.shape[1]}")
print(f"Label distribution: UP={y.mean():.4f}")

print("\n=== Training with Optuna (50 trials) ===")
model = BotModel()
metrics = model.train(X, y, n_optuna_trials=50)

print("\n=== Validation Report ===")
print(f"AUC-ROC:                    {metrics['auc_roc']:.4f}")
print(f"Brier Score:                {metrics['brier_score']:.4f}")
print(f"Accuracy (top 20% conf):    {metrics['accuracy_top20']:.4f}")
print(f"Best params:                {metrics['best_params']}")

checks = {
    "AUC-ROC > 0.52": metrics["auc_roc"] > 0.52,
    "Brier < 0.24": metrics["brier_score"] < 0.24,
    "Acc top20 > 57%": metrics["accuracy_top20"] > 0.57,
}
print("\n=== Production Readiness ===")
all_pass = True
for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {check}")
    if not passed:
        all_pass = False

if all_pass:
    model.save(cfg.MODELS_DIR)
    print(f"\nModel saved to {cfg.MODELS_DIR}/")
else:
    # Save anyway for backtest analysis even if not prod-ready
    model.save(cfg.MODELS_DIR)
    print("\nModel did NOT pass all checks but saved for analysis.")

# Feature importance
importances = model.model.feature_importances_
feat_names = X.columns
sorted_idx = np.argsort(importances)[::-1]
print("\n=== Feature Importance ===")
for i in sorted_idx:
    print(f"  {feat_names[i]:25s} {importances[i]:.4f}")
