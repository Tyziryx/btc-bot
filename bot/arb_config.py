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

    # ── Instant arb ────────────────────────────────────────────────────────
    # If combined ask < this, buy both sides immediately (guaranteed profit).
    MAX_COMBINED_COST: float = 0.97  # Max combined ask for instant arb ($1 payout)

    # ── Directional entry ───────────────────────────────────────────────────
    # When confidence > threshold, buy the predicted side and hold to resolution.
    MAX_ENTRY_PRICE: float = 0.65        # Don't pay more than this for a directional bet
    MIN_WINDOW_REMAINING_S: int = 120    # Don't open position in last 2 min of window
    PRE_SUBSCRIBE_S: int = 30            # Pre-fetch next window this many seconds early

    # ── Timing ─────────────────────────────────────────────────────────────
    WINDOW_SECONDS: int = 900        # 15-min windows

    # ── Risk ───────────────────────────────────────────────────────────────
    BET_SIZE: float = 2.0            # $ per position
    MAX_TRADES_PER_WINDOW: int = 1   # One position per 15-min window

    # ── Fees ───────────────────────────────────────────────────────────────
    POLYMARKET_FEE: float = 0.02     # 2% on notional (instant arb) or on profit (directional)

    # ── Binance lead-lag signal ─────────────────────────────────────────────
    # Polymarket typically lags Binance by 30-90s. Binance momentum acts as a
    # direction multiplier on the confidence score (not a separate weight).
    BINANCE_ENABLED: bool = True
    BINANCE_MOMENTUM_THRESHOLD: float = 0.002  # 0.2% 3m return to count as signal
    BINANCE_AGREE_BOOST: float = 1.25           # Score × 1.25 when Binance agrees
    BINANCE_DISAGREE_PENALTY: float = 0.65      # Score × 0.65 when Binance disagrees

    # ── Directories ────────────────────────────────────────────────────────
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
