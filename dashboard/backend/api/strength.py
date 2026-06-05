"""Currency Strength API — 3-session -7..+7 strength, suggestions, agent status.

Reads the state JSON written by the strength producer (the single computation
path, also used in-process by the M3 Strength-Scalp agent) plus the agent's own
state/paper files. Mirrors api/iconic.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = BASE_DIR / "logs" / "strength" / "_strength_state.json"
AGENT_PATH = BASE_DIR / "logs" / "m3strength" / "_agent_state.json"
PAPER_PATH = BASE_DIR / "logs" / "m3strength" / "_paper_trades.jsonl"


def _read_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _read_jsonl(p: Path, limit: int = 200) -> list[dict]:
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


def _default_state():
    return {
        "updated_at": None,
        "tf": "H1",
        "pairs_loaded": 0,
        "majors": ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"],
        "sessions": {},
        "trade_of_the_day": None,
    }


@router.get("/strength/state")
def get_strength_state():
    """Full 3-session strength payload (score + tiers + suggestions per session)."""
    return _read_json(STATE_PATH, _default_state())


@router.get("/strength/suggestions")
def get_strength_suggestions(session: str = "newyork"):
    """Ranked BUY/SELL pair suggestions for one session (default New York)."""
    state = _read_json(STATE_PATH, _default_state())
    sess = (state.get("sessions") or {}).get(session) or {}
    return {
        "session": session,
        "updated_at": state.get("updated_at"),
        "suggestions": sess.get("suggestions", []),
        "trade_of_the_day": state.get("trade_of_the_day"),
    }


@router.get("/strength/agent")
def get_strength_agent():
    """M3 Strength-Scalp agent status + paper performance."""
    agent = _read_json(AGENT_PATH, {
        "mode": "OFFLINE", "magic": 20260900, "updated_at": None,
        "active_session": None, "open_positions": {}, "candidates": [],
        "trades_today": 0, "paper_pf": None, "paper_trades": None,
    })
    closed = [t for t in _read_jsonl(PAPER_PATH) if t.get("status") == "closed"]
    agent["paper_closed_count"] = len(closed)
    return agent
