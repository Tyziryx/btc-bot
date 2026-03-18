import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
TRADES_FILE = os.path.join(DATA_DIR, "paper_trades.jsonl")


def read_trades() -> list[dict]:
    """Read all trades from JSONL file."""
    trades = []
    if not os.path.exists(TRADES_FILE):
        return trades
    with open(TRADES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return trades


def compute_stats(trades: list[dict]) -> dict:
    """Compute dashboard stats from trades list."""
    if not trades:
        return {
            "capital": 100.0, "initial_capital": 100.0, "roi": 0.0,
            "total_pnl": 0.0, "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0,
            "first_trade": None, "last_trade": None,
            "hourly": {}, "capital_curve": [],
        }

    capital = trades[-1].get("capital_after", 100.0)
    initial = trades[0].get("capital_before", 100.0)
    wins = [t for t in trades if t.get("won")]
    losses = [t for t in trades if not t.get("won")]

    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    # Max drawdown from capital curve
    peak = initial
    max_dd = 0
    for t in trades:
        cap = t.get("capital_after", initial)
        peak = max(peak, cap)
        dd = (peak - cap) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Hourly breakdown
    hourly = {}
    for t in trades:
        ts = t.get("timestamp", "")
        if "T" in ts:
            hour = int(ts.split("T")[1][:2])
            if hour not in hourly:
                hourly[hour] = {"trades": 0, "wins": 0, "pnl": 0.0}
            hourly[hour]["trades"] += 1
            if t.get("won"):
                hourly[hour]["wins"] += 1
            hourly[hour]["pnl"] += t.get("pnl", 0)

    return {
        "capital": round(capital, 2),
        "initial_capital": round(initial, 2),
        "roi": round((capital / initial - 1) * 100, 2),
        "total_pnl": round(sum(t["pnl"] for t in trades), 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "max_drawdown": round(max_dd * 100, 1),
        "first_trade": trades[0].get("timestamp"),
        "last_trade": trades[-1].get("timestamp"),
        "hourly": hourly,
        "capital_curve": [
            {"ts": t.get("timestamp"), "capital": t.get("capital_after", 100)}
            for t in trades
        ],
    }
