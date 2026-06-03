"""GS-VP Agent API — adaptive volume-profile live (demo) status + trades."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = BASE_DIR / "logs" / "scalp" / "_gsvp_agent_state.json"
TRADES_PATH = BASE_DIR / "logs" / "scalp" / "_gsvp_trades.jsonl"


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


@router.get("/vp/agent")
def get_vp_agent():
    """GS-VP agent state: demo/real, per-symbol PF/WR/gate, equity, DD."""
    return _read_json(STATE_PATH, {
        "agent": "GS-VP",
        "mode": "NOT_RUNNING",
        "account": "demo",
        "symbols": ["GBPUSD", "EURUSD", "XAUUSD", "BTCUSD", "XAGUSD"],
        "tf": "M15",
        "trades": 0,
        "pf": 0.0,
        "open_positions": 0,
        "per_symbol": {},
        "equity": 0.0,
        "daily_loss_pct": 0.0,
        "trades_today": 0,
        "gate": {"min_trades": 20, "min_pf": 1.3},
        "updated_at": None,
    })


@router.get("/vp/trades")
def get_vp_trades(limit: int = 50):
    """Recent closed GS-VP trades (newest first)."""
    trades = _read_jsonl(TRADES_PATH, limit * 3)
    closed = [t for t in trades if t.get("status") == "closed"]
    closed.sort(key=lambda t: t.get("ts_close", ""), reverse=True)
    return {"trades": closed[:limit]}
