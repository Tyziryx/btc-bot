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
    # Raised from 0.93 → 0.97: captures ~5x more instant-arb opportunities.
    # Breakeven with real fees ($0.08 per $4 notional) is ≈ 0.978 at equal splits.
    MAX_COMBINED_COST: float = 0.97  # Max combined ask for INSTANT arb ($1 payout)
    LEG2_TIMEOUT_S: int = 120        # Abandon leg 2 search after 2 min
    LEG2_MAX_PRICE: float = 0.48     # Never pay more than this for leg 2

    # ── Entry guards (moved from hardcoded literals in arb_trader.py) ───────
    LEG1_MAX_PRICE: float = 0.60         # Don't enter leg 1 above this price
    WINDOW_EXPIRY_ABANDON_S: int = 30    # Abandon open leg if < Ns remain in window
    PRE_SUBSCRIBE_S: int = 30            # Pre-fetch next window this many seconds early

    # ── Timing ─────────────────────────────────────────────────────────────
    WINDOW_SECONDS: int = 900        # 15-min windows
    MIN_WINDOW_REMAINING_S: int = 60 # Don't open leg 1 in last 60s

    # ── Risk ───────────────────────────────────────────────────────────────
    BET_SIZE: float = 2.0            # $ per leg (paper)
    MAX_TRADES_PER_WINDOW: int = 1   # One arb attempt per 15-min window
    MAX_OPEN_LEGS: int = 1           # Only one open leg at a time

    # ── Fees ───────────────────────────────────────────────────────────────
    # Applied on TOTAL NOTIONAL (both legs), not on profit.
    # Real cost: BET_SIZE * 2 * 0.02 = $0.08 per arb for default $2 bets.
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
