"""Time-sync widget endpoint — UTC / BD / current session / next brief."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from trading_agents.alpha_desk.sessions import (
        current_session, session_label, is_overlap,
        next_brief as _next_brief, session_table,
    )
    _HAVE_SESSIONS = True
except Exception:
    _HAVE_SESSIONS = False
    def current_session(now=None): return "off"
    def session_label(s): return s
    def is_overlap(now=None): return False
    def _next_brief(now=None): return ("off", None)
    def session_table(now=None): return []


@router.get("/system/time")
def get_system_time():
    now_utc = datetime.now(timezone.utc)
    now_bd  = now_utc + timedelta(hours=6)
    sess    = current_session(now_utc)

    bd_tz = timezone(timedelta(hours=6))
    next_brief = None
    if _HAVE_SESSIONS:
        try:
            nxt_name, nxt_at = _next_brief(now_utc)
            if nxt_at is not None:
                mins = int((nxt_at - now_utc).total_seconds() // 60)
                next_brief = {
                    "session":      nxt_name,
                    "fires_at_utc": nxt_at.isoformat(timespec="minutes"),
                    "fires_at_bd":  nxt_at.astimezone(bd_tz).isoformat(timespec="minutes"),
                    "fires_bd_hhmm": nxt_at.astimezone(bd_tz).strftime("%H:%M"),
                    "minutes_until": mins,
                }
        except Exception:
            pass

    return {
        "utc":      now_utc.isoformat(timespec="seconds"),
        "bd":       now_bd.isoformat(timespec="seconds"),
        "utc_hhmm": now_utc.strftime("%H:%M:%S"),
        "bd_hhmm":  now_bd.strftime("%H:%M:%S"),
        "session":  sess,
        "session_label": session_label(sess),
        "overlap":  is_overlap(now_utc),     # London↔NY peak window
        "next_brief": next_brief,
        "sessions": session_table(now_utc),  # full DST-aware table (UTC + BD)
    }
