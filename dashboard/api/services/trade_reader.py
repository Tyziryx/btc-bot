import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


def read_trades() -> list[dict]:
    """Read all trades from JSONL file, falling back to JSON."""
    trades = []
    jsonl_path = os.path.join(DATA_DIR, "paper_trades.jsonl")
    json_path = os.path.join(DATA_DIR, "paper_trades.json")

    if os.path.exists(jsonl_path):
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    elif os.path.exists(json_path):
        with open(json_path, "r") as f:
            try:
                trades = json.load(f)
            except json.JSONDecodeError:
                pass
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
            "capital_curve": [],
        }

    capital = trades[-1].get("capital_after", 100.0)
    initial = trades[0].get("capital_before", 100.0)
    # Exclude draws (won=None) from W/L stats
    real_trades = [t for t in trades if t.get("won") is not None]
    wins = [t for t in real_trades if t.get("won")]
    losses = [t for t in real_trades if not t.get("won")]

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

    return {
        "capital": round(capital, 2),
        "initial_capital": round(initial, 2),
        "roi": round((capital / initial - 1) * 100, 2),
        "total_pnl": round(sum(t["pnl"] for t in trades), 2),
        "total_trades": len(real_trades),
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
