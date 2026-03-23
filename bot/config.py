import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Data sources
    SYMBOL: str = "BTCUSDT"
    KLINE_INTERVAL: str = "1m"
    WINDOW_SECONDS: int = 900

    # Directories
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
    MODELS_DIR: str = field(default_factory=lambda: os.getenv("MODELS_DIR", "models"))

    # Risk management
    MIN_BET: float = 2.0
    MAX_BET: float = 40.0
    MAX_BET_FRACTION: float = 0.02
    DAILY_STOP_LOSS: float = 0.12
    MAX_DRAWDOWN: float = 0.15
    MIN_CONFIDENCE: float = 0.12
    MIN_EDGE: float = 0.03
    MAX_ENTRY_PRICE: float = 0.58  # Skip if CLOB already repriced above this
    CIRCUIT_BREAKER_LOSSES: int = 4
    CIRCUIT_BREAKER_PAUSE_MIN: int = 30
    MAX_TRADES_PER_DAY: int = 50
    MAX_TRADES_PER_HOUR: int = 8
    COOLDOWN_AFTER_LOSS: int = 2  # Skip N windows (x15min) after a loss
    MIN_RANGE_15M: float = 0.002  # Min 15-min range to trade (volatility gate)
    MIN_RV_RATIO: float = 0.5     # Min rv_ratio to trade
    MIN_MOMENTUM: float = 0.003   # 0.3% minimum 1h return to trigger
    MIN_VOL_RATIO: float = 0.8    # Volume confirmation threshold
    WARMUP_CANDLES: int = 1000    # Candles loaded at startup (for Hurst 1000)

    # Binance
    BINANCE_DATA_BASE: str = "https://data.binance.vision/data/spot/monthly/klines"
    BINANCE_FUTURES_BASE: str = "https://fapi.binance.com"

    # Polymarket
    POLYMARKET_PRIVATE_KEY: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", "")
    )
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"

    # Optional lowercase aliases for constructor convenience
    data_dir: str = field(default=None, repr=False)
    models_dir: str = field(default=None, repr=False)

    def __post_init__(self):
        if self.data_dir is not None:
            self.DATA_DIR = self.data_dir
        if self.models_dir is not None:
            self.MODELS_DIR = self.models_dir
        # Sync aliases
        self.data_dir = self.DATA_DIR
        self.models_dir = self.MODELS_DIR

    def ensure_dirs(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)
        os.makedirs(self.MODELS_DIR, exist_ok=True)
