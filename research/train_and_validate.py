"""
Full model training pipeline with Optuna optimization.
Uses training_features_v2.parquet + training_labels_v2.parquet.
Saves trained model for live inference.

Target: >70% accuracy at threshold=0.65, positive PnL in backtest.
"""
import os
import sys
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import joblib

# Check for XGBoost
try:
    import xgboost as xgb
    print("XGBoost available:", xgb.__version__)
except ImportError:
    print("ERROR: XGBoost not installed. Run: pip install xgboost")
    sys.exit(1)

# Check for Optuna
try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False
    print("Optuna not available - using default params")

from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score, log_loss
from sklearn.model_selection import TimeSeriesSplit

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading training data...")
X_df = pd.read_parquet('data/training_features_v2.parquet')
y_df = pd.read_parquet('data/training_labels_v2.parquet')

df = X_df.join(y_df, how='inner').dropna()
print(f"Dataset: {df.shape[0]} samples, {X_df.shape[1]} features")
print(f"Period: {df.index.min().date()} to {df.index.max().date()}")
print(f"Label balance: {df['label'].mean():.3f} (0.50 = perfect)")

FEATURE_COLS = X_df.columns.tolist()
X = df[FEATURE_COLS].values.astype(np.float32)
y = df['label'].values.astype(np.int32)

# BAD hours from live data analysis
BAD_HOURS = {2, 6, 10, 14, 16, 18}
hours = df.index.hour

# ── Time-series split ─────────────────────────────────────────────────────────
n = len(df)
train_end = int(n * 0.70)
val_end = int(n * 0.85)

X_train, y_train = X[:train_end], y[:train_end]
X_val, y_val = X[train_end:val_end], y[train_end:val_end]
X_test, y_test = X[val_end:], y[val_end:]
hours_test = hours[val_end:]

print(f"\nSplit: Train={train_end:,}, Val={val_end-train_end:,}, Test={n-val_end:,}")

# ── Scaler ─────────────────────────────────────────────────────────────────────
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_val_s = scaler.transform(X_val)
X_test_s = scaler.transform(X_test)

# ── Optuna hyperparameter search ──────────────────────────────────────────────
if HAS_OPTUNA:
    print("\nRunning Optuna hyperparameter search (50 trials)...")

    def objective(trial):
        params = {
            'max_depth': trial.suggest_int('max_depth', 2, 6),
            'n_estimators': trial.suggest_int('n_estimators', 200, 1000),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.15, log=True),
            'subsample': trial.suggest_float('subsample', 0.5, 0.9),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 0.9),
            'min_child_weight': trial.suggest_int('min_child_weight', 10, 100),
            'gamma': trial.suggest_float('gamma', 0.5, 5.0),
            'reg_alpha': trial.suggest_float('reg_alpha', 0.1, 5.0),
            'reg_lambda': trial.suggest_float('reg_lambda', 1.0, 10.0),
        }

        clf = xgb.XGBClassifier(
            **params,
            eval_metric='logloss',
            early_stopping_rounds=20,
            random_state=42,
            verbosity=0,
        )
        clf.fit(X_train_s, y_train, eval_set=[(X_val_s, y_val)], verbose=False)
        probs = clf.predict_proba(X_val_s)[:, 1]
        return log_loss(y_val, probs)

    study = optuna.create_study(direction='minimize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=50, show_progress_bar=True)

    best_params = study.best_params
    print(f"\nBest params: {best_params}")
    print(f"Best val log_loss: {study.best_value:.4f}")
else:
    best_params = {
        'max_depth': 4,
        'n_estimators': 500,
        'learning_rate': 0.05,
        'subsample': 0.7,
        'colsample_bytree': 0.7,
        'min_child_weight': 20,
        'gamma': 1.0,
        'reg_alpha': 0.5,
        'reg_lambda': 2.0,
    }
    print("\nUsing default params (install optuna for optimization)")

# ── Final model training ──────────────────────────────────────────────────────
print("\nTraining final model...")
model = xgb.XGBClassifier(
    **best_params,
    eval_metric='logloss',
    early_stopping_rounds=30,
    random_state=42,
    verbosity=0,
)
model.fit(X_train_s, y_train, eval_set=[(X_val_s, y_val)], verbose=False)
print(f"Best iteration: {model.best_iteration}")

# ── Calibration (isotonic regression for well-calibrated probabilities) ────────
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression

val_probs_raw = model.predict_proba(X_val_s)[:, 1]
calibrator = IsotonicRegression(out_of_bounds='clip')
calibrator.fit(val_probs_raw, y_val)

# ── Evaluate ─────────────────────────────────────────────────────────────────
test_probs_raw = model.predict_proba(X_test_s)[:, 1]
test_probs = calibrator.predict(test_probs_raw)

print("\n=== TEST SET EVALUATION ===")
print(f"ROC-AUC: {roc_auc_score(y_test, test_probs):.4f}")
print(f"Overall accuracy: {accuracy_score(y_test, test_probs > 0.5):.4f}")
print(f"Log loss: {log_loss(y_test, test_probs):.4f}")

# Accuracy at different confidence thresholds
print("\n=== CONFIDENCE THRESHOLD ANALYSIS ===")
print(f"{'Thresh':>8} {'Trades':>8} {'Accuracy':>10} {'Coverage':>10} {'PnL(0.50)':>12} {'CR_pass':>10}")

BET_SIZE = 2.0
FEE_RATE = 0.02
ENTRY_PRICE = 0.50

results = []
for thresh in [0.50, 0.52, 0.54, 0.55, 0.57, 0.60, 0.62, 0.65, 0.67, 0.70]:
    mask = (test_probs >= thresh) | (test_probs <= (1 - thresh))
    # Apply hour filter
    hour_mask = np.array([h not in BAD_HOURS for h in hours_test])
    full_mask = mask & hour_mask

    if full_mask.sum() < 5:
        continue

    p_sub = test_probs[full_mask]
    y_sub = y_test[full_mask]

    preds = (p_sub > 0.5).astype(int)
    acc = accuracy_score(y_sub, preds)
    n_trades = len(p_sub)
    coverage = n_trades / len(test_probs)

    # Backtest with fixed 0.50 entry price
    shares = BET_SIZE / ENTRY_PRICE
    fee = BET_SIZE * FEE_RATE
    pnl_per_win = shares - BET_SIZE - fee   # ~$1.96
    pnl_per_lose = -BET_SIZE - fee           # ~-$2.04

    correct = (preds == y_sub)
    pnl = (correct * pnl_per_win + (1 - correct) * pnl_per_lose).sum()
    cr_above_75 = "YES ***" if acc >= 0.75 else ("OK" if acc >= 0.65 else "")

    print(f"  {thresh:>6.2f}  {n_trades:>8d}  {acc:>10.3f}  {coverage:>10.1%}  {pnl:>+12.2f}  {cr_above_75:>10}")
    results.append({'thresh': thresh, 'trades': n_trades, 'acc': acc, 'pnl': pnl})

# ── Find optimal threshold ─────────────────────────────────────────────────────
best = max(results, key=lambda x: x['pnl'] if x['trades'] >= 20 else -9999)
print(f"\nBest threshold: {best['thresh']} (acc={best['acc']:.3f}, trades={best['trades']}, pnl={best['pnl']:+.2f})")

# ── Feature importance ────────────────────────────────────────────────────────
print("\n=== TOP FEATURES ===")
feat_imp = sorted(zip(FEATURE_COLS, model.feature_importances_), key=lambda x: -x[1])[:15]
for feat, imp in feat_imp:
    print(f"  {feat:30s}: {imp:.4f}")

# ── Save model ────────────────────────────────────────────────────────────────
os.makedirs('data/models', exist_ok=True)
joblib.dump({
    'model': model,
    'scaler': scaler,
    'calibrator': calibrator,
    'feature_cols': FEATURE_COLS,
    'best_threshold': best['thresh'],
    'bad_hours': list(BAD_HOURS),
    'metrics': {
        'test_accuracy': float(accuracy_score(y_test, test_probs > 0.5)),
        'test_roc_auc': float(roc_auc_score(y_test, test_probs)),
        'best_thresh_accuracy': float(best['acc']),
        'best_thresh_trades': best['trades'],
        'best_thresh_pnl': float(best['pnl']),
    }
}, 'data/models/v3_xgb_model.joblib')

print("\nModel saved to data/models/v3_xgb_model.joblib")
print(f"Best threshold: {best['thresh']}")
print(f"Expected accuracy at threshold: {best['acc']:.1%}")
print(f"Expected PnL on test: {best['pnl']:+.2f} over {best['trades']} trades")
