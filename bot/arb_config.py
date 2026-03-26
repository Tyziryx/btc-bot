from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ArbConfig:
    """Configuration for the legging arbitrage bot — Pro-Enhanced."""

    # ── Polling ────────────────────────────────────────────────────────────
    POLL_INTERVAL_S: float = 5.0
    OFI_WINDOW_S: int = 30           # Sliding window for TFI accumulation (30s = 6 ticks)

    # ── Signal: Trade Flow Imbalance (TFI) ─────────────────────────────────
    # TFI is raw dollar-volume of trade executions. This value is used as the
    # "saturation point" for normalization — TFI >= threshold → 100% weight.
    OFI_THRESHOLD: float = 50.0      # kept for backward compat (= TFI sat. reference)

    # ── Signal: Confidence Score ────────────────────────────────────────────
    # Composite [0-100] from TFI + OBI (+ Binance if enabled).
    CONFIDENCE_THRESHOLD: float = 65.0   # Min score to enter leg 1
    TFI_WEIGHT: float = 0.55             # Weight of Trade Flow Imbalance in score
    OBI_WEIGHT: float = 0.45             # Weight of Order Book Imbalance in score
    OBI_DEPTH: int = 5                   # Top N levels to compute OBI

    # ── Legging parameters ─────────────────────────────────────────────────
    MAX_COMBINED_COST: float = 0.95  # Tighter than before (was 0.97) — better margin
    LEG2_TIMEOUT_S: int = 300        # 5 min to find leg2 (was 2 min)
    LEG2_MAX_PRICE: float = 0.50     # Max price for leg2

    # ── Entry guards ────────────────────────────────────────────────────────
    LEG1_MAX_PRICE: float = 0.70         # Don't enter leg1 above this price
    WINDOW_EXPIRY_ABANDON_S: int = 30    # Abandon if < 30s remain and no leg2
    PRE_SUBSCRIBE_S: int = 30

    # ── Stop-loss: Binance OFI reversal ────────────────────────────────────
    # If Binance OFI strongly reverses against our leg1 direction, abandon early.
    BINANCE_OFI_STOP_LOSS: float = -0.35  # e.g. holding UP + Binance OFI < -0.35 → cut
    STOP_LOSS_MIN_ELAPSED_S: int = 60     # Don't stop-loss in first 60s (signal noise)

    # ── Timing ─────────────────────────────────────────────────────────────
    WINDOW_SECONDS: int = 900
    MIN_WINDOW_REMAINING_S: int = 60

    # ── Risk ───────────────────────────────────────────────────────────────
    BET_SIZE: float = 2.0
    MAX_TRADES_PER_WINDOW: int = 1

    # ── Fees ───────────────────────────────────────────────────────────────
    POLYMARKET_FEE: float = 0.02

    # ── Binance lead-lag signal ─────────────────────────────────────────────
    # Polymarket typically lags Binance by 30-90s. Binance momentum acts as a
    # direction multiplier on the confidence score (not a separate weight).
    BINANCE_ENABLED: bool = True
    BINANCE_MOMENTUM_THRESHOLD: float = 0.002  # 0.2% 3m return to count as signal
    BINANCE_AGREE_BOOST: float = 1.25           # Score × 1.25 when Binance agrees
    BINANCE_DISAGREE_PENALTY: float = 0.65      # Score × 0.65 when Binance disagrees

    # ── Directories ────────────────────────────────────────────────────────
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
