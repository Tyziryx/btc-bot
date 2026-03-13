import numpy as np
import pandas as pd
import pytest
from bot.model import BotModel
from bot.features import FeatureEngine


@pytest.fixture
def dummy_dataset():
    np.random.seed(42)
    n = 1000
    X = pd.DataFrame({
        name: np.random.randn(n)
        for name in FeatureEngine.FEATURE_NAMES
    })
    # Make label slightly correlated with window_delta
    prob = 1 / (1 + np.exp(-2 * X["window_delta"]))
    y = (np.random.random(n) < prob).astype(int)
    return X, pd.Series(y, name="label")


def test_model_train_and_predict(dummy_dataset):
    X, y = dummy_dataset
    model = BotModel()
    metrics = model.train(X, y, n_optuna_trials=5)
    assert "auc_roc" in metrics
    assert "accuracy_top20" in metrics
    assert "brier_score" in metrics
    assert metrics["auc_roc"] > 0.5
    proba = model.predict_proba(X.iloc[:5])
    assert len(proba) == 5
    assert all(0 <= p <= 1 for p in proba)


def test_model_calibration(dummy_dataset):
    X, y = dummy_dataset
    model = BotModel()
    model.train(X, y, n_optuna_trials=5)
    cal_proba = model.predict_calibrated(X.iloc[:5])
    assert len(cal_proba) == 5
    assert all(0 <= p <= 1 for p in cal_proba)


def test_model_save_load(dummy_dataset, tmp_path):
    X, y = dummy_dataset
    model = BotModel()
    model.train(X, y, n_optuna_trials=5)
    model.save(str(tmp_path))
    model2 = BotModel()
    model2.load(str(tmp_path))
    p1 = model.predict_calibrated(X.iloc[:5])
    p2 = model2.predict_calibrated(X.iloc[:5])
    np.testing.assert_array_almost_equal(p1, p2)


def test_model_confidence(dummy_dataset):
    X, y = dummy_dataset
    model = BotModel()
    model.train(X, y, n_optuna_trials=5)
    conf = model.get_confidence(X.iloc[:5])
    assert len(conf) == 5
    assert all(0 <= c <= 1 for c in conf)
