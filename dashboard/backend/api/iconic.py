"""Iconic Trader API — A/B/C scoreboard + live trade signals."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR     = Path(__file__).resolve().parents[3]
STATE_PATH   = BASE_DIR / "logs" / "iconic" / "_iconic_state.json"
EVENTS_PATH  = BASE_DIR / "logs" / "iconic" / "_iconic_events.jsonl"
AGENT_PATH   = BASE_DIR / "logs" / "iconic" / "_agent_state.json"
PAPER_PATH   = BASE_DIR / "logs" / "iconic" / "_paper_trades.jsonl"

# Scalp agent paths (logs/iconic_scalp/)
SCALP_AGENT_PATH = BASE_DIR / "logs" / "iconic_scalp" / "_agent_state.json"
SCALP_PAPER_PATH = BASE_DIR / "logs" / "iconic_scalp" / "_paper_trades.jsonl"


def _read_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _read_jsonl(p: Path, limit: int = 100) -> list[dict]:
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


@router.get("/iconic/state")
def get_iconic_state():
    """All confluence scores (A/B/C) + currently active trade signals."""
    return _read_json(STATE_PATH, {
        "running": False,
        "updated_at": None,
        "signals_live": {},
        "scores_all": {},
    })


@router.get("/iconic/signals")
def get_iconic_signals(limit: int = 50):
    """Historical A/B signal events since last restart."""
    return {"signals": list(reversed(_read_jsonl(EVENTS_PATH, limit)))}


@router.get("/iconic/agent")
def get_iconic_agent():
    """Iconic agent status: paper/live mode, paper PF, daily DD, pending positions."""
    state = _read_json(AGENT_PATH, {
        "mode": "NOT_RUNNING", "live_mode": False,
        "paper_trades": 0, "paper_pf": 0.0,
        "paper_pending": [], "equity": 0.0,
        "daily_loss_pct": 0.0, "trades_today": {},
        "updated_at": None,
    })
    # Attach recent paper trade summary
    paper_lines = _read_jsonl(PAPER_PATH, 200)
    closed = [t for t in paper_lines if t.get("status") == "closed"]
    wins   = sum(1 for t in closed if t.get("pnl", 0) > 0)
    state["paper_closed"]   = len(closed)
    state["paper_wins"]     = wins
    state["paper_win_rate"] = round(wins / len(closed) * 100, 1) if closed else 0.0
    return state


@router.get("/iconic/symbol/{symbol}")
def get_iconic_symbol(symbol: str):
    """Confluence score + live signal for a single symbol."""
    state = _read_json(STATE_PATH, {})
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
    state = _read_json(SCALP_AGENT_PATH, {
        "mode": "NOT_RUNNING", "live_mode": False,
        "paper_trades": 0, "paper_pf": 0.0,
        "paper_pending": [], "equity": 0.0,
        "daily_loss_pct": 0.0, "trades_today": {},
        "updated_at": None,
    })
    closed = [t for t in _read_jsonl(SCALP_PAPER_PATH, 200)
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
    trades = _read_jsonl(SCALP_PAPER_PATH, limit * 3)
    closed = [t for t in trades if t.get("status") == "closed"]
    closed.sort(key=lambda t: t.get("ts_close", ""), reverse=True)
    return {"trades": closed[:limit]}
