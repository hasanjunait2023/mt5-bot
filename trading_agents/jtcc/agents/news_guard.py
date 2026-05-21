"""Layer 1: News guard — blocks trading around high-impact economic events. Uses FMP calendar."""

import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .base_agent import BaseAgent

BD_TZ = ZoneInfo("Asia/Dhaka")
_cache: dict = {"data": [], "fetched_at": None}
_CACHE_TTL_MINUTES = 30


def _fetch_calendar() -> list[dict]:
    """Fetch FMP economic calendar for the next 24 hours."""
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return []
    now = datetime.now(tz=BD_TZ)
    from_dt = now.strftime("%Y-%m-%d")
    to_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={from_dt}&to={to_dt}&apikey={api_key}"
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json() if isinstance(r.json(), list) else []
    except Exception:
        return []


def _get_calendar() -> list[dict]:
    global _cache
    now = datetime.now(tz=BD_TZ)
    if _cache["fetched_at"] is None or (now - _cache["fetched_at"]).total_seconds() > _CACHE_TTL_MINUTES * 60:
        _cache["data"] = _fetch_calendar()
        _cache["fetched_at"] = now
    return _cache["data"]


def _check_news(block_before: int = 30, block_after: int = 15) -> dict:
    now_bd = datetime.now(tz=BD_TZ)
    events = _get_calendar()

    blocked = False
    blocking_event = None
    next_event_mins = 9999
    upcoming = []

    for event in events:
        impact = (event.get("impact") or event.get("type") or "").upper()
        if impact not in ("HIGH", "3"):
            continue
        try:
            # FMP returns UTC datetime string
            ev_dt = datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00"))
            ev_bd = ev_dt.astimezone(BD_TZ)
        except Exception:
            continue

        delta_mins = (ev_bd - now_bd).total_seconds() / 60

        # Check block window
        if -block_after <= delta_mins <= block_before:
            blocked = True
            blocking_event = {
                "name": event.get("event", "Unknown"),
                "country": event.get("country", ""),
                "time": ev_bd.strftime("%H:%M BD"),
                "delta_mins": round(delta_mins, 1),
            }

        if 0 < delta_mins < next_event_mins:
            next_event_mins = int(delta_mins)

        if 0 < delta_mins <= 120:
            upcoming.append({
                "name": event.get("event", "Unknown"),
                "country": event.get("country", ""),
                "time_bd": ev_bd.strftime("%H:%M"),
                "mins_until": int(delta_mins),
            })

    return {
        "blocked": blocked,
        "blocking_event": blocking_event,
        "next_event_mins": next_event_mins if next_event_mins < 9999 else None,
        "upcoming_events": upcoming[:5],
        "reason": f"High-impact event: {blocking_event['name']}" if blocked else None,
    }


class NewsGuardAgent(BaseAgent):
    name = "news_guard"

    def __init__(self, block_before: int = 30, block_after: int = 15) -> None:
        super().__init__()
        self.block_before = block_before
        self.block_after = block_after

    async def analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return _check_news(self.block_before, self.block_after)
