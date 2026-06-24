"""Alpha Desk API — zones / liquidity / order blocks / briefs / signals.

Powers the Desk View page on the dashboard.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from core.file_utils import safe_read_json, safe_read_jsonl

router = APIRouter()

BASE_DIR     = Path(__file__).resolve().parents[3]
STATE_PATH   = BASE_DIR / "logs" / "alpha" / "_alpha_state.json"
EVENTS_PATH  = BASE_DIR / "logs" / "alpha" / "_alpha_events.jsonl"
BRIEFS_PATH  = BASE_DIR / "logs" / "alpha" / "_alpha_briefs.jsonl"
CHART_DIR    = BASE_DIR / "logs" / "alpha" / "charts"


@router.get("/desk/state")
def get_desk_state():
    """Full alpha desk state — zones, liquidity, order blocks, session."""
    return safe_read_json(STATE_PATH, {
        "running": False, "session": "off",
        "zones_snapshot": {}, "liquidity_snapshot": {},
        "orderflow_snapshot": {}, "updated_at": None,
    })


@router.get("/desk/symbol/{symbol}")
def get_desk_symbol(symbol: str):
    """All alpha context for a single symbol — zones + pools + order blocks."""
    state = safe_read_json(STATE_PATH, {})
    sym = symbol.upper()
    return {
        "symbol":      sym,
        "session":     state.get("session", "off"),
        "zones":       state.get("zones_snapshot", {}).get(sym, {}),
        "liquidity":   state.get("liquidity_snapshot", {}).get(sym, []),
        "order_blocks":state.get("orderflow_snapshot", {}).get(sym, {}),
        "updated_at":  state.get("updated_at"),
    }


@router.get("/desk/signals")
def get_alpha_signals(limit: int = 50):
    return {"signals": list(reversed(safe_read_jsonl(str(EVENTS_PATH), limit)))}


@router.get("/desk/briefs")
def get_alpha_briefs(limit: int = 6):
    return {"briefs": list(reversed(safe_read_jsonl(str(BRIEFS_PATH), limit)))}


@router.get("/desk/brief/now")
def get_brief_now():
    """Returns the most recent brief (live preview without waiting for cron)."""
    briefs = safe_read_jsonl(str(BRIEFS_PATH), 1)
    if not briefs:
        return {"brief": None, "msg": "No brief generated yet — wait for next session window"}
    return {"brief": briefs[-1]}


@router.get("/desk/chart/{event_id}")
def get_chart(event_id: str):
    safe = "".join(c for c in event_id if c.isalnum() or c in "-_")
    # Alpha chart filename pattern: alpha-{type}-{symbol}-{epoch}.png
    f = CHART_DIR / f"{safe}.png"
    if not f.exists():
        # fallback: search by prefix
        matches = list(CHART_DIR.glob(f"{safe}*.png"))
        if not matches:
            return {"error": "not_found"}
        f = matches[0]
    return FileResponse(str(f), media_type="image/png")
