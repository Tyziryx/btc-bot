import json
import math
import os
import threading
import time

# ── Stats cache ──────────────────────────────────────────────────────────────
_stats_cache: dict | None = None
_stats_cache_ts: float = 0.0
_CACHE_TTL: float = 10.0
_stats_cache_lock = threading.Lock()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


def _detect_mode() -> str:
    """Detect whether we're running arb or paper trader based on which file exists and is newer."""
    arb_path = os.path.join(DATA_DIR, "arb_trades.jsonl")
    paper_path = os.path.join(DATA_DIR, "paper_trades.jsonl")
    arb_exists = os.path.exists(arb_path)
    paper_exists = os.path.exists(paper_path)

    if arb_exists and paper_exists:
        return "arb" if os.path.getmtime(arb_path) > os.path.getmtime(paper_path) else "paper"
    if arb_exists:
        return "arb"
    return "paper"


def read_trades() -> list[dict]:
    """Read all trades from JSONL file."""
    mode = _detect_mode()
    if mode == "arb":
        path = os.path.join(DATA_DIR, "arb_trades.jsonl")
    else:
        path = os.path.join(DATA_DIR, "paper_trades.jsonl")
        if not os.path.exists(path):
            path = os.path.join(DATA_DIR, "paper_trades.json")

    trades = []
    if not os.path.exists(path):
        return trades

    if path.endswith(".json"):
        with open(path, "r") as f:
            try:
                trades = json.load(f)
            except json.JSONDecodeError:
                pass
    else:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return trades


def _sharpe(returns: list[float]) -> float:
    """Sharpe ratio (annualised by √n — trade-level, not calendar)."""
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    return round(mean / std * math.sqrt(n), 2) if std > 0 else 0.0


def _sortino(returns: list[float]) -> float:
    """Sortino ratio — downside semi-deviation over full return series."""
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    # Sum of squared negative returns over full n (standard semi-deviation)
    downside_sq_sum = sum(min(r, 0) ** 2 for r in returns)
    if downside_sq_sum == 0:
        return 0.0
    downside_std = math.sqrt(downside_sq_sum / n)
    return round(mean / downside_std * math.sqrt(n), 2)


def _win_rate_by_confidence(trades: list[dict]) -> dict:
    """Win rate grouped by entry_confidence bucket (directional trades only)."""
    buckets: dict[str, dict] = {
        "65_70": {"wins": 0, "total": 0},
        "70_80": {"wins": 0, "total": 0},
        "80_plus": {"wins": 0, "total": 0},
    }
    for t in trades:
        if t.get("leg2_side"):          # skip instant arbs — no directional signal
            continue
        conf = t.get("entry_confidence") or 0
        status = t.get("status", "")
        is_win = status == "win"

        if 65 <= conf < 70:
            key = "65_70"
        elif 70 <= conf < 80:
            key = "70_80"
        elif conf >= 80:
            key = "80_plus"
        else:
            continue

        buckets[key]["total"] += 1
        if is_win:
            buckets[key]["wins"] += 1

    result: dict = {}
    for key, data in buckets.items():
        total = data["total"]
        result[key] = {
            "win_rate": round(data["wins"] / total * 100, 1) if total > 0 else 0.0,
            "total": total,
            "wins": data["wins"],
        }
    return result


def compute_stats(trades: list[dict]) -> dict:
    """Compute dashboard stats from trades list (arb or paper format)."""
    if not trades:
        return {
            "mode": "arb",
            "capital": 100.0, "initial_capital": 100.0, "roi": 0.0,
            "total_pnl": 0.0, "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0,
            "completed": 0, "abandoned": 0,
            "first_trade": None, "last_trade": None,
            "capital_curve": [],
        }

    # Detect format: arb trades have "status" field, paper trades have "won"
    is_arb = "status" in trades[0]

    if is_arb:
        return _compute_arb_stats(trades)
    else:
        return _compute_paper_stats(trades)


def _compute_arb_stats(trades: list[dict]) -> dict:
    """Stats for arb trades."""
    capital = trades[-1].get("capital_after", 100.0)
    initial = trades[0].get("capital_after", 100.0) - trades[0].get("profit", 0)

    completed = [t for t in trades if t.get("status") == "complete"]
    abandoned = [t for t in trades if t.get("status") == "abandoned"]

    profits = [t["profit"] for t in completed if t.get("profit", 0) > 0]
    losses_list = [t["profit"] for t in completed if t.get("profit", 0) <= 0]

    total_pnl = sum(t.get("profit", 0) for t in trades)
    avg_win = sum(profits) / len(profits) if profits else 0
    avg_loss = sum(losses_list) / len(losses_list) if losses_list else 0
    gross_profit = sum(profits)
    gross_loss = abs(sum(losses_list))

    # Max drawdown
    peak = initial
    max_dd = 0
    for t in trades:
        cap = t.get("capital_after", initial)
        peak = max(peak, cap)
        dd = (peak - cap) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    total_decided = len(completed)
    win_count = len(profits)

    # ── New quant metrics ─────────────────────────────────────────────
    all_returns = [t.get("profit", 0) for t in completed]
    sharpe = _sharpe(all_returns)
    sortino = _sortino(all_returns)

    # Calmar = ROI / max_drawdown
    roi_pct = round((capital / initial - 1) * 100, 2) if initial > 0 else 0.0
    calmar = round(roi_pct / (max_dd * 100), 2) if max_dd > 0 else 0.0

    # Win rate by confidence bucket (directional trades only)
    win_by_conf = _win_rate_by_confidence(trades)

    # Drawdown duration: count consecutive losing trades
    max_dd_trades = 0
    cur_dd = 0
    for t in trades:
        if t.get("profit", 0) < 0:
            cur_dd += 1
            max_dd_trades = max(max_dd_trades, cur_dd)
        else:
            cur_dd = 0

    return {
        "mode": "arb",
        "capital": round(capital, 2),
        "initial_capital": round(initial, 2),
        "roi": round((capital / initial - 1) * 100, 2) if initial > 0 else 0,
        "total_pnl": round(total_pnl, 4),
        "total_trades": len(trades),
        "completed": len(completed),
        "abandoned": len(abandoned),
        "wins": win_count,
        "losses": len(losses_list),
        "win_rate": round(win_count / total_decided * 100, 1) if total_decided > 0 else 0.0,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "max_drawdown": round(max_dd * 100, 1),
        "first_trade": trades[0].get("timestamp"),
        "last_trade": trades[-1].get("timestamp"),
        "capital_curve": [
            {"ts": t.get("timestamp"), "capital": t.get("capital_after", 100)}
            for t in trades
        ],
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "win_by_conf": win_by_conf,
        "max_dd_trades": max_dd_trades,
    }


def _compute_paper_stats(trades: list[dict]) -> dict:
    """Stats for paper trades (backward compat)."""
    capital = trades[-1].get("capital_after", 100.0)
    initial = trades[0].get("capital_before", 100.0)
    real_trades = [t for t in trades if t.get("won") is not None]
    wins = [t for t in real_trades if t.get("won")]
    losses = [t for t in real_trades if not t.get("won")]

    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    peak = initial
    max_dd = 0
    for t in trades:
        cap = t.get("capital_after", initial)
        peak = max(peak, cap)
        dd = (peak - cap) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return {
        "mode": "paper",
        "capital": round(capital, 2),
        "initial_capital": round(initial, 2),
        "roi": round((capital / initial - 1) * 100, 2),
        "total_pnl": round(sum(t["pnl"] for t in trades), 2),
        "total_trades": len(real_trades),
        "completed": len(real_trades),
        "abandoned": 0,
        "draws": len(trades) - len(real_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(real_trades) * 100, 1) if real_trades else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "max_drawdown": round(max_dd * 100, 1),
        "first_trade": trades[0].get("timestamp"),
        "last_trade": trades[-1].get("timestamp"),
        "capital_curve": [
            {"ts": t.get("timestamp"), "capital": t.get("capital_after", 100)}
            for t in trades
        ],
    }


def get_stats_cached() -> dict:
    """Return stats with 10-second TTL cache to avoid recomputing on every request."""
    global _stats_cache, _stats_cache_ts
    with _stats_cache_lock:
        if _stats_cache is not None and time.time() - _stats_cache_ts < _CACHE_TTL:
            return _stats_cache
        _stats_cache = compute_stats(read_trades())
        _stats_cache_ts = time.time()
        return _stats_cache
