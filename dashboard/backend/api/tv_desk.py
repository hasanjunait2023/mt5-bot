"""TV Desk agents (Intraday Analyst + Session Scalper) API.

Reads the per-agent state/events/charts written by trading_agents/tv_desk/*.
Read-only: agents persist to logs/<agent>/, the dashboard serves snapshots.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from core.file_utils import safe_read_json, safe_read_jsonl

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
INTRADAY_DIR = BASE_DIR / "logs" / "intraday_analyst"
SCALP_DIR    = BASE_DIR / "logs" / "session_scalper"


def _latest_per_symbol(events: list[dict]) -> list[dict]:
    """Most-recent event per symbol (events already newest-first)."""
    seen: dict[str, dict] = {}
    for ev in events:
        sym = ev.get("symbol")
        if sym and sym not in seen:
            seen[sym] = ev
    return list(seen.values())


def _chart(agent_dir: Path, event_id: str):
    safe = "".join(c for c in event_id if c.isalnum() or c in "-_")
    f = agent_dir / "charts" / f"{safe}.png"
    if not f.exists():
        return {"error": "not_found"}
    return FileResponse(str(f), media_type="image/png")


# ── Intraday Analyst ─────────────────────────────────────────────────────────
@router.get("/intraday/state")
def intraday_state():
    state = safe_read_json(INTRADAY_DIR / "_state.json",
                           {"running": False, "mode": "intraday", "updated_at": None})
    events = safe_read_jsonl(str(INTRADAY_DIR / "_events.jsonl"), 60)
    return {"state": state, "latest": _latest_per_symbol(events), "count": len(events)}


@router.get("/intraday/events")
def intraday_events(limit: int = 60):
    return {"events": safe_read_jsonl(str(INTRADAY_DIR / "_events.jsonl"), max(1, min(limit, 500)))}


@router.get("/intraday/chart/{event_id}")
def intraday_chart(event_id: str):
    return _chart(INTRADAY_DIR, event_id)


@router.get("/intraday/perf")
def intraday_perf():
    return safe_read_json(INTRADAY_DIR / "_perf.json", {"totals": {}, "by_symbol": {}, "by_session": {}})


# ── Session Scalper ──────────────────────────────────────────────────────────
@router.get("/session-scalp/state")
def scalp_state():
    state = safe_read_json(SCALP_DIR / "_state.json",
                           {"running": False, "mode": "scalp", "updated_at": None})
    events = safe_read_jsonl(str(SCALP_DIR / "_events.jsonl"), 80)
    return {"state": state, "latest": _latest_per_symbol(events), "count": len(events)}


@router.get("/session-scalp/events")
def scalp_events(limit: int = 80):
    return {"events": safe_read_jsonl(str(SCALP_DIR / "_events.jsonl"), max(1, min(limit, 500)))}


@router.get("/session-scalp/chart/{event_id}")
def scalp_chart(event_id: str):
    return _chart(SCALP_DIR, event_id)


@router.get("/session-scalp/perf")
def scalp_perf():
    return safe_read_json(SCALP_DIR / "_perf.json", {"totals": {}, "by_symbol": {}, "by_session": {}})
