"""Scalp Agent API — GS11/GS07 paper-trade status and trade history."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from core.file_utils import safe_read_json, safe_read_jsonl

router = APIRouter()

BASE_DIR   = Path(__file__).resolve().parents[3]
STATE_PATH = BASE_DIR / "logs" / "scalp" / "_agent_state.json"
PAPER_PATH = BASE_DIR / "logs" / "scalp" / "_paper_trades.jsonl"


@router.get("/scalp/agent")
def get_scalp_agent():
    """Scalp agent state: paper/live mode per strategy, PF, DD, pending."""
    state = safe_read_json(STATE_PATH, {
        "mode": "NOT_RUNNING",
        "strategies": ["GS11", "GS07"],
        "symbol": "XAUUSD",
        "paper_trades": 0,
        "paper_pf": 0.0,
        "paper_pending": [],
        "strat_stats": {},
        "equity": 0.0,
        "daily_loss_pct": 0.0,
        "trades_today": 0,
        "updated_at": None,
    })

    # Compute WR from paper trades
    paper_lines = safe_read_jsonl(str(PAPER_PATH), 500)
    closed = [t for t in paper_lines if t.get("status") == "closed"]
    wins   = sum(1 for t in closed if t.get("pnl", 0) > 0)
    state["paper_closed"]   = len(closed)
    state["paper_wins"]     = wins
    state["paper_win_rate"] = round(wins / len(closed) * 100, 1) if closed else 0.0
    return state


@router.get("/scalp/trades")
def get_scalp_trades(limit: int = 50):
    """Recent paper trades (newest first), optionally filtered by strategy."""
    trades = safe_read_jsonl(str(PAPER_PATH), limit * 2)
    closed = [t for t in trades if t.get("status") == "closed"]
    closed.sort(key=lambda t: t.get("ts_close", ""), reverse=True)
    return {"trades": closed[:limit]}
