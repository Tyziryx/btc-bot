import numpy as np
import pandas as pd
import pytest
from bot.features import FeatureEngine
from bot.data_pipeline import BinanceDataDownloader


def test_training_dataset_alignment():
    """Features at each 5min boundary should align with labels."""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    base = 84000.0
    closes = base + np.cumsum(np.random.normal(0, 10, n))
    opens = closes - np.random.normal(0, 5, n)

    df_1min = pd.DataFrame({
        "open": opens,
        "high": np.maximum(opens, closes) + 3,
        "low": np.minimum(opens, closes) - 3,
        "close": closes,
        "volume": np.random.uniform(50, 200, n),
        "quote_volume": np.random.uniform(50, 200, n) * closes,
        "trades": np.random.randint(20, 100, n),
        "taker_buy_volume": np.random.uniform(20, 100, n),
        "taker_buy_quote_volume": np.random.uniform(20, 100, n) * closes,
        "close_time": dates + pd.Timedelta(seconds=59),
    }, index=dates)

    dl = BinanceDataDownloader()
    df_5min = dl.resample_to_5min(df_1min)

    engine = FeatureEngine()
    features = engine.compute_all(df_1min)

    # Features at minute 4 (last minute of window) should predict label of that window
    features_at_boundary = features[features.index.minute % 5 == 4]
    features_at_boundary_floored = features_at_boundary.copy()
    features_at_boundary_floored.index = features_at_boundary_floored.index.floor("5min")

    common = df_5min.index.intersection(features_at_boundary_floored.index)
    assert len(common) > 0

    X = features_at_boundary_floored.loc[common]
    y = df_5min.loc[common, "label"]
    assert len(X) == len(y)
    assert set(y.unique()).issubset({0, 1})
