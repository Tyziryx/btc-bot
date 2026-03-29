from fastapi import APIRouter
from ..services.trade_reader import read_trades, compute_stats, get_stats_cached

router = APIRouter(prefix="/api")


@router.get("/trades")
def get_trades(limit: int = 50):
    """Get recent trades."""
    trades = read_trades()
    return {"trades": trades[-limit:], "total": len(trades)}


@router.get("/stats")
def get_stats():
    return get_stats_cached()
