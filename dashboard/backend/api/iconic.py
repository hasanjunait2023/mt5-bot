"""Iconic Trader API — A/B/C scoreboard + live trade signals."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR    = Path(__file__).resolve().parents[3]
STATE_PATH  = BASE_DIR / "logs" / "iconic" / "_iconic_state.json"
EVENTS_PATH = BASE_DIR / "logs" / "iconic" / "_iconic_events.jsonl"


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
