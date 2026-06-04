"""Asia Desk API — Asian Range Fade (S1) live state + validated backtest summary."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = BASE_DIR / "logs" / "asia_desk" / "_state.json"

# Validated 2.1yr M15 real-cost backtest (in/out-of-sample). See
# trading_agents/asia_desk/backtest.py + STRATEGY_SPECS.md.
BACKTEST = {
    "window": "2.1yr M15, real cost, in/out-of-sample",
    "deployed": ["USDJPY", "AUDJPY"],
    "pairs": [
        {"symbol": "USDJPY", "pf": 1.60, "pf_oos": 1.46, "wr": 50.5, "trades": 1418, "dd_pips": 180, "deployed": True},
        {"symbol": "AUDJPY", "pf": 1.47, "pf_oos": 1.40, "wr": 51.9, "trades": 1435, "dd_pips": 288, "deployed": True},
        {"symbol": "EURJPY", "pf": 1.36, "pf_oos": 1.26, "wr": 49.2, "trades": 1458, "dd_pips": 212, "deployed": False},
        {"symbol": "GBPJPY", "pf": 1.48, "pf_oos": 1.18, "wr": 49.2, "trades": 1584, "dd_pips": 325, "deployed": False},
    ],
    "rejected": [
        {"strategy": "S5 Gold Goldmine", "note": "72d PF 2.29 was regime-luck → 0.94 on 2.1yr"},
        {"strategy": "S2 ICT sweep", "note": "0.95 — no edge in M15 approximation"},
        {"strategy": "S3 PipStorm breakout", "note": "0.78 GBPUSD"},
        {"strategy": "S4 classic ORB", "note": "all <1.0 — ORB fails Asia session"},
    ],
}


def _read_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


@router.get("/asia/state")
def get_asia_state():
    """Live Asia Desk agent state: open positions, today's ranges, daily trades."""
    return _read_json(STATE_PATH, {
        "agent": "asia_desk", "strategy": "Asian Range Fade (S1)",
        "running": False, "open_positions": [], "ranges": {}, "daily_trades": {},
    })


@router.get("/asia/backtest")
def get_asia_backtest():
    """Validated backtest summary backing the deployment decision."""
    return BACKTEST
