#!/usr/bin/env python3
"""
Train model V2 - predict at window start (minute 0).

This model is harder (no current window data) but enables limit order strategy
with much better prices (~0.40-0.50 instead of 0.90+).
"""

import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import joblib
import warnings
import optuna
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import TimeSeriesSplit

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

print("=" * 60)
print("  TRAINING MODEL V2 (predict at minute 0)")
print("=" * 60)

# Load V2 data
X = pd.read_parquet("data/training_features_v2.parquet")
y = pd.read_parquet("data/training_labels_v2.parquet")["label"]

print("Dataset: %d samples x %d features" % X.shape)
print("Label distribution: UP=%.4f DOWN=%.4f" % (y.mean(), 1 - y.mean()))

# Clean inf/nan values
import numpy as np
X = X.replace([np.inf, -np.inf], np.nan)
X = X.fillna(0.0)
print("Cleaned inf/nan values")

# Temporal split: 70/15/15
n = len(X)
train_end = int(n * 0.70)
cal_end = int(n * 0.85)

X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
X_cal, y_cal = X.iloc[train_end:cal_end], y.iloc[train_end:cal_end]
X_test, y_test = X.iloc[cal_end:], y.iloc[cal_end:]

print("\nSplits:")
print("  Train: %d (%s to %s)" % (len(X_train), X_train.index.min(), X_train.index.max()))
print("  Cal:   %d (%s to %s)" % (len(X_cal), X_cal.index.min(), X_cal.index.max()))
print("  Test:  %d (%s to %s)" % (len(X_test), X_test.index.min(), X_test.index.max()))

# Optuna hyperparameter optimization
print("\nRunning Optuna (50 trials)...")

def objective(trial):
    params = {
        "max_depth": trial.suggest_int("max_depth", 2, 8),
        "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
        "learning_rate": trial.suggest_float("learning_rate", 0.003, 0.1, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 0.95),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 0.95),
        "min_child_weight": trial.suggest_int("min_child_weight", 5, 150),
        "gamma": trial.suggest_float("gamma", 0, 10),
        "reg_alpha": trial.suggest_float("reg_alpha", 0, 15),
        "reg_lambda": trial.suggest_float("reg_lambda", 1, 15),
    }

    tscv = TimeSeriesSplit(n_splits=3)
    scores = []
    for train_idx, val_idx in tscv.split(X_train):
        clf = xgb.XGBClassifier(**params, eval_metric="logloss", random_state=42, verbosity=0)
        clf.fit(X_train.iloc[train_idx], y_train.iloc[train_idx])
        proba = clf.predict_proba(X_train.iloc[val_idx])[:, 1]
        auc = roc_auc_score(y_train.iloc[val_idx], proba)
        scores.append(auc)
    return np.mean(scores)

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=50, show_progress_bar=False)
best_params = study.best_params

print("Best AUC (CV): %.4f" % study.best_value)
print("Best params:", best_params)

# Train final model
print("\nTraining final model...")
model = xgb.XGBClassifier(**best_params, eval_metric="logloss", random_state=42, verbosity=0)
model.fit(X_train, y_train)

# Calibrate
cal_proba = model.predict_proba(X_cal)[:, 1]
calibrator = IsotonicRegression(out_of_bounds="clip")
calibrator.fit(cal_proba, y_cal)

# Evaluate on test
test_proba_raw = model.predict_proba(X_test)[:, 1]
test_proba_cal = calibrator.predict(test_proba_raw)

auc = roc_auc_score(y_test, test_proba_cal)
brier = brier_score_loss(y_test, test_proba_cal)

# Accuracy at different confidence levels
confidence = np.abs(test_proba_cal - 0.5) * 2

for threshold_name, threshold in [("all", 0.0), ("top50%", 0.5), ("top30%", 0.7), ("top20%", 0.8)]:
    if threshold == 0.0:
        mask = np.ones(len(confidence), dtype=bool)
    else:
        mask = confidence >= np.percentile(confidence, threshold * 100)
    if mask.sum() > 0:
        preds = (test_proba_cal[mask] >= 0.5).astype(int)
        acc = (preds == y_test.values[mask]).mean()
        print("  Accuracy (%s, n=%d): %.4f" % (threshold_name, mask.sum(), acc))

# Top 20% for main metric
top20_mask = confidence >= np.percentile(confidence, 80)
if top20_mask.sum() > 0:
    preds_top20 = (test_proba_cal[top20_mask] >= 0.5).astype(int)
    acc_top20 = (preds_top20 == y_test.values[top20_mask]).mean()
else:
    acc_top20 = 0.0

print("\n" + "=" * 60)
print("  MODEL V2 RESULTS")
print("=" * 60)
print("  AUC-ROC:          %.4f" % auc)
print("  Brier Score:      %.4f" % brier)
print("  Acc (top 20%%):    %.4f" % acc_top20)

# Feature importance
imp = model.feature_importances_
idx = np.argsort(imp)[::-1]
print("\n  Feature Importance:")
for i, j in enumerate(idx[:10]):
    bar = "#" * int(imp[j] * 50)
    print("  %2d. %-25s %.4f %s" % (i + 1, X.columns[j], imp[j], bar))

# Save V2 model
import os
os.makedirs("models_v2", exist_ok=True)
joblib.dump(model, "models_v2/xgb_model.joblib")
joblib.dump(calibrator, "models_v2/calibrator.joblib")
joblib.dump({"auc_roc": auc, "brier_score": brier, "accuracy_top20": acc_top20}, "models_v2/metrics.joblib")
joblib.dump(best_params, "models_v2/best_params.joblib")

print("\nModel saved to models_v2/")

# Realistic edge analysis
print("\n" + "=" * 60)
print("  EDGE ANALYSIS (if buying at market price ~0.50)")
print("=" * 60)
# Simulate: we buy at 0.50, model gives probability
# Edge = model_prob - 0.50 (for the side we pick)
model_sides = np.where(test_proba_cal >= 0.5, test_proba_cal, 1 - test_proba_cal)
edges = model_sides - 0.50
actuals = y_test.values
predicted_up = test_proba_cal >= 0.5
correct = predicted_up == actuals

# Only take trades where edge > 0.03
for min_edge in [0.0, 0.03, 0.05, 0.10, 0.15]:
    trade_mask = edges >= min_edge
    if trade_mask.sum() > 0:
        wr = correct[trade_mask].mean()
        avg_edge = edges[trade_mask].mean()
        print("  Edge >= %.2f: %d trades, WR=%.1f%%, avg_edge=%.3f" % (
            min_edge, trade_mask.sum(), wr * 100, avg_edge))

print("\nDONE!")
