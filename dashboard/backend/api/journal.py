"""Dashboard API — Trade journal: full trade history + per-strategy stats."""

import sys
from pathlib import Path

from fastapi import APIRouter, Query

BASE_DIR = Path(__file__).parent.parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

router = APIRouter()


def _get_journal():
    try:
        from trading_agents.trade_journal import get_all, get_stats
        return get_all, get_stats
    except Exception:
        return None, None


@router.get("/journal/trades")
def get_trades(
    limit: int = Query(default=200, le=1000),
    source: str = Query(default=""),
    symbol: str = Query(default=""),
    outcome: str = Query(default=""),
):
    get_all, _ = _get_journal()
    if get_all is None:
        return {"trades": [], "error": "Journal module not available"}

    trades = get_all(limit=limit)

    if source:
        trades = [t for t in trades if t.get("source", "").upper() == source.upper()]
    if symbol:
        trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]
    if outcome:
        trades = [t for t in trades if t.get("outcome", "").upper() == outcome.upper()]

    return {"trades": trades, "total": len(trades)}


@router.get("/journal/stats")
def get_journal_stats():
    _, get_stats = _get_journal()
    if get_stats is None:
        return {"error": "Journal module not available"}
    return get_stats()


@router.get("/journal/analysis")
def get_loss_analysis():
    try:
        from trading_agents.loss_analyzer import analyze
        return analyze()
    except Exception:
        return {
            "error": "loss analysis failed",
            "total_losses": 0,
            "by_strategy": {},
            "by_source": {},
            "by_symbol": {},
            "trades": [],
        }
