# Phase 1: Critical Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paper trading results reliable and interpretable by fixing risk management, adding real data feeds, improving logging, and adding model monitoring.

**Architecture:** All changes are to the existing paper_trader.py (risk/logging), polymarket.py (liquidity), a new drift_detector.py (monitoring), and build_training_data_v2.py (feature fix). Each task is independent and can be committed separately.

**Tech Stack:** Python 3.12, XGBoost, pandas, requests, websockets, systemd

---

## Chunk 1: Risk Management Fixes (Tasks 1.1, 1.3)

### Task 1.1: Fix daily stop loss to use start-of-day capital

**Files:**
- Modify: `bot/paper_trader.py:39-71` (init), `bot/paper_trader.py:282-296` (risk gates), `bot/paper_trader.py:595-600` (midnight reset)

- [ ] **Step 1: Add daily_start_capital to __init__**

In `bot/paper_trader.py`, add to `__init__` after `self.daily_pnl = 0.0`:
```python
self.daily_start_capital = capital
```

- [ ] **Step 2: Fix _check_risk_gates to use daily_start_capital**

Replace line 289:
```python
# OLD: if self.daily_pnl <= -(self.capital * self.config.DAILY_STOP_LOSS):
# NEW:
if self.daily_pnl <= -(self.daily_start_capital * self.config.DAILY_STOP_LOSS):
    return "daily_stop_loss (%.2f / limit %.2f)" % (
        self.daily_pnl, -(self.daily_start_capital * self.config.DAILY_STOP_LOSS))
```

- [ ] **Step 3: Reset daily_start_capital at midnight UTC**

In the midnight reset block (~line 597), add:
```python
if ts_dt.hour == 0 and ts_dt.minute < 5:
    self.daily_pnl = 0.0
    self.daily_start_capital = self.capital
```

- [ ] **Step 4: Verify logic**

Run: `python -c "from bot.paper_trader import PaperTrader; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add bot/paper_trader.py
git commit -m "fix: daily stop loss uses start-of-day capital"
```

---

### Task 1.3: Add trade limits and cooldown after loss

**Files:**
- Modify: `bot/paper_trader.py:39-71` (init), `bot/paper_trader.py:282-296` (risk gates), `bot/config.py` (new params)

- [ ] **Step 1: Add config parameters**

In `bot/config.py`, add after `CIRCUIT_BREAKER_PAUSE_MIN`:
```python
MAX_TRADES_PER_DAY: int = 50
MAX_TRADES_PER_HOUR: int = 8
COOLDOWN_AFTER_LOSS: int = 1  # Skip N windows after a loss
```

- [ ] **Step 2: Add state tracking to __init__**

In `bot/paper_trader.py` `__init__`, add:
```python
self.daily_trades_count = 0
self.hourly_trades = []  # list of timestamps
self.cooldown_until_window = 0  # window_id to skip until
```

- [ ] **Step 3: Add trade limit checks to _check_risk_gates**

Add to `_check_risk_gates()` before the return None:
```python
# Trade frequency limits
if self.daily_trades_count >= self.config.MAX_TRADES_PER_DAY:
    return "max_daily_trades (%d)" % self.daily_trades_count

now_ts = time.time()
recent_hour = [t for t in self.hourly_trades if t > now_ts - 3600]
self.hourly_trades = recent_hour
if len(recent_hour) >= self.config.MAX_TRADES_PER_HOUR:
    return "max_hourly_trades (%d)" % len(recent_hour)
```

- [ ] **Step 4: Add cooldown check to _on_prediction**

In `_on_prediction()`, add after `window_id = self._window_id(ts_ms)`:
```python
if window_id <= self.cooldown_until_window:
    self._log("SKIP window=%d | cooldown after loss" % window_id)
    self.trades_skipped += 1
    return
```

- [ ] **Step 5: Set cooldown on loss in _resolve_prediction**

In `_resolve_prediction()`, in the `else` (loss) block, add:
```python
self.cooldown_until_window = pred["window_id"] + 300 * self.config.COOLDOWN_AFTER_LOSS
```

- [ ] **Step 6: Increment counters on trade**

In `_resolve_prediction()`, after `self.trades_taken += 1`:
```python
self.daily_trades_count += 1
self.hourly_trades.append(time.time())
```

- [ ] **Step 7: Reset daily counter at midnight**

In midnight reset block:
```python
self.daily_trades_count = 0
```

- [ ] **Step 8: Commit**

```bash
git add bot/paper_trader.py bot/config.py
git commit -m "feat: trade limits (50/day, 8/hour) + cooldown after loss"
```

---

## Chunk 2: Logging and Monitoring (Tasks 1.4, 1.6)

### Task 1.4: Switch to JSONL append-only logging

**Files:**
- Modify: `bot/paper_trader.py:455-477` (_save_trade)
- Modify: `status.sh:20-99` (read JSONL)

- [ ] **Step 1: Change log path extension**

In `__init__`, change:
```python
self.log_path = os.path.join(self.config.DATA_DIR, "paper_trades.jsonl")
```

- [ ] **Step 2: Replace _save_trade with JSONL append**

Replace the entire `_save_trade` method:
```python
def _save_trade(self, trade: dict):
    """Append trade as single JSONL line."""
    clean = {}
    for k, v in trade.items():
        if isinstance(v, (np.floating, np.float32, np.float64)):
            clean[k] = float(v)
        elif isinstance(v, (np.integer, np.int32, np.int64)):
            clean[k] = int(v)
        elif isinstance(v, np.bool_):
            clean[k] = bool(v)
        else:
            clean[k] = v
    with open(self.log_path, "a") as f:
        f.write(json.dumps(clean) + "\n")
```

- [ ] **Step 3: Update status.sh to read JSONL**

Replace the Python inline in `status.sh` to read JSONL:
```python
trades = []
with open('data/paper_trades.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            trades.append(json.loads(line))
```

Also update the file existence check:
```bash
if [ -f data/paper_trades.jsonl ]; then
```

- [ ] **Step 4: Commit**

```bash
git add bot/paper_trader.py status.sh
git commit -m "refactor: switch to JSONL append-only trade logging"
```

---

### Task 1.6: Add drift detector

**Files:**
- Create: `bot/drift_detector.py`
- Modify: `bot/paper_trader.py` (integrate)

- [ ] **Step 1: Create bot/drift_detector.py**

```python
"""
Model drift detector - monitors rolling win rate and alerts when
the model's predictions no longer match reality.
"""

class DriftDetector:
    def __init__(self, window: int = 100, critical_threshold: float = 0.48,
                 warning_threshold: float = 0.52):
        self.window = window
        self.critical_threshold = critical_threshold
        self.warning_threshold = warning_threshold
        self.results: list[bool] = []

    def update(self, won: bool):
        self.results.append(won)
        if len(self.results) > self.window * 2:
            self.results = self.results[-self.window * 2:]

    def check(self) -> dict:
        if len(self.results) < 30:
            return {"status": "warming_up", "n": len(self.results),
                    "win_rate": 0.0, "should_stop": False}

        recent = self.results[-self.window:]
        n = len(recent)
        wins = sum(recent)
        wr = wins / n

        status = "ok"
        if wr < self.critical_threshold:
            status = "CRITICAL"
        elif wr < self.warning_threshold:
            status = "WARNING"

        return {
            "status": status,
            "win_rate": round(wr, 4),
            "n": n,
            "should_stop": status == "CRITICAL",
            "should_retrain": status in ("CRITICAL", "WARNING"),
        }

    def summary(self) -> str:
        info = self.check()
        if info["status"] == "warming_up":
            return "DRIFT: warming up (%d/%d trades)" % (info["n"], self.window)
        return "DRIFT: %s | WR=%.1f%% (%d trades)" % (
            info["status"], info["win_rate"] * 100, info["n"])
```

- [ ] **Step 2: Integrate into paper_trader.py**

Add import at top:
```python
from bot.drift_detector import DriftDetector
```

Add to `__init__`:
```python
self.drift = DriftDetector(window=100)
```

In `_resolve_prediction()`, after `self.trades.append(trade)`:
```python
self.drift.update(won)
drift_info = self.drift.check()
if drift_info.get("should_stop"):
    self._log("DRIFT CRITICAL: WR=%.1f%% on %d trades - STOPPING" % (
        drift_info["win_rate"] * 100, drift_info["n"]))
    self.paused_until = time.time() + 3600  # Pause 1 hour
```

In the dashboard print (every 10 trades), add:
```python
print("  Drift: %s" % self.drift.summary())
```

- [ ] **Step 3: Commit**

```bash
git add bot/drift_detector.py bot/paper_trader.py
git commit -m "feat: drift detector monitors rolling win rate"
```

---

## Chunk 3: Real Data Integration (Tasks 1.2, 1.5)

### Task 1.2: Integrate real funding rate from Binance Futures

**Files:**
- Modify: `bot/paper_trader.py` (fetch + use in features)

- [ ] **Step 1: Add funding rate fetcher method**

Add to PaperTrader class:
```python
def _fetch_funding_rate(self) -> float:
    """Fetch latest funding rate from Binance Futures API."""
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": "BTCUSDT", "limit": 1},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0]["fundingRate"])
    except Exception as e:
        self._log("WARNING: Could not fetch funding rate: %s" % e)
    return 0.0
```

- [ ] **Step 2: Add state for funding rate**

In `__init__`, add:
```python
self.current_funding_rate = 0.0
self.last_funding_fetch = 0.0
```

- [ ] **Step 3: Fetch periodically in run loop**

In the `run()` method, inside the window transition block (after midnight reset), add:
```python
# Refresh funding rate every 4 hours
if time.time() - self.last_funding_fetch > 4 * 3600:
    self.current_funding_rate = self._fetch_funding_rate()
    self.last_funding_fetch = time.time()
    self._log("Funding rate: %.6f" % self.current_funding_rate)
```

- [ ] **Step 4: Use in feature computation**

In `_compute_v2_features()`, replace line 256:
```python
# OLD: feat["funding_rate"] = 0.0
feat["funding_rate"] = self.current_funding_rate
```

Note: need to pass `self` context - the method already has access via `self`.

- [ ] **Step 5: Fetch on startup**

In `run()`, after `_fetch_recent_candles()`:
```python
self.current_funding_rate = self._fetch_funding_rate()
self.last_funding_fetch = time.time()
self._log("Funding rate: %.6f" % self.current_funding_rate)
```

- [ ] **Step 6: Commit**

```bash
git add bot/paper_trader.py
git commit -m "feat: fetch real Binance funding rate every 4h"
```

---

### Task 1.5: Add Polymarket liquidity check

**Files:**
- Modify: `bot/polymarket.py` (add function)
- Modify: `bot/paper_trader.py` (use in prediction)

- [ ] **Step 1: Add check_liquidity to polymarket.py**

Add after `get_best_bid()`:
```python
def check_liquidity(token_id: str, max_spread: float = 0.03,
                    min_depth: float = 20.0) -> dict:
    """Check if a token has enough liquidity to trade.

    Returns dict with 'ok' bool, 'spread', 'depth', 'reason'.
    """
    book = get_orderbook(token_id)
    bids = book.get("bids", [])
    asks = book.get("asks", [])

    if not bids or not asks:
        return {"ok": False, "spread": 1.0, "depth": 0.0,
                "reason": "empty_orderbook"}

    best_bid = float(bids[0]["price"])
    best_ask = float(asks[0]["price"])
    spread = best_ask - best_bid

    # Calculate depth (total $ within 2 cents of best)
    bid_depth = sum(
        float(b["price"]) * float(b["size"])
        for b in bids[:5]
    )
    ask_depth = sum(
        float(a["price"]) * float(a["size"])
        for a in asks[:5]
    )
    depth = min(bid_depth, ask_depth)

    if spread > max_spread:
        return {"ok": False, "spread": spread, "depth": depth,
                "reason": "spread_too_wide (%.3f > %.3f)" % (spread, max_spread)}

    if depth < min_depth:
        return {"ok": False, "spread": spread, "depth": depth,
                "reason": "depth_too_low ($%.0f < $%.0f)" % (depth, min_depth)}

    return {"ok": True, "spread": spread, "depth": depth, "reason": "pass"}
```

- [ ] **Step 2: Integrate into paper_trader.py _on_prediction**

In `_on_prediction()`, after fetching market price, add liquidity check:
```python
# Check liquidity
try:
    from bot.polymarket import check_liquidity
    token_id = market.up_token_id if direction == "UP" else market.down_token_id
    liq = check_liquidity(token_id)
    if not liq["ok"]:
        self._log("SKIP window=%d | liquidity: %s" % (window_id, liq["reason"]))
        self.trades_skipped += 1
        return
    self._log("LIQUIDITY spread=%.3f depth=$%.0f" % (liq["spread"], liq["depth"]))
except Exception:
    pass  # Don't block trading if liquidity check fails
```

- [ ] **Step 3: Commit**

```bash
git add bot/polymarket.py bot/paper_trader.py
git commit -m "feat: check Polymarket liquidity before trading"
```

---

## Chunk 4: Feature Fix (Task 1.7)

### Task 1.7: Normalize prev1_volume

**Files:**
- Modify: `scripts/build_training_data_v2.py:148`
- Modify: `bot/paper_trader.py:228`

- [ ] **Step 1: Fix in build_training_data_v2.py**

Replace line 148:
```python
# OLD: feat["prev1_volume"] = pw["volume"]
# NEW: Normalize by average volume of last 10 windows
vol_window = []
for j in range(1, 11):
    prev_check = window_start - pd.Timedelta(minutes=5 * j)
    if prev_check in df_5min.index:
        vol_window.append(df_5min.loc[prev_check, "volume"])
avg_vol = np.mean(vol_window) if vol_window else 1.0
feat["prev1_volume"] = pw["volume"] / (avg_vol + 1e-10)
```

- [ ] **Step 2: Fix in paper_trader.py**

Replace the prev1_volume line in `_compute_v2_features()`:
```python
# Normalize volume by recent average
if len(self.prev_windows) >= 2:
    avg_vol = np.mean([w["volume"] for w in self.prev_windows[-10:]]) or 1.0
    feat["prev1_volume"] = pw["volume"] / (avg_vol + 1e-10)
else:
    feat["prev1_volume"] = 1.0
```

- [ ] **Step 3: Rebuild training data**

Run: `python scripts/build_training_data_v2.py`

- [ ] **Step 4: Retrain model**

Run: `python scripts/train_model_v2.py`

- [ ] **Step 5: Commit**

```bash
git add scripts/build_training_data_v2.py bot/paper_trader.py models_v2/
git commit -m "fix: normalize prev1_volume by 10-window average"
```

---

## Execution Order

1. Task 1.1 (daily stop loss) + Task 1.3 (trade limits) - risk management
2. Task 1.4 (JSONL logging) + Task 1.6 (drift detector) - monitoring
3. Task 1.2 (funding rate) + Task 1.5 (liquidity check) - real data
4. Task 1.7 (normalize prev1_volume) - feature fix + retrain

After all tasks: push to GitHub, update server, reset trades, validate.

## Success Criteria

- Paper trader runs 2+ weeks with no crashes
- Drift detector never reaches CRITICAL
- Win rate > 52% on 300+ trades with real Polymarket prices
- All trades logged in JSONL with liquidity and funding data
