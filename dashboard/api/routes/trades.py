from fastapi import APIRouter
from ..services.trade_reader import read_trades, compute_stats

router = APIRouter(prefix="/api")


@router.get("/trades")
def get_trades(limit: int = 50):
    """Get recent trades."""
    trades = read_trades()
    return {"trades": trades[-limit:], "total": len(trades)}


@router.get("/stats")
def get_stats():
    """Get computed stats."""
    trades = read_trades()
    return compute_stats(trades)
