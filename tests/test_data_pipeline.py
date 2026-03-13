import pandas as pd
import pytest
from bot.data_pipeline import BinanceDataDownloader


def test_parse_kline_csv(tmp_path):
    csv_content = (
        "1704067200000,42000.0,42100.0,41900.0,42050.0,100.5,"
        "1704067259999,4225275.0,50,60.3,2535150.0,0\n"
        "1704067260000,42050.0,42150.0,41950.0,42100.0,110.2,"
        "1704067319999,4635420.0,55,65.1,2740710.0,0\n"
    )
    csv_file = tmp_path / "test.csv"
    csv_file.write_text(csv_content)

    dl = BinanceDataDownloader(data_dir=str(tmp_path))
    df = dl.parse_kline_csv(str(csv_file))

    assert len(df) == 2
    assert list(df.columns) == [
        "open_time", "open", "high", "low", "close",
        "volume", "close_time", "quote_volume",
        "trades", "taker_buy_volume", "taker_buy_quote_volume",
    ]
    assert df["open"].iloc[0] == 42000.0
    assert df["close"].iloc[1] == 42100.0
    assert isinstance(df.index, pd.DatetimeIndex)


def test_build_download_url():
    dl = BinanceDataDownloader()
    url = dl.build_download_url("BTCUSDT", "1m", 2026, 1)
    assert url == (
        "https://data.binance.vision/data/spot/monthly/klines/"
        "BTCUSDT/1m/BTCUSDT-1m-2026-01.zip"
    )


def test_resample_to_5min(tmp_path):
    import numpy as np
    dates = pd.date_range("2026-01-01", periods=10, freq="1min", tz="UTC")
    df = pd.DataFrame({
        "open": [100 + i for i in range(10)],
        "high": [101 + i for i in range(10)],
        "low": [99 + i for i in range(10)],
        "close": [100.5 + i for i in range(10)],
        "volume": [10.0] * 10,
        "quote_volume": [1000.0] * 10,
        "trades": [5] * 10,
        "taker_buy_volume": [6.0] * 10,
        "taker_buy_quote_volume": [600.0] * 10,
    }, index=dates)
    df["close_time"] = df.index + pd.Timedelta(seconds=59)

    dl = BinanceDataDownloader(data_dir=str(tmp_path))
    result = dl.resample_to_5min(df)

    assert len(result) == 2
    assert result["open"].iloc[0] == 100
    assert result["close"].iloc[0] == 104.5
    assert result["label"].iloc[0] == 1
