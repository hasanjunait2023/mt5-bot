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
    "window": "Asian Range Fade (ATR stop), 2.1yr M15, real cost, in/out-of-sample",
    "deployed": ["XAUUSD", "BTCUSD", "AUDJPY", "USDJPY"],
    "pairs": [
        {"symbol": "XAUUSD", "pf": 2.15, "pf_oos": 2.23, "wr": 56.8, "trades": 1847, "dd_pips": 747, "deployed": True},
        {"symbol": "BTCUSD", "pf": 1.72, "pf_oos": 1.71, "wr": 54.7, "trades": 1735, "dd_pips": 4326, "deployed": True},
        {"symbol": "AUDJPY", "pf": 1.56, "pf_oos": 1.44, "wr": 51.5, "trades": 1699, "dd_pips": 260, "deployed": True},
        {"symbol": "USDJPY", "pf": 1.57, "pf_oos": 1.49, "wr": 50.1, "trades": 1480, "dd_pips": 169, "deployed": True},
        {"symbol": "XAGUSD", "pf": 1.54, "pf_oos": 2.08, "wr": 42.9, "trades": 1984, "dd_pips": 2115, "deployed": False},
        {"symbol": "EURJPY", "pf": 1.36, "pf_oos": 1.26, "wr": 49.2, "trades": 1458, "dd_pips": 212, "deployed": False},
        {"symbol": "GBPJPY", "pf": 1.48, "pf_oos": 1.18, "wr": 49.2, "trades": 1584, "dd_pips": 325, "deployed": False},
    ],
    "rejected": [
        {"strategy": "S6 Fake-breakout / stop-hunt sweep", "note": "claimed 80% WR; real 30-38% WR, PF<0.9 all assets"},
        {"strategy": "S5 Gold Goldmine breakout (+v2 SGE)", "note": "72d 2.29 was regime-luck → 0.94/0.95 on 2.1yr"},
        {"strategy": "S2 ICT sweep / S3 PipStorm / S4 ORB", "note": "all <1.0 — breakout/sweep families fail Asia"},
        {"strategy": "Fixed-pip stop on gold/BTC", "note": "PF 6 was a BUG (mis-scaled stop) — ATR stop is the real test"},
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
