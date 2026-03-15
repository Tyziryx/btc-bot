# Phase 1: Data Pipeline & Feature Engineering — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download 3 months of Binance BTC/USDT data, build 17 features, generate UP/DOWN labels for XGBoost training.

**Architecture:** Modular Python package with separate modules for config, data download, feature computation. Data stored as Parquet files. Features computed from 1min klines with aggTrades for CVD and funding rates from Futures API.

**Tech Stack:** Python 3.11+, pandas, numpy, ta (technical indicators), python-binance, pyarrow, python-dotenv

---

## Chunk 1: Project Setup & Config

### Task 1: Initialize project structure

**Files:**
- Create: `bot/config.py`
- Create: `bot/__init__.py`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Init git repo and create .gitignore**

```bash
cd C:/Users/alexi/Desktop/BOT
git init
```

`.gitignore`:
```
.env
*.db
data/
models/
__pycache__/
*.pyc
.pytest_cache/
venv/
```

- [ ] **Step 2: Create requirements.txt**

```
python-binance>=1.0.29
pandas>=2.0
numpy>=1.24
scikit-learn>=1.3
xgboost>=2.0
ta>=0.11
optuna>=3.0
shap>=0.43
joblib>=1.3
python-dotenv>=1.0
pyarrow>=14.0
websockets>=12.0
pytest>=7.0
```

- [ ] **Step 3: Create virtual env and install deps**

```bash
cd C:/Users/alexi/Desktop/BOT
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
```

- [ ] **Step 4: Write test for config**

`tests/test_config.py`:
```python
from bot.config import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.SYMBOL == "BTCUSDT"
    assert cfg.KLINE_INTERVAL == "1m"
    assert cfg.WINDOW_SECONDS == 300
    assert cfg.DATA_DIR == "data"
    assert cfg.MODELS_DIR == "models"
    assert cfg.MIN_BET == 2.0
    assert cfg.MAX_BET == 40.0
    assert cfg.MAX_BET_FRACTION == 0.02
    assert cfg.DAILY_STOP_LOSS == 0.05
    assert cfg.MAX_DRAWDOWN == 0.15
    assert cfg.MIN_CONFIDENCE == 0.60
    assert cfg.MIN_EDGE == 0.03
    assert cfg.CIRCUIT_BREAKER_LOSSES == 5
    assert cfg.CIRCUIT_BREAKER_PAUSE_MIN == 30


def test_config_data_dir_creation(tmp_path):
    cfg = Config(data_dir=str(tmp_path / "test_data"))
    cfg.ensure_dirs()
    assert (tmp_path / "test_data").exists()
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd C:/Users/alexi/Desktop/BOT
source venv/Scripts/activate
python -m pytest tests/test_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'bot'`

- [ ] **Step 6: Write config.py**

`bot/__init__.py`:
```python
```

`bot/config.py`:
```python
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Data sources
    SYMBOL: str = "BTCUSDT"
    KLINE_INTERVAL: str = "1m"
    WINDOW_SECONDS: int = 300  # 5 minutes

    # Directories
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
    MODELS_DIR: str = field(default_factory=lambda: os.getenv("MODELS_DIR", "models"))

    # Risk management
    MIN_BET: float = 2.0
    MAX_BET: float = 40.0
    MAX_BET_FRACTION: float = 0.02
    DAILY_STOP_LOSS: float = 0.05
    MAX_DRAWDOWN: float = 0.15
    MIN_CONFIDENCE: float = 0.60
    MIN_EDGE: float = 0.03
    CIRCUIT_BREAKER_LOSSES: int = 5
    CIRCUIT_BREAKER_PAUSE_MIN: int = 30

    # Binance data.binance.vision base URL
    BINANCE_DATA_BASE: str = "https://data.binance.vision/data/spot/monthly/klines"
    BINANCE_FUTURES_BASE: str = "https://fapi.binance.com"

    # Polymarket
    POLYMARKET_PRIVATE_KEY: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", "")
    )
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"

    def __post_init__(self):
        self.data_dir = self.DATA_DIR
        self.models_dir = self.MODELS_DIR

    def ensure_dirs(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)
        os.makedirs(self.MODELS_DIR, exist_ok=True)
```

`.env.example`:
```
DATA_DIR=data
MODELS_DIR=models
POLYMARKET_PRIVATE_KEY=
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python -m pytest tests/test_config.py -v
```
Expected: 2 PASSED

- [ ] **Step 8: Commit**

```bash
git add bot/ tests/ requirements.txt .gitignore .env.example
git commit -m "feat: project setup with config module"
```

---

## Chunk 2: Historical Data Download

### Task 2: Download klines from data.binance.vision

**Files:**
- Create: `bot/data_pipeline.py`
- Create: `tests/test_data_pipeline.py`

- [ ] **Step 1: Write test for kline download and parsing**

`tests/test_data_pipeline.py`:
```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
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
    # Create 10 rows of 1min data (= 2 windows of 5min)
    import numpy as np
    dates = pd.date_range("2026-01-01", periods=10, freq="1min")
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
    # Add required columns
    df["close_time"] = df.index + pd.Timedelta(seconds=59)

    dl = BinanceDataDownloader(data_dir=str(tmp_path))
    result = dl.resample_to_5min(df)

    assert len(result) == 2
    # First 5min window: open of first candle
    assert result["open"].iloc[0] == 100
    # First 5min window: close of 5th candle
    assert result["close"].iloc[0] == 104.5
    # Label: close >= open -> UP (1)
    assert result["label"].iloc[0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_data_pipeline.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement BinanceDataDownloader**

`bot/data_pipeline.py`:
```python
import io
import os
import zipfile
from datetime import datetime, timezone

import pandas as pd
import requests

from bot.config import Config


class BinanceDataDownloader:
    KLINE_COLUMNS = [
        "open_time", "open", "high", "low", "close",
        "volume", "close_time", "quote_volume",
        "trades", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
    ]

    def __init__(self, data_dir: str = "data", config: Config | None = None):
        self.config = config or Config()
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def build_download_url(
        self, symbol: str, interval: str, year: int, month: int
    ) -> str:
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

    def parse_kline_csv(self, path_or_buf) -> pd.DataFrame:
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
        df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.index.name = "datetime"
        return df

    def download_klines(
        self, symbol: str = "BTCUSDT", interval: str = "1m", months: int = 3
    ) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        frames = []
        for i in range(months, 0, -1):
            # Go back i months
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

        # Label: UP (1) if close >= open, DOWN (0) otherwise
        resampled["label"] = (resampled["close"] >= resampled["open"]).astype(int)
        return resampled

    def download_funding_rates(
        self, symbol: str = "BTCUSDT", months: int = 3
    ) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        start_ts = int(
            (now - pd.Timedelta(days=months * 31)).timestamp() * 1000
        )
        all_rates = []
        current_start = start_ts

        while True:
            resp = requests.get(
                f"{self.config.BINANCE_FUTURES_BASE}/fapi/v1/fundingRate",
                params={
                    "symbol": symbol,
                    "startTime": current_start,
                    "limit": 1000,
                },
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_data_pipeline.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/data_pipeline.py tests/test_data_pipeline.py
git commit -m "feat: data pipeline for Binance kline download and 5min resampling"
```

---

### Task 3: Download real data (manual step)

- [ ] **Step 1: Create download script**

Create `scripts/download_data.py`:
```python
"""Download 3 months of BTC/USDT 1min klines + funding rates from Binance."""
import sys
sys.path.insert(0, ".")

from bot.config import Config
from bot.data_pipeline import BinanceDataDownloader

cfg = Config()
cfg.ensure_dirs()
dl = BinanceDataDownloader(data_dir=cfg.DATA_DIR, config=cfg)

print("=== Downloading 1min klines ===")
df_1min = dl.download_klines("BTCUSDT", "1m", months=3)
print(f"Total 1min candles: {len(df_1min)}")
print(f"Date range: {df_1min.index[0]} → {df_1min.index[-1]}")

# Save combined
combined_path = f"{cfg.DATA_DIR}/BTCUSDT-1m-combined.parquet"
df_1min.to_parquet(combined_path)
print(f"Saved combined to {combined_path}")

print("\n=== Resampling to 5min ===")
df_5min = dl.resample_to_5min(df_1min)
print(f"Total 5min windows: {len(df_5min)}")
print(f"UP ratio: {df_5min['label'].mean():.4f}")
df_5min.to_parquet(f"{cfg.DATA_DIR}/BTCUSDT-5min-labeled.parquet")

print("\n=== Downloading funding rates ===")
df_funding = dl.download_funding_rates("BTCUSDT", months=3)
print(f"Total funding rates: {len(df_funding)}")
df_funding.to_parquet(f"{cfg.DATA_DIR}/BTCUSDT-funding-rates.parquet")

print("\nDone!")
```

- [ ] **Step 2: Run the download**

```bash
cd C:/Users/alexi/Desktop/BOT
source venv/Scripts/activate
python scripts/download_data.py
```
Expected: Downloads ~3 zip files, creates parquet files in `data/`

- [ ] **Step 3: Commit script (not data)**

```bash
git add scripts/download_data.py
git commit -m "feat: data download script for 3 months BTC klines + funding"
```

---

## Chunk 3: Feature Engineering

### Task 4: Implement feature computation

**Files:**
- Create: `bot/features.py`
- Create: `tests/test_features.py`

- [ ] **Step 1: Write tests for feature computation**

`tests/test_features.py`:
```python
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
    # Random walk for close prices
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
    # Should have rows (some lost to indicator warmup)
    assert len(features) > 0
    # 17 features (hour_of_day becomes sin + cos)
    assert features.shape[1] == 17


def test_window_delta(sample_1min_data, sample_funding):
    engine = FeatureEngine()
    features = engine.compute_all(sample_1min_data, sample_funding)
    assert "window_delta" in features.columns
    # Window delta should be a small percentage
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_features.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement FeatureEngine**

`bot/features.py`:
```python
import numpy as np
import pandas as pd
import ta


class FeatureEngine:
    FEATURE_NAMES = [
        "window_delta", "micro_momentum", "acceleration",
        "cvd", "bid_ask_imbalance", "vwap_deviation",
        "ema_cross", "rsi_14", "z_score",
        "bollinger_bw", "realized_vol_15m", "volume_ratio",
        "candle_body_ratio", "funding_rate",
        "minute_in_window", "hour_sin", "hour_cos",
    ]
    WARMUP_PERIODS = 25  # Enough for BB(20), EMA(21), RSI(14)

    def compute_all(
        self,
        df_1min: pd.DataFrame,
        df_funding: pd.DataFrame | None = None,
        bid_qty: float = 0.0,
        ask_qty: float = 0.0,
    ) -> pd.DataFrame:
        df = df_1min.copy()
        close = df["close"]
        open_ = df["open"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        features = pd.DataFrame(index=df.index)

        # --- Cat 1: Direction in window ---
        # Window delta: position in current 5min window
        window_open = open_.groupby(
            df.index.floor("5min")
        ).transform("first")
        features["window_delta"] = (close - window_open) / window_open

        # Micro momentum: sum of returns of last 2 candles
        returns = close.pct_change()
        features["micro_momentum"] = returns.rolling(2).sum()

        # Acceleration: change in momentum
        momentum = returns.rolling(2).sum()
        features["acceleration"] = momentum.diff()

        # --- Cat 2: Order Flow ---
        # CVD proxy from taker buy volume
        if "taker_buy_volume" in df.columns:
            sell_volume = volume - df["taker_buy_volume"]
            buy_volume = df["taker_buy_volume"]
            delta = buy_volume - sell_volume
            features["cvd"] = delta.rolling(5).sum()
        else:
            features["cvd"] = 0.0

        # Bid-Ask imbalance (from live data; 0 for historical)
        total_qty = bid_qty + ask_qty
        if total_qty > 0:
            features["bid_ask_imbalance"] = (bid_qty - ask_qty) / total_qty
        else:
            features["bid_ask_imbalance"] = 0.0

        # VWAP deviation
        cum_vol = volume.rolling(5).sum()
        cum_vwap = (close * volume).rolling(5).sum() / cum_vol
        features["vwap_deviation"] = (close - cum_vwap) / cum_vwap

        # --- Cat 3: Trend & Momentum ---
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        features["ema_cross"] = (ema9 - ema21) / ema21

        features["rsi_14"] = ta.momentum.rsi(close, window=14) / 100.0

        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        features["z_score"] = (close - sma20) / std20

        # --- Cat 4: Volatility & Regime ---
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband()
        bb_lower = bb.bollinger_lband()
        bb_middle = bb.bollinger_mavg()
        features["bollinger_bw"] = (bb_upper - bb_lower) / bb_middle

        features["realized_vol_15m"] = returns.rolling(15).std()

        vol_ma3 = volume.rolling(3).mean()
        features["volume_ratio"] = volume / vol_ma3

        # --- Cat 5: Microstructure & Context ---
        body = (close - open_).abs()
        wick = high - low + 1e-10
        features["candle_body_ratio"] = body / wick

        # Funding rate: forward-fill from 8h data
        if df_funding is not None and not df_funding.empty:
            features["funding_rate"] = (
                df_funding["funding_rate"]
                .reindex(df.index, method="ffill")
                .fillna(0.0)
            )
        else:
            features["funding_rate"] = 0.0

        # Minute in window (0-4)
        features["minute_in_window"] = df.index.minute % 5

        # Hour of day (cyclical encoding)
        hour = df.index.hour + df.index.minute / 60.0
        features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * hour / 24)

        # Drop warmup rows and NaNs
        features = features.iloc[self.WARMUP_PERIODS:]
        features = features.dropna()

        return features

    def compute_live(
        self,
        df_1min: pd.DataFrame,
        df_funding: pd.DataFrame | None = None,
        bid_qty: float = 0.0,
        ask_qty: float = 0.0,
    ) -> pd.Series:
        """Compute features for the latest candle only (live trading)."""
        features = self.compute_all(df_1min, df_funding, bid_qty, ask_qty)
        if features.empty:
            raise ValueError("Not enough data to compute features")
        return features.iloc[-1]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_features.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/features.py tests/test_features.py
git commit -m "feat: feature engine with 17 features for XGBoost"
```

---

### Task 5: Build training dataset

**Files:**
- Create: `scripts/build_training_data.py`
- Create: `tests/test_build_dataset.py`

- [ ] **Step 1: Write test for dataset builder**

`tests/test_build_dataset.py`:
```python
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

    # Features at minute X:04 (last minute of window) should predict label of that window
    # Align by flooring to 5min
    features_at_boundary = features[features.index.minute % 5 == 4]
    features_at_boundary_floored = features_at_boundary.copy()
    features_at_boundary_floored.index = features_at_boundary_floored.index.floor("5min")

    common = df_5min.index.intersection(features_at_boundary_floored.index)
    assert len(common) > 0

    X = features_at_boundary_floored.loc[common]
    y = df_5min.loc[common, "label"]
    assert len(X) == len(y)
    assert set(y.unique()).issubset({0, 1})
```

- [ ] **Step 2: Run test**

```bash
python -m pytest tests/test_build_dataset.py -v
```
Expected: PASS

- [ ] **Step 3: Create build script**

`scripts/build_training_data.py`:
```python
"""Build training dataset: features + labels aligned at 5min boundaries."""
import sys
sys.path.insert(0, ".")

import pandas as pd
from bot.config import Config
from bot.data_pipeline import BinanceDataDownloader
from bot.features import FeatureEngine

cfg = Config()
dl = BinanceDataDownloader(data_dir=cfg.DATA_DIR, config=cfg)
engine = FeatureEngine()

print("=== Loading 1min data ===")
df_1min = pd.read_parquet(f"{cfg.DATA_DIR}/BTCUSDT-1m-combined.parquet")
print(f"Loaded {len(df_1min)} candles")

print("=== Loading funding rates ===")
try:
    df_funding = pd.read_parquet(f"{cfg.DATA_DIR}/BTCUSDT-funding-rates.parquet")
    print(f"Loaded {len(df_funding)} funding rate entries")
except FileNotFoundError:
    df_funding = None
    print("No funding data found, using 0")

print("=== Computing features ===")
features = engine.compute_all(df_1min, df_funding)
print(f"Feature matrix: {features.shape}")

print("=== Building 5min labels ===")
df_5min = dl.resample_to_5min(df_1min)
print(f"5min windows: {len(df_5min)}, UP ratio: {df_5min['label'].mean():.4f}")

print("=== Aligning features to labels ===")
# Take features at minute 4 (last minute of each 5min window)
# These represent the "state" just before the window closes
feat_at_boundary = features[features.index.minute % 5 == 4].copy()
feat_at_boundary.index = feat_at_boundary.index.floor("5min")

common = df_5min.index.intersection(feat_at_boundary.index)
X = feat_at_boundary.loc[common]
y = df_5min.loc[common, "label"]

print(f"Training samples: {len(X)}")
print(f"Features: {list(X.columns)}")
print(f"Label distribution: UP={y.mean():.4f}, DOWN={1-y.mean():.4f}")

# Save
X.to_parquet(f"{cfg.DATA_DIR}/training_features.parquet")
y.to_frame("label").to_parquet(f"{cfg.DATA_DIR}/training_labels.parquet")
print(f"\nSaved to {cfg.DATA_DIR}/training_features.parquet")
print(f"Saved to {cfg.DATA_DIR}/training_labels.parquet")
print("Done!")
```

- [ ] **Step 4: Run the build script**

```bash
python scripts/build_training_data.py
```
Expected: Creates `training_features.parquet` and `training_labels.parquet`

- [ ] **Step 5: Commit**

```bash
git add scripts/build_training_data.py tests/test_build_dataset.py
git commit -m "feat: training dataset builder - features aligned to 5min labels"
```

---

## Chunk 4: Model Training & Calibration

### Task 6: XGBoost training with Optuna + calibration

**Files:**
- Create: `bot/model.py`
- Create: `tests/test_model.py`

- [ ] **Step 1: Write tests for model**

`tests/test_model.py`:
```python
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
    assert metrics["auc_roc"] > 0.5  # Better than random

    proba = model.predict_proba(X.iloc[:5])
    assert len(proba) == 5
    assert all(0 <= p <= 1 for p in proba)


def test_model_calibration(dummy_dataset):
    X, y = dummy_dataset
    model = BotModel()
    model.train(X, y, n_optuna_trials=5)

    # Calibrated probas should be between 0 and 1
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_model.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement BotModel**

`bot/model.py`:
```python
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
        # Split: 70% train, 15% calibration, 15% test (temporal)
        train_end = int(n * 0.70)
        cal_end = int(n * 0.85)

        X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]
        X_cal, y_cal = X.iloc[train_end:cal_end], y.iloc[train_end:cal_end]
        X_test, y_test = X.iloc[cal_end:], y.iloc[cal_end:]

        # Optuna optimization on train set with TimeSeriesSplit
        def objective(trial):
            params = {
                "max_depth": trial.suggest_int("max_depth", 2, 6),
                "n_estimators": trial.suggest_int("n_estimators", 100, 800),
                "learning_rate": trial.suggest_float(
                    "learning_rate", 0.005, 0.1, log=True
                ),
                "subsample": trial.suggest_float("subsample", 0.6, 0.95),
                "colsample_bytree": trial.suggest_float(
                    "colsample_bytree", 0.5, 0.95
                ),
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
                    use_label_encoder=False,
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

        # Train final model on full train set
        self.model = xgb.XGBClassifier(
            **self.best_params,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            verbosity=0,
        )
        self.model.fit(X_train, y_train)

        # Calibrate on calibration set
        cal_proba = self.model.predict_proba(X_cal)[:, 1]
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.calibrator.fit(cal_proba, y_cal)

        # Evaluate on test set
        test_proba_raw = self.model.predict_proba(X_test)[:, 1]
        test_proba_cal = self.calibrator.predict(test_proba_raw)

        auc = roc_auc_score(y_test, test_proba_cal)
        brier = brier_score_loss(y_test, test_proba_cal)

        # Accuracy on top 20% confidence
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_model.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/model.py tests/test_model.py
git commit -m "feat: XGBoost model with Optuna optimization and isotonic calibration"
```

---

### Task 7: Training script with validation report

**Files:**
- Create: `scripts/train_model.py`

- [ ] **Step 1: Create training script**

`scripts/train_model.py`:
```python
"""Train XGBoost model on prepared dataset with full validation report."""
import sys
sys.path.insert(0, ".")

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

# Check production readiness thresholds
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
    print("\nModel did NOT pass all checks. Not saving.")
    print("Consider: more data, different features, or adjusted thresholds.")

# Feature importance
import numpy as np
importances = model.model.feature_importances_
feat_names = X.columns
sorted_idx = np.argsort(importances)[::-1]
print("\n=== Feature Importance ===")
for i in sorted_idx:
    print(f"  {feat_names[i]:25s} {importances[i]:.4f}")
```

- [ ] **Step 2: Run training**

```bash
python scripts/train_model.py
```
Expected: Trains model, prints validation report, saves if passing

- [ ] **Step 3: Commit**

```bash
git add scripts/train_model.py
git commit -m "feat: model training script with validation report"
```

---

## Chunk 5: Backtest Engine

### Task 8: Backtest simulator

**Files:**
- Create: `bot/backtest.py`
- Create: `tests/test_backtest.py`

- [ ] **Step 1: Write tests for backtest**

`tests/test_backtest.py`:
```python
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
    labels = (np.random.random(n) < 0.52).astype(int)  # Slight UP bias
    return pd.DataFrame({
        "prob_calibrated": probas,
        "label": labels,
    }, index=dates)


def test_backtest_runs(dummy_backtest_data):
    engine = BacktestEngine(initial_capital=100.0)
    results = engine.run(dummy_backtest_data)
    assert "total_trades" in results
    assert "win_rate" in results
    assert "final_capital" in results
    assert "max_drawdown" in results
    assert "profit_factor" in results
    assert results["total_trades"] > 0


def test_backtest_no_trades_below_confidence():
    """If all probas are near 0.5, no trades should be taken."""
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
    engine = BacktestEngine(initial_capital=100.0)
    results = engine.run(dummy_backtest_data)
    assert all(c >= 0 for c in results["capital_curve"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_backtest.py -v
```

- [ ] **Step 3: Implement BacktestEngine**

`bot/backtest.py`:
```python
import random

import numpy as np
import pandas as pd


class BacktestEngine:
    FILL_RATES = {
        (0.45, 1.00): 0.95,
        (0.40, 0.45): 0.85,
        (0.35, 0.40): 0.65,
        (0.00, 0.35): 0.40,
    }

    def __init__(
        self,
        initial_capital: float = 100.0,
        min_confidence: float = 0.60,
        min_edge: float = 0.03,
        max_bet_fraction: float = 0.02,
        max_bet: float = 40.0,
        min_bet: float = 2.0,
        daily_stop_loss: float = 0.05,
        max_drawdown: float = 0.15,
        circuit_breaker_losses: int = 5,
    ):
        self.initial_capital = initial_capital
        self.min_confidence = min_confidence
        self.min_edge = min_edge
        self.max_bet_fraction = max_bet_fraction
        self.max_bet = max_bet
        self.min_bet = min_bet
        self.daily_stop_loss = daily_stop_loss
        self.max_drawdown = max_drawdown
        self.circuit_breaker_losses = circuit_breaker_losses

    def _get_fill_rate(self, entry_price: float) -> float:
        for (lo, hi), rate in self.FILL_RATES.items():
            if lo <= entry_price < hi:
                return rate
        return 0.5

    def _calculate_entry_price(self, prob: float) -> float:
        """Simulate entry price based on probability."""
        if prob > 0.5:
            fair_value = prob
        else:
            fair_value = 1 - prob
        entry = fair_value - self.min_edge
        # Add small random noise (anti-adversarial simulation)
        entry += random.uniform(-0.005, 0.005)
        return max(0.25, min(entry, 0.55))

    def _quarter_kelly(
        self, capital: float, confidence: float, win_rate: float, entry_price: float
    ) -> float:
        b = (1.0 - entry_price) / entry_price  # odds
        p = win_rate
        kelly = (p * b - (1 - p)) / b if b > 0 else 0
        kelly = max(kelly, 0)
        fraction = kelly / 4 * confidence
        bet = capital * fraction
        return max(self.min_bet, min(bet, capital * self.max_bet_fraction, self.max_bet))

    def run(self, data: pd.DataFrame) -> dict:
        capital = self.initial_capital
        peak_capital = capital
        trades = []
        capital_curve = [capital]
        consecutive_losses = 0
        daily_start_capital = capital
        current_day = None
        paused_until = None

        for ts, row in data.iterrows():
            prob = row["prob_calibrated"]
            label = int(row["label"])

            # Daily reset
            day = ts.date()
            if day != current_day:
                current_day = day
                daily_start_capital = capital

            # Check pauses
            if paused_until is not None and ts < paused_until:
                capital_curve.append(capital)
                continue
            paused_until = None

            # Daily stop loss
            if (daily_start_capital - capital) / daily_start_capital > self.daily_stop_loss:
                capital_curve.append(capital)
                continue

            # Max drawdown
            if (peak_capital - capital) / peak_capital > self.max_drawdown:
                capital_curve.append(capital)
                continue

            # Confidence check
            confidence = abs(prob - 0.5) * 2
            if confidence < self.min_confidence:
                capital_curve.append(capital)
                continue

            # Entry price
            entry_price = self._calculate_entry_price(prob)
            fair_value = prob if prob > 0.5 else (1 - prob)

            # Edge check
            if fair_value - entry_price < self.min_edge:
                capital_curve.append(capital)
                continue

            # Fill simulation
            fill_rate = self._get_fill_rate(entry_price)
            if random.random() > fill_rate:
                capital_curve.append(capital)
                continue

            # Bet sizing
            rolling_wr = 0.55  # Use default for first trades
            if len(trades) >= 20:
                recent = trades[-20:]
                rolling_wr = sum(1 for t in recent if t["result"] == "win") / len(recent)
                rolling_wr = max(rolling_wr, 0.50)

            bet_size = self._quarter_kelly(capital, confidence, rolling_wr, entry_price)
            if bet_size > capital:
                capital_curve.append(capital)
                continue

            # Determine direction and result
            predicted_up = prob > 0.5
            actual_up = label == 1
            win = predicted_up == actual_up

            if win:
                pnl = bet_size * (1.0 - entry_price) / entry_price
                consecutive_losses = 0
            else:
                pnl = -bet_size
                consecutive_losses += 1

            capital += pnl
            capital = max(capital, 0)
            peak_capital = max(peak_capital, capital)

            trades.append({
                "timestamp": ts,
                "direction": "UP" if predicted_up else "DOWN",
                "confidence": confidence,
                "entry_price": entry_price,
                "bet_size": bet_size,
                "result": "win" if win else "loss",
                "pnl": pnl,
                "capital": capital,
            })

            # Circuit breaker
            if consecutive_losses >= self.circuit_breaker_losses:
                paused_until = ts + pd.Timedelta(minutes=30)
                consecutive_losses = 0

            capital_curve.append(capital)

        # Compute metrics
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "final_capital": capital,
                "roi": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "capital_curve": capital_curve,
                "trades": [],
            }

        wins = [t for t in trades if t["result"] == "win"]
        losses = [t for t in trades if t["result"] == "loss"]
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1

        # Max drawdown from capital curve
        curve = np.array(capital_curve)
        running_max = np.maximum.accumulate(curve)
        drawdowns = (running_max - curve) / running_max
        max_dd = drawdowns.max()

        # Sharpe (daily)
        pnls = [t["pnl"] for t in trades]
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252 * 24 * 12)
        else:
            sharpe = 0.0

        return {
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades),
            "final_capital": capital,
            "roi": (capital - self.initial_capital) / self.initial_capital,
            "max_drawdown": max_dd,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            "sharpe_ratio": sharpe,
            "capital_curve": capital_curve,
            "trades": trades,
        }
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_backtest.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/backtest.py tests/test_backtest.py
git commit -m "feat: backtest engine with realistic fill rate and risk management"
```

---

### Task 9: Backtest runner script

**Files:**
- Create: `scripts/run_backtest.py`

- [ ] **Step 1: Create backtest runner**

`scripts/run_backtest.py`:
```python
"""Run backtest on trained model with full metrics report."""
import sys
sys.path.insert(0, ".")

import pandas as pd
import numpy as np
from bot.config import Config
from bot.model import BotModel
from bot.backtest import BacktestEngine

cfg = Config()

print("=== Loading model ===")
model = BotModel()
model.load(cfg.MODELS_DIR)
print(f"Model metrics from training: {model.metrics}")

print("\n=== Loading test data ===")
X = pd.read_parquet(f"{cfg.DATA_DIR}/training_features.parquet")
y = pd.read_parquet(f"{cfg.DATA_DIR}/training_labels.parquet")["label"]

# Use last 15% as out-of-sample (same as model test set)
n = len(X)
test_start = int(n * 0.85)
X_test = X.iloc[test_start:]
y_test = y.iloc[test_start:]
print(f"Test samples: {len(X_test)}")

# Get calibrated probabilities
probas = model.predict_calibrated(X_test)

backtest_data = pd.DataFrame({
    "prob_calibrated": probas,
    "label": y_test.values,
}, index=X_test.index)

print("\n=== Running Backtest ===")
engine = BacktestEngine(initial_capital=100.0)
results = engine.run(backtest_data)

print(f"\n{'='*50}")
print(f"BACKTEST RESULTS")
print(f"{'='*50}")
print(f"Total trades:        {results['total_trades']}")
print(f"Win rate:            {results['win_rate']:.2%}")
print(f"Final capital:       ${results['final_capital']:.2f}")
print(f"ROI:                 {results['roi']:.2%}")
print(f"Max drawdown:        {results['max_drawdown']:.2%}")
print(f"Profit factor:       {results['profit_factor']:.2f}")
print(f"Sharpe ratio:        {results['sharpe_ratio']:.2f}")

# Production readiness
print(f"\n=== Production Readiness ===")
checks = {
    "Win rate > 57%": results["win_rate"] > 0.57,
    "Profit factor > 1.15": results["profit_factor"] > 1.15,
    "Max drawdown < 10%": results["max_drawdown"] < 0.10,
    "Sharpe > 1.0": results["sharpe_ratio"] > 1.0,
    "Trades > 20": results["total_trades"] > 20,
}
for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {check}")
```

- [ ] **Step 2: Run backtest**

```bash
python scripts/run_backtest.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run_backtest.py
git commit -m "feat: backtest runner script with production readiness checks"
```

---

**End of Phase 1 plan.** Phase 2 (live trading engine, risk management, Polymarket integration) will be planned separately after Phase 1 results are validated.
