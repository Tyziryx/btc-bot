import io
import os
import zipfile
from datetime import datetime, timezone
from typing import Optional, Union

import pandas as pd
import requests

from bot.config import Config


class BinanceDataDownloader:
    KLINE_COLUMNS = [
        "open_time", "open", "high", "low", "close",
        "volume", "close_time", "quote_volume",
        "trades", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
    ]

    def __init__(self, data_dir: str = "data", config: Optional[Config] = None):
        self.config = config or Config()
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def build_download_url(self, symbol: str, interval: str, year: int, month: int) -> str:
        filename = f"{symbol}-{interval}-{year}-{month:02d}.zip"
        return (
            f"https://data.binance.vision/data/spot/monthly/klines/"
            f"{symbol}/{interval}/{filename}"
        )

    def download_month(self, symbol: str, interval: str, year: int, month: int) -> str:
        url = self.build_download_url(symbol, interval, year, month)
        out_path = os.path.join(
            self.data_dir, f"{symbol}-{interval}-{year}-{month:02d}.parquet"
        )
        if os.path.exists(out_path):
            print(f"Already exists: {out_path}")
            return out_path

        print(f"Downloading {url} ...")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                df = self.parse_kline_csv(f)

        df.to_parquet(out_path)
        print(f"Saved {len(df)} rows to {out_path}")
        return out_path

    def parse_kline_csv(self, path_or_buf: Union[str, io.IOBase]) -> pd.DataFrame:
        df = pd.read_csv(
            path_or_buf,
            header=None,
            names=self.KLINE_COLUMNS,
            dtype={
                "open": float, "high": float, "low": float, "close": float,
                "volume": float, "quote_volume": float, "trades": int,
                "taker_buy_volume": float, "taker_buy_quote_volume": float,
            },
        )
        df.drop(columns=["ignore"], inplace=True, errors="ignore")
        # Binance switched from ms to us timestamps; auto-detect based on magnitude
        sample_ts = df["open_time"].iloc[0]
        unit = "us" if sample_ts > 1e15 else "ms"
        df.index = pd.to_datetime(df["open_time"], unit=unit, utc=True)
        df.index.name = "datetime"
        return df

    def download_klines(self, symbol: str = "BTCUSDT", interval: str = "1m", months: int = 3) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        frames = []
        for i in range(months, 0, -1):
            month = now.month - i
            year = now.year
            while month <= 0:
                month += 12
                year -= 1
            path = self.download_month(symbol, interval, year, month)
            frames.append(pd.read_parquet(path))

        df = pd.concat(frames).sort_index()
        df = df[~df.index.duplicated(keep="first")]
        return df

    def resample_to_5min(self, df_1min: pd.DataFrame) -> pd.DataFrame:
        resampled = df_1min.resample("5min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "quote_volume": "sum",
            "trades": "sum",
            "taker_buy_volume": "sum",
            "taker_buy_quote_volume": "sum",
        }).dropna()

        resampled["label"] = (resampled["close"] >= resampled["open"]).astype(int)
        return resampled

    def download_funding_rates(self, symbol: str = "BTCUSDT", months: int = 3) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        start_ts = int((now - pd.Timedelta(days=months * 31)).timestamp() * 1000)
        all_rates = []
        current_start = start_ts

        while True:
            resp = requests.get(
                f"{self.config.BINANCE_FUTURES_BASE}/fapi/v1/fundingRate",
                params={"symbol": symbol, "startTime": current_start, "limit": 1000},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            all_rates.extend(data)
            current_start = data[-1]["fundingTime"] + 1

        if not all_rates:
            return pd.DataFrame(columns=["funding_rate"])

        df = pd.DataFrame(all_rates)
        df["funding_rate"] = df["fundingRate"].astype(float)
        df.index = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df.index.name = "datetime"
        return df[["funding_rate"]]
