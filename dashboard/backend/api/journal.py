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


@router.get("/scorecard")
def get_scorecard(window_days: int = 30):
    """Strategy Performance scorecard — verdict + per-strategy P&L + fix + improvement
    queue. Serves the cached file the analytics service writes (fresh, cheap); falls
    back to building live if the file is missing."""
    import json
    sc_file = BASE_DIR / "logs" / "_strategy_scorecard.json"
    try:
        if sc_file.exists():
            data = json.loads(sc_file.read_text(encoding="utf-8"))
            if window_days == data.get("window_days"):
                return data
        from trading_agents.strategy_scorecard import build_scorecard
        return build_scorecard(window_days=window_days)
    except Exception as e:
        return {"error": f"scorecard unavailable: {e}", "strategies": [],
                "counts": {"profitable": 0, "losing": 0, "insufficient": 0},
                "portfolio": {"net_pnl": 0, "trades": 0}, "improvement_queue": []}


@router.get("/reconciler/status")
def get_reconciler_status():
    """Proxy the bridge reconciler status for the dashboard 'last reconciled' stamp."""
    import os
    import requests
    base = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        return requests.get(f"{base}/reconciler/status", timeout=4).json()
    except Exception as e:
        return {"error": str(e), "last_run": None, "enabled": False}
