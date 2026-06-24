"""Asia Desk API — Asian Range Fade (S1) live state + validated backtest summary."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from core.file_utils import safe_read_json

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
STATE_PATH = BASE_DIR / "logs" / "asia_desk" / "_state.json"

# Validated 2.1yr M15 real-cost backtest (in/out-of-sample). See
# trading_agents/asia_desk/backtest.py + STRATEGY_SPECS.md.
BACKTEST = {
    "window": "Asian Range Fade (SL 0.75*ATR, tuned 2026-06-06), 50k M15 bars (~1.4yr), real cost, in/out-of-sample",
    "deployed": ["XAUUSD", "BTCUSD", "AUDJPY", "USDJPY", "XAGUSD", "EURJPY"],
    "pairs": [
        {"symbol": "XAUUSD", "pf": 2.91, "pf_oos": 3.08, "wr": 60.1, "trades": 2049, "dd_pips": 685, "deployed": True},
        {"symbol": "XAGUSD", "pf": 1.93, "pf_oos": 2.80, "wr": 44.3, "trades": 2254, "dd_pips": 1928, "deployed": True},
        {"symbol": "BTCUSD", "pf": 2.19, "pf_oos": 2.25, "wr": 56.1, "trades": 2011, "dd_pips": 2718, "deployed": True},
        {"symbol": "AUDJPY", "pf": 1.93, "pf_oos": 1.92, "wr": 53.3, "trades": 1890, "dd_pips": 217, "deployed": True},
        {"symbol": "USDJPY", "pf": 1.81, "pf_oos": 1.77, "wr": 51.2, "trades": 1696, "dd_pips": 163, "deployed": True},
        {"symbol": "EURJPY", "pf": 1.58, "pf_oos": 1.58, "wr": 49.8, "trades": 1770, "dd_pips": 144, "deployed": True},
    ],
    "rejected": [
        {"strategy": "GBPJPY pair", "note": "OOS PF 1.04/1.05 (below 1.3 bar) + 0/9 live — dropped 2026-06-06"},
        {"strategy": "Reclaim (close-back-inside) entry filter", "note": "destroys edge: PF 1.5-2.2 → 0.5-0.9 all pairs. Naive touch is the edge"},
        {"strategy": "RR floor 0.8-1.0 / min-width filter", "note": "no help, slightly hurt (EURJPY oos <1.3)"},
        {"strategy": "S6 Fake-breakout / stop-hunt sweep", "note": "claimed 80% WR; real 30-38% WR, PF<0.9 all assets"},
        {"strategy": "S5 Gold Goldmine breakout (+v2 SGE)", "note": "72d 2.29 was regime-luck → 0.94/0.95 on 2.1yr"},
        {"strategy": "Fixed-pip stop on gold/BTC", "note": "PF 6 was a BUG (mis-scaled stop) — ATR stop is the real test"},
    ],
}


@router.get("/asia/state")
def get_asia_state():
    """Live Asia Desk agent state: open positions, today's ranges, daily trades."""
    return safe_read_json(STATE_PATH, {
        "agent": "asia_desk", "strategy": "Asian Range Fade (S1)",
        "running": False, "open_positions": [], "ranges": {}, "daily_trades": {},
    })


@router.get("/asia/backtest")
def get_asia_backtest():
    """Validated backtest summary backing the deployment decision."""
    return BACKTEST
