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
    CONFIDENCE_THRESHOLD: float = 55.0   # Min score to enter leg 1
    TFI_WEIGHT: float = 0.55             # Weight of Trade Flow Imbalance in score
    OBI_WEIGHT: float = 0.45             # Weight of Order Book Imbalance in score
    OBI_DEPTH: int = 5                   # Top N levels to compute OBI

    # ── Legging parameters ─────────────────────────────────────────────────
    MAX_COMBINED_COST: float = 0.96  # Catch more arbs (was 0.95 — missed 0.950/0.960 opps)
    MIN_ARB_NET_USD: float = 0.05    # Skip arb if estimated net profit < $0.05 after fees
    LEG2_TIMEOUT_S: int = 300        # 5 min to find leg2 (was 2 min)
    LEG2_MAX_PRICE: float = 0.65     # Max price for leg2 (real guard is combined < 0.96)

    # ── Entry guards ────────────────────────────────────────────────────────
    LEG1_MAX_PRICE: float = 0.70         # Data: 0.55-0.65 zone = 77% completion (was 0.60)
    MIN_ENTRY_PRICE: float = 0.50        # Data: 0.35-0.50 = 48-57% completion, bleeds -13.87 (was 0.35)
    WINDOW_EXPIRY_ABANDON_S: int = 30    # Abandon if < 30s remain and no leg2
    PRE_SUBSCRIBE_S: int = 30
    RECONNECT_COOLDOWN_S: int = 90       # Ignore signals for 90s after WS reconnect (fake TFI burst)

    # ── Option B: combined filter at leg1 entry ─────────────────────────────
    # Only enter leg1 if combined is already ≥ this value.
    # Logic: if combined=0.92, we only need a 4% move to complete the arb.
    # If combined=0.80, we need a 20% move — very unlikely.
    # Set to 0.0 to disable (allow any combined). Data: test 0.88 first.
    MIN_COMBINED_AT_ENTRY: float = 0.88  # Skip leg1 if combined < 0.88 (too far from arb)

    # ── Option A: pure arb mode ─────────────────────────────────────────────
    # If True, completely disables the directional/confidence path.
    # Bot only trades instant riskless arbs (combined < MAX_COMBINED_COST).
    PURE_ARB_ONLY: bool = False

    # ── Cross-window momentum ───────────────────────────────────────────────
    MOMENTUM_LOOKBACK: int = 3           # How many past windows to remember
    MOMENTUM_BOOST: float = 1.15         # Multiplier when momentum confirms
    MOMENTUM_PENALTY: float = 0.85       # Multiplier when momentum disagrees

    # ── Order Book Shock ────────────────────────────────────────────────────
    OB_SHOCK_HISTORY: int = 8            # Ticks to keep for rolling average
    OB_SHOCK_MIN_SCORE: int = 2          # Score ≥ this lowers confidence threshold
    OB_SHOCK_CONF_THRESHOLD: float = 55.0  # Effective threshold when shock detected

    # ── Stop-loss: prix immédiat ────────────────────────────────────────────
    # Si le token bid chute de plus de X% depuis l'entrée → abandon immédiat, sans délai.
    PRICE_STOP_LOSS_PCT: float = 0.80    # Coupe si token bid < entry × 0.80 (drop de 20%) — was 0.65/35%

    # ── Stop-loss: Binance OFI reversal ────────────────────────────────────
    # DISABLED: data shows combined dips (arb opportunities) are instantaneous
    # (1-2 ticks at 0.88-0.96 then back to 1.01). OFI stop was ejecting us at
    # t=274s avg, wasting 626s of remaining arb-catching window per trade.
    # The bot must STAY in position to catch these flash dips.
    BINANCE_OFI_STOP_ENABLED: bool = False
    BINANCE_OFI_STOP_LOSS: float = -0.35  # kept for reference, only used if ENABLED
    STOP_LOSS_MIN_ELAPSED_S: int = 30

    # ── ML Directional Mode ────────────────────────────────────────────────
    # When enabled, the bot uses the trained XGBoost v3 model to predict
    # direction at each window start. Stop-losses are disabled.
    # Entry only when: model confidence ≥ threshold AND token price ≤ max.
    # Win/lose resolves at window end (directional bet, not arb).
    ML_DIRECTIONAL_MODE: bool = True
    ML_CONFIDENCE_THRESHOLD: float = 0.54   # Model prob ≥ 0.54 (58% accuracy, +EV)
    ML_MAX_ENTRY_PRICE: float = 0.56         # Only enter if token ask ≤ 0.56 (market near 50/50)
    ML_BAD_HOURS: tuple = (2, 6, 10, 14, 16, 18)  # Skip these UTC hours (live data analysis)

    # ── Timing ─────────────────────────────────────────────────────────────
    WINDOW_SECONDS: int = 900
    MIN_WINDOW_REMAINING_S: int = 180

    # ── Risk ───────────────────────────────────────────────────────────────
    BET_SIZE: float = 2.0
    MAX_TRADES_PER_WINDOW: int = 1

    # ── Fees ───────────────────────────────────────────────────────────────
    POLYMARKET_FEE: float = 0.02

    # ── Binance lead-lag signal ─────────────────────────────────────────────
    # Polymarket typically lags Binance by 30-90s. Binance momentum acts as a
    # direction multiplier on the confidence score (not a separate weight).
    BINANCE_ENABLED: bool = True
    BINANCE_MOMENTUM_THRESHOLD: float = 0.001  # 0.1% 3m return to count as signal (was 0.002 — created blind zone)
    BINANCE_AGREE_BOOST: float = 1.25           # Score × 1.25 when Binance agrees
    BINANCE_DISAGREE_PENALTY: float = 0.65      # Score × 0.65 when Binance disagrees
    # Blocage dur à l'entrée : si BTC 1m return dépasse ce seuil CONTRE notre direction → skip
    BTC_HARD_BLOCK_MOMENTUM: float = 0.0025    # 0.25% en 1m = mouvement BTC fort, ne pas entrer

    # ── Directories ────────────────────────────────────────────────────────
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
