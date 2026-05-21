"""CPP — unified Confluence Pullback Portfolio daily-performance API.

Surfaces the per-day performance file written by mt5_bridge/cpp_live_trader
(wins/losses vs the 15-20 / <=6 / <=6%DD target, daily P&L, daily DD vs the
6% breaker line, per-symbol contribution) plus the hybrid trade-confirmation
agent's recent decision telemetry. Read-only, fail-soft.
"""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter

from core.config import CPP_DAILY_PATH, CPP_STATE_PATH, AGENT_METRICS

router = APIRouter()


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _agent_stats():
    """Last-200 trade_confirmation_agent calls: backend split + fallback rate."""
    try:
        lines = AGENT_METRICS.read_text(encoding="utf-8").splitlines()[-400:]
    except Exception:
        return {"calls": 0, "claude": 0, "nvidia": 0, "errors": 0,
                "fallback_pct": 0.0}
    claude = nvidia = errors = calls = 0
    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        if e.get("agent") != "trade_confirmation_agent":
            continue
        calls += 1
        if e.get("backend") == "nvidia":
            nvidia += 1
        elif e.get("backend") == "claude":
            claude += 1
        if not e.get("ok", True):
            errors += 1
    return {"calls": calls, "claude": claude, "nvidia": nvidia,
            "errors": errors,
            "fallback_pct": round(nvidia / calls * 100, 1) if calls else 0.0}


@router.get("/cpp/daily")
def cpp_daily():
    daily = _read_json(CPP_DAILY_PATH)
    state = _read_json(CPP_STATE_PATH)

    runner_online = False
    ts = state.get("ts")
    if ts:
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(ts)).total_seconds()
            runner_online = age < 180  # state written every M15 loop
        except Exception:
            pass

    return {
        "daily": daily or {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "wins": 0, "losses": 0, "trades": 0, "win_rate": 0.0,
            "daily_pnl": 0.0, "floating_pnl": 0.0, "daily_dd_pct": 0.0,
            "dd_limit_pct": 6.0, "dd_breaker_tripped": False,
            "target": {"wins": 15, "losses": 6, "dd": 6.0},
            "target_hit": False, "per_symbol": {}, "recent_trades": [],
        },
        "runner": {
            "online": runner_online,
            "running": state.get("running", False),
            "agent_mode": state.get("agent_mode", "—"),
            "dd_breaker_tripped": state.get("dd_breaker_tripped", False),
            "symbols": state.get("symbols", []),
            "last_signals": state.get("last_signals", {}),
            "ts": ts,
        },
        "agent": _agent_stats(),
        "server_time": int(time.time()),
    }
