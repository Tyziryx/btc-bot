import os
import warnings

import joblib
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

warnings.filterwarnings("ignore", category=FutureWarning)
optuna.logging.set_verbosity(optuna.logging.WARNING)


class BotModel:
    def __init__(self):
        self.model: xgb.XGBClassifier | None = None
        self.calibrator: IsotonicRegression | None = None
        self.best_params: dict = {}
        self.metrics: dict = {}

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        n_optuna_trials: int = 50,
        n_cv_splits: int = 5,
    ) -> dict:
        n = len(X)
        train_end = int(n * 0.70)
        cal_end = int(n * 0.85)

        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_cal, y_cal = X.iloc[train_end:cal_end], y.iloc[train_end:cal_end]
        X_test, y_test = X.iloc[cal_end:], y.iloc[cal_end:]

        def objective(trial):
            params = {
                "max_depth": trial.suggest_int("max_depth", 2, 6),
                "n_estimators": trial.suggest_int("n_estimators", 100, 800),
                "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.1, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 0.95),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 0.95),
                "min_child_weight": trial.suggest_int("min_child_weight", 5, 100),
                "gamma": trial.suggest_float("gamma", 0, 5),
                "reg_alpha": trial.suggest_float("reg_alpha", 0, 10),
                "reg_lambda": trial.suggest_float("reg_lambda", 1, 10),
            }

            tscv = TimeSeriesSplit(n_splits=min(n_cv_splits, 3))
            scores = []
            for train_idx, val_idx in tscv.split(X_train):
                clf = xgb.XGBClassifier(
                    **params,
                    eval_metric="logloss",
                    random_state=42,
                    verbosity=0,
                )
                clf.fit(X_train.iloc[train_idx], y_train.iloc[train_idx])
                proba = clf.predict_proba(X_train.iloc[val_idx])[:, 1]
                auc = roc_auc_score(y_train.iloc[val_idx], proba)
                scores.append(auc)
            return np.mean(scores)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_optuna_trials, show_progress_bar=False)
        self.best_params = study.best_params

        self.model = xgb.XGBClassifier(
            **self.best_params,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
        self.model.fit(X_train, y_train)

        cal_proba = self.model.predict_proba(X_cal)[:, 1]
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.calibrator.fit(cal_proba, y_cal)

        test_proba_raw = self.model.predict_proba(X_test)[:, 1]
        test_proba_cal = self.calibrator.predict(test_proba_raw)

        auc = roc_auc_score(y_test, test_proba_cal)
        brier = brier_score_loss(y_test, test_proba_cal)

        confidence = np.abs(test_proba_cal - 0.5) * 2
        top20_mask = confidence >= np.percentile(confidence, 80)
        if top20_mask.sum() > 0:
            preds_top20 = (test_proba_cal[top20_mask] >= 0.5).astype(int)
            acc_top20 = (preds_top20 == y_test.values[top20_mask]).mean()
        else:
            acc_top20 = 0.0

        self.metrics = {
            "auc_roc": auc,
            "brier_score": brier,
            "accuracy_top20": acc_top20,
            "best_params": self.best_params,
            "train_size": len(X_train),
            "cal_size": len(X_cal),
            "test_size": len(X_test),
        }

        print(f"AUC-ROC: {auc:.4f}")
        print(f"Brier Score: {brier:.4f}")
        print(f"Accuracy (top 20% confidence): {acc_top20:.4f}")

        return self.metrics

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise ValueError("Model not trained. Call train() or load() first.")
        return self.model.predict_proba(X)[:, 1]

    def predict_calibrated(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.predict_proba(X)
        if self.calibrator is None:
            return raw
        return self.calibrator.predict(raw)

    def get_confidence(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_calibrated(X)
        return np.abs(proba - 0.5) * 2

    def save(self, directory: str):
        os.makedirs(directory, exist_ok=True)
        joblib.dump(self.model, os.path.join(directory, "xgb_model.joblib"))
        joblib.dump(self.calibrator, os.path.join(directory, "calibrator.joblib"))
        joblib.dump(self.metrics, os.path.join(directory, "metrics.joblib"))
        joblib.dump(self.best_params, os.path.join(directory, "best_params.joblib"))

    def load(self, directory: str):
        self.model = joblib.load(os.path.join(directory, "xgb_model.joblib"))
        self.calibrator = joblib.load(os.path.join(directory, "calibrator.joblib"))
        self.metrics = joblib.load(os.path.join(directory, "metrics.joblib"))
        self.best_params = joblib.load(os.path.join(directory, "best_params.joblib"))
