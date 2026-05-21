"""Dashboard API — JTCC signal engine status, confluence scores, and signal history."""

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent.parent.parent
JTCC_STATE = BASE_DIR / "logs" / "jtcc" / "_jtcc_state.json"
JTCC_PERF = BASE_DIR / "logs" / "jtcc" / "_jtcc_performance.json"
JTCC_LOG = BASE_DIR / "logs" / "jtcc" / "_jtcc_trades.jsonl"
JTCC_LATENCY = BASE_DIR / "logs" / "jtcc" / "_jtcc_latency.json"
JTCC_GUARDIAN = BASE_DIR / "logs" / "jtcc" / "_guardian_state.json"
JTCC_DIGEST = BASE_DIR / "logs" / "jtcc" / "_jtcc_digest.json"
JTCC_COACH = BASE_DIR / "logs" / "jtcc" / "_jtcc_coach.json"


def _read_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default or {}


def _read_trades(limit: int = 50) -> list[dict]:
    try:
        if not JTCC_LOG.exists():
            return []
        lines = JTCC_LOG.read_text(encoding="utf-8").strip().splitlines()
        trades = [json.loads(l) for l in lines[-limit:] if l.strip()]
        return list(reversed(trades))
    except Exception:
        return []


@router.get("/jtcc")
def get_jtcc():
    state = _read_json(JTCC_STATE, {
        "status": "offline",
        "dry_run": False,
        "symbols": [],
        "confluence": {},
        "last_signals": [],
        "daily_api_calls": 0,
    })
    perf = _read_json(JTCC_PERF, {
        "total_trades": 0, "wins": 0, "losses": 0,
        "total_pnl": 0.0, "win_rate_pct": 0.0,
        "strategy_stats": {},
    })

    total = perf.get("total_trades", 0)
    wins = perf.get("wins", 0)
    win_rate = round(wins / total * 100, 1) if total > 0 else 0.0

    return {
        "status": state.get("status", "offline"),
        "dry_run": state.get("dry_run", False),
        "started_at": state.get("started_at"),
        "symbols": state.get("symbols", []),
        "daily_api_calls": state.get("daily_api_calls", 0),
        "api_calls_limit": 15,
        "confluence": state.get("confluence", {}),
        "last_signals": state.get("last_signals", [])[:10],
        "performance": {
            **perf,
            "win_rate_pct": win_rate,
        },
        "strategy_stats": perf.get("strategy_stats", {}),
        "backend_stats": state.get("backend_stats", {
            "claude_success": 0, "nvidia_recovered": 0, "all_fail": 0,
            "total_calls": 0, "fallback_rate_pct": 0,
        }),
        "ict_specialist": state.get("ict_specialist_stats", {
            "calls_today": 0, "calls_budget": 30, "gate_blocks": 0,
            "signals_returned": 0, "signal_rate_pct": 0,
        }),
        "last_heartbeat": state.get("last_heartbeat"),
    }


@router.get("/jtcc/trades")
def get_jtcc_trades(limit: int = 50):
    return {"trades": _read_trades(limit), "total": len(_read_trades(500))}


@router.get("/jtcc/confluence")
def get_confluence():
    state = _read_json(JTCC_STATE, {})
    return {"confluence": state.get("confluence", {})}


@router.get("/jtcc/equity")
def get_equity_curve():
    """Build JTCC-specific equity curve from trade close history."""
    trades = _read_trades(500)
    closes = [t for t in trades if t.get("type") == "trade_close"]
    closes.sort(key=lambda t: t.get("ts", ""))
    curve, cumulative = [], 0.0
    for c in closes:
        cumulative += c.get("pnl", 0)
        curve.append({"ts": c.get("ts"), "pnl": c.get("pnl"), "equity": round(cumulative, 2),
                      "symbol": c.get("symbol"), "strategy": c.get("strategy")})
    # Compute drawdown
    peak = 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        p["drawdown"] = round(peak - p["equity"], 2)
    return {"points": curve, "total_pnl": round(cumulative, 2), "trade_count": len(curve)}


@router.get("/jtcc/heatmap")
def get_strategy_heatmap():
    """Per-strategy × per-symbol P&L matrix for heatmap viz."""
    trades = _read_trades(1000)
    closes = [t for t in trades if t.get("type") == "trade_close"]
    matrix: dict[str, dict[str, dict]] = {}
    for c in closes:
        strat = c.get("strategy", "unknown")
        sym = c.get("symbol", "?")
        pnl = c.get("pnl", 0)
        if strat not in matrix:
            matrix[strat] = {}
        if sym not in matrix[strat]:
            matrix[strat][sym] = {"trades": 0, "wins": 0, "pnl": 0.0}
        matrix[strat][sym]["trades"] += 1
        matrix[strat][sym]["pnl"] = round(matrix[strat][sym]["pnl"] + pnl, 2)
        if pnl > 0:
            matrix[strat][sym]["wins"] += 1
    return {"matrix": matrix}


@router.get("/jtcc/latency")
def get_latency():
    return _read_json(JTCC_LATENCY, {"stats": {}, "updated_at": None})


@router.get("/jtcc/guardian")
def get_guardian():
    return _read_json(JTCC_GUARDIAN, {"issues": [], "issues_count": 0, "checked_at": None})


@router.get("/jtcc/digest")
def get_digest():
    return _read_json(JTCC_DIGEST, {"date": None, "today": {}})


@router.get("/jtcc/coach")
def get_coach():
    return _read_json(JTCC_COACH, {"last_run": None, "proposals": []})
