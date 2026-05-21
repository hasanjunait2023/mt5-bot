"""Dashboard API — Signal Engine status, recent events, chart images."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse

router = APIRouter()

BASE_DIR    = Path(__file__).resolve().parents[3]
STATE_PATH  = BASE_DIR / "logs" / "signals" / "_signal_state.json"
EVENTS_PATH = BASE_DIR / "logs" / "signals" / "_signal_events.jsonl"
CHART_DIR   = BASE_DIR / "logs" / "signals" / "charts"
PERF_PATH   = BASE_DIR / "logs" / "signals" / "_paper_perf.json"
TRADES_PATH = BASE_DIR / "logs" / "signals" / "_paper_trades.jsonl"


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _read_events(limit: int = 50) -> list[dict]:
    if not EVENTS_PATH.exists():
        return []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
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
    return list(reversed(out))


@router.get("/signals")
def get_signals():
    state = _read_json(STATE_PATH, {
        "running": False, "symbols": [], "tick_sec": None,
        "updated_at": None,
    })
    events = _read_events(50)
    # quick rollup by type
    counts = {"alignment": 0, "cross": 0, "touch": 0}
    for e in events:
        t = e.get("type")
        if t in counts:
            counts[t] += 1
    return {
        "state": state,
        "events": events,
        "counts_recent": counts,
    }


@router.get("/signals/events")
def get_events(limit: int = 200):
    limit = max(1, min(int(limit), 1000))
    return {"events": _read_events(limit)}


@router.get("/signals/chart/{event_id}")
def get_chart(event_id: str):
    """Serve a signal's PNG. event_id is sanitized to allow only id chars."""
    safe = "".join(c for c in event_id if c.isalnum() or c in "-_")
    f = CHART_DIR / f"{safe}.png"
    if not f.exists():
        return {"error": "not_found"}
    return FileResponse(str(f), media_type="image/png")


@router.get("/signals/performance")
def get_performance():
    """Paper-trade win rate / pips per (system × signal_type).

    Returns the rollup that PaperTradeTracker writes every tick, plus the
    full list of closed trades for the dashboard table.
    """
    perf = _read_json(PERF_PATH, {
        "generated_at": None,
        "open_trades": [],
        "by_system": {"classic": {}, "improved": {}},
        "total_closed": 0,
    })
    # tail the closed-trades log for the comparison table
    closed: list[dict] = []
    if TRADES_PATH.exists():
        try:
            lines = TRADES_PATH.read_text(encoding="utf-8").splitlines()
            for ln in lines[-200:]:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    closed.append(json.loads(ln))
                except Exception:
                    continue
        except Exception:
            pass
    closed.reverse()
    perf["closed_trades"] = closed
    return perf


def _delivery_module():
    root = str(BASE_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    from trading_agents.signal_engine import delivery   # type: ignore
    return delivery


@router.get("/signals/delivery")
def get_delivery():
    """Current delivery config + live per-channel deliver-now status."""
    try:
        return _delivery_module().status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/signals/delivery")
def set_delivery(config: dict = Body(...)):
    """Persist a new delivery config (master / windows_mode / windows / channels)."""
    try:
        d = _delivery_module()
        saved = d.save_config(config)
        return {"ok": True, "config": saved}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/signals/compare")
def get_compare():
    """Side-by-side comparison: latest 50 events split by system."""
    events: list[dict] = []
    if EVENTS_PATH.exists():
        for ln in EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-500:]:
            ln = ln.strip()
            if not ln: continue
            try: events.append(json.loads(ln))
            except Exception: continue
    classic  = [e for e in events if e.get("system", "classic") == "classic"][-50:]
    improved = [e for e in events if e.get("system") == "improved"][-50:]
    return {
        "classic":  list(reversed(classic)),
        "improved": list(reversed(improved)),
        "counts": {"classic": len(classic), "improved": len(improved)},
    }
