import numpy as np
import pandas as pd
import pytest
from bot.features import FeatureEngine


@pytest.fixture
def sample_1min_data():
    """60 rows of 1min BTC data with realistic structure."""
    np.random.seed(42)
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    base_price = 84000.0
    changes = np.random.normal(0, 10, n)
    closes = base_price + np.cumsum(changes)
    opens = closes - np.random.normal(0, 5, n)
    highs = np.maximum(opens, closes) + np.abs(np.random.normal(0, 3, n))
    lows = np.minimum(opens, closes) - np.abs(np.random.normal(0, 3, n))
    volumes = np.random.uniform(50, 200, n)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "quote_volume": volumes * closes,
        "trades": np.random.randint(20, 100, n),
        "taker_buy_volume": volumes * np.random.uniform(0.3, 0.7, n),
        "taker_buy_quote_volume": volumes * closes * 0.5,
    }, index=dates)
    return df


@pytest.fixture
def sample_funding():
    dates = pd.date_range("2026-01-01", periods=8, freq="8h", tz="UTC")
    return pd.DataFrame({"funding_rate": [0.0001] * 8}, index=dates)


def test_feature_engine_output_shape(sample_1min_data, sample_funding):
    engine = FeatureEngine()
    features = engine.compute_all(sample_1min_data, sample_funding)
    assert len(features) > 0
    # 17 features (hour_of_day becomes sin + cos)
    assert features.shape[1] == 17


def test_window_delta(sample_1min_data, sample_funding):
    engine = FeatureEngine()
    features = engine.compute_all(sample_1min_data, sample_funding)
    assert "window_delta" in features.columns
    assert features["window_delta"].abs().max() < 0.1


def test_feature_names(sample_1min_data, sample_funding):
    engine = FeatureEngine()
    features = engine.compute_all(sample_1min_data, sample_funding)
    expected = [
        "window_delta", "micro_momentum", "acceleration",
        "cvd", "bid_ask_imbalance", "vwap_deviation",
        "ema_cross", "rsi_14", "z_score",
        "bollinger_bw", "realized_vol_15m", "volume_ratio",
        "candle_body_ratio", "funding_rate",
        "minute_in_window", "hour_sin", "hour_cos",
    ]
    assert list(features.columns) == expected


def test_no_nan_in_output(sample_1min_data, sample_funding):
    engine = FeatureEngine()
    features = engine.compute_all(sample_1min_data, sample_funding)
    assert not features.isna().any().any(), (
        f"NaN found in columns: {features.columns[features.isna().any()].tolist()}"
    )
