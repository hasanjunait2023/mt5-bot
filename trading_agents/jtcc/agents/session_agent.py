"""Layer 1: Kill zone and session manager. Bangladesh UTC+6, DST-aware. Pure Python."""

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .base_agent import BaseAgent

BD_TZ = ZoneInfo("Asia/Dhaka")
UTC_TZ = ZoneInfo("UTC")

# (start_bd, end_bd, name, is_primary, is_silver_bullet)
SESSIONS = [
    (time(7, 0),  time(11, 0), "asian_kz",               False, False),
    (time(13, 0), time(16, 0), "london_kz",               True,  False),
    (time(14, 0), time(15, 0), "silver_bullet_london",    True,  True),
    (time(18, 0), time(21, 0), "ny_kz",                   True,  False),
    (time(21, 0), time(22, 0), "silver_bullet_ny",        True,  True),
]


def _now_bd() -> datetime:
    return datetime.now(tz=BD_TZ)


def _active_session(now_bd: datetime) -> dict:
    t = now_bd.time()
    active = []
    for start, end, name, primary, sb in SESSIONS:
        in_zone = start <= t < end
        if in_zone:
            active.append({
                "name": name,
                "primary": primary,
                "silver_bullet": sb,
                "end": end,
            })
    if not active:
        return {"name": "off_session", "active": False, "primary": False,
                "silver_bullet": False, "minutes_remaining": 0}
    # prefer primary over non-primary, silver_bullet over regular
    best = sorted(active, key=lambda x: (x["primary"], x["silver_bullet"]), reverse=True)[0]
    end_dt = datetime.combine(now_bd.date(), best["end"], tzinfo=BD_TZ)
    if end_dt < now_bd:
        end_dt += timedelta(days=1)
    mins_left = int((end_dt - now_bd).total_seconds() / 60)
    return {
        "name": best["name"],
        "active": True,
        "primary": best["primary"],
        "silver_bullet": best["silver_bullet"],
        "minutes_remaining": mins_left,
        "all_active": [s["name"] for s in active],
    }


def _next_session(now_bd: datetime) -> dict:
    t = now_bd.time()
    upcoming = []
    for start, end, name, primary, _ in SESSIONS:
        if start > t:
            start_dt = datetime.combine(now_bd.date(), start, tzinfo=BD_TZ)
        else:
            start_dt = datetime.combine(now_bd.date() + timedelta(days=1), start, tzinfo=BD_TZ)
        mins_until = int((start_dt - now_bd).total_seconds() / 60)
        upcoming.append((mins_until, name, primary))
    upcoming.sort()
    if upcoming:
        mins, name, primary = upcoming[0]
        return {"name": name, "minutes_until": mins, "primary": primary}
    return {"name": "unknown", "minutes_until": 999, "primary": False}


class SessionAgent(BaseAgent):
    name = "session"

    async def analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        now_bd = _now_bd()
        session = _active_session(now_bd)
        next_sess = _next_session(now_bd) if not session["active"] else {}
        return {
            **session,
            "next_session": next_sess,
            "bd_time": now_bd.strftime("%H:%M:%S"),
            "bd_date": now_bd.strftime("%Y-%m-%d"),
            "utc_time": datetime.now(tz=UTC_TZ).strftime("%H:%M:%S"),
        }
