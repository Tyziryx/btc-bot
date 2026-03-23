from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ArbConfig:
    """Configuration for the legging arbitrage bot."""

    # Polling
    POLL_INTERVAL_S: float = 5.0
    OFI_WINDOW_S: int = 30          # 30-second sliding window (6 snapshots)

    # OFI thresholds
    OFI_THRESHOLD: float = 50.0     # Minimum |OFI| to trigger leg 1

    # Legging parameters
    MAX_COMBINED_COST: float = 0.93  # Max total for both legs ($1 payout)
    LEG2_TIMEOUT_S: int = 120        # Abandon leg 2 search after 2 min
    LEG2_MAX_PRICE: float = 0.48     # Never pay more than this for leg 2

    # Timing
    WINDOW_SECONDS: int = 900        # 15-min windows
    MIN_WINDOW_REMAINING_S: int = 60 # Don't open leg 1 in last 60s

    # Risk
    BET_SIZE: float = 2.0            # $ per leg (paper)
    MAX_TRADES_PER_WINDOW: int = 1   # One arb attempt per 15-min window
    MAX_OPEN_LEGS: int = 1           # Only one open leg at a time

    # Fees
    POLYMARKET_FEE: float = 0.02     # 2% on profit

    # Directories
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
