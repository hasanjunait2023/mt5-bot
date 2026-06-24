"""Iconic Trader API — A/B/C scoreboard + live trade signals."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from core.file_utils import safe_read_json, safe_read_jsonl

router = APIRouter()

BASE_DIR     = Path(__file__).resolve().parents[3]
STATE_PATH   = BASE_DIR / "logs" / "iconic" / "_iconic_state.json"
EVENTS_PATH  = BASE_DIR / "logs" / "iconic" / "_iconic_events.jsonl"
AGENT_PATH   = BASE_DIR / "logs" / "iconic" / "_agent_state.json"
PAPER_PATH   = BASE_DIR / "logs" / "iconic" / "_paper_trades.jsonl"
BOARD_PATH   = BASE_DIR / "logs" / "iconic" / "_board_state.json"

# Scalp agent paths (logs/iconic_scalp/)
SCALP_AGENT_PATH = BASE_DIR / "logs" / "iconic_scalp" / "_agent_state.json"
SCALP_PAPER_PATH = BASE_DIR / "logs" / "iconic_scalp" / "_paper_trades.jsonl"


@router.get("/iconic/state")
def get_iconic_state():
    """All confluence scores (A/B/C) + currently active trade signals."""
    return safe_read_json(STATE_PATH, {
        "running": False,
        "updated_at": None,
        "signals_live": {},
        "scores_all": {},
    })


@router.get("/iconic/board")
def get_iconic_board():
    """Whole-board view: 8-currency strength matrix, correlation groups + leaders,
    candidate leaders (after hard group roll-over), open book, and management
    actions. Written by board_trader (the board-level system)."""
    return safe_read_json(BOARD_PATH, {
        "running": False, "updated_at": None, "n_pairs": 0,
        "strength": [], "groups": [], "candidates": [], "open": [], "managed": [],
    })


@router.get("/iconic/signals")
def get_iconic_signals(limit: int = 50):
    """Historical A/B signal events since last restart."""
    return {"signals": list(reversed(safe_read_jsonl(str(EVENTS_PATH), limit)))}


@router.get("/iconic/agent")
def get_iconic_agent():
    """Iconic agent status: paper/live mode, paper PF, daily DD, pending positions."""
    state = safe_read_json(AGENT_PATH, {
        "mode": "NOT_RUNNING", "live_mode": False,
        "paper_trades": 0, "paper_pf": 0.0,
        "paper_pending": [], "equity": 0.0,
        "daily_loss_pct": 0.0, "trades_today": {},
        "updated_at": None,
    })
    # Attach recent paper trade summary
    paper_lines = safe_read_jsonl(str(PAPER_PATH), 200)
    closed = [t for t in paper_lines if t.get("status") == "closed"]
    wins   = sum(1 for t in closed if t.get("pnl", 0) > 0)
    state["paper_closed"]   = len(closed)
    state["paper_wins"]     = wins
    state["paper_win_rate"] = round(wins / len(closed) * 100, 1) if closed else 0.0
    return state


@router.get("/iconic/symbol/{symbol}")
def get_iconic_symbol(symbol: str):
    """Confluence score + live signal for a single symbol."""
    state = safe_read_json(STATE_PATH, {})
    sym = symbol.upper()
    return {
        "symbol":      sym,
        "score":       state.get("scores_all", {}).get(sym),
        "live_signal": state.get("signals_live", {}).get(sym),
        "updated_at":  state.get("updated_at"),
    }


# ── Iconic Scalp endpoints (M15 NZDUSD, partial exit at 1R) ──────────────────

@router.get("/iconic/scalp/agent")
def get_iconic_scalp_agent():
    """Iconic Scalp agent state: NZDUSD M15, paper/live mode, PF, partial exits."""
    state = safe_read_json(SCALP_AGENT_PATH, {
        "mode": "NOT_RUNNING", "live_mode": False,
        "paper_trades": 0, "paper_pf": 0.0,
        "paper_pending": [], "equity": 0.0,
        "daily_loss_pct": 0.0, "trades_today": {},
        "updated_at": None,
    })
    closed = [t for t in safe_read_jsonl(str(SCALP_PAPER_PATH), 200)
              if t.get("status") == "closed"]
    wins        = sum(1 for t in closed if t.get("pnl", 0) > 0)
    partial_cnt = sum(1 for t in closed if t.get("partial_done"))
    state["paper_closed"]        = len(closed)
    state["paper_wins"]          = wins
    state["paper_win_rate"]      = round(wins / len(closed) * 100, 1) if closed else 0.0
    state["partial_exits_taken"] = partial_cnt
    # Profit factor from paper trades (cross-check with state file)
    wins_pnl   = sum(t["pnl"] for t in closed if t.get("pnl", 0) > 0)
    losses_pnl = abs(sum(t["pnl"] for t in closed if t.get("pnl", 0) < 0))
    state["paper_pf_live"] = round(wins_pnl / losses_pnl, 2) if losses_pnl > 0 else 0.0
    return state


@router.get("/iconic/scalp/trades")
def get_iconic_scalp_trades(limit: int = 50):
    """Recent Iconic Scalp paper trades, newest first."""
    trades = safe_read_jsonl(str(SCALP_PAPER_PATH), limit * 3)
    closed = [t for t in trades if t.get("status") == "closed"]
    closed.sort(key=lambda t: t.get("ts_close", ""), reverse=True)
    return {"trades": closed[:limit]}
