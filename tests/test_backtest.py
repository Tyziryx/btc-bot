import numpy as np
import pandas as pd
import pytest
from bot.backtest import BacktestEngine


@pytest.fixture
def dummy_backtest_data():
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    probas = np.random.uniform(0.3, 0.7, n)
    labels = (np.random.random(n) < 0.52).astype(int)
    return pd.DataFrame({
        "prob_calibrated": probas,
        "label": labels,
    }, index=dates)


def test_backtest_runs(dummy_backtest_data):
    engine = BacktestEngine(initial_capital=100.0, min_confidence=0.20)
    results = engine.run(dummy_backtest_data)
    assert "total_trades" in results
    assert "win_rate" in results
    assert "final_capital" in results
    assert "max_drawdown" in results
    assert "profit_factor" in results
    assert results["total_trades"] > 0


def test_backtest_no_trades_below_confidence():
    n = 100
    dates = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    data = pd.DataFrame({
        "prob_calibrated": [0.5] * n,
        "label": [1] * n,
    }, index=dates)
    engine = BacktestEngine(initial_capital=100.0, min_confidence=0.6)
    results = engine.run(data)
    assert results["total_trades"] == 0


def test_backtest_capital_never_negative(dummy_backtest_data):
    engine = BacktestEngine(initial_capital=100.0, min_confidence=0.20)
    results = engine.run(dummy_backtest_data)
    assert all(c >= 0 for c in results["capital_curve"])
