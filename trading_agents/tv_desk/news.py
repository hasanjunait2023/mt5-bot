"""news — high-impact event filter from the cached ForexFactory calendar.

Used to (a) skip publishing a symbol when a HIGH-impact event for its currencies
is imminent, and (b) tag entries whose trade horizon contains one so the LLM /
dashboard can flag the risk.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from . import config

log = logging.getLogger("tv_desk.news")


def _load() -> list[dict]:
    try:
        d = json.loads(config.NEWS_CACHE_PATH.read_text(encoding="utf-8"))
        return d.get("events", []) if isinstance(d, dict) else []
    except Exception:
        return []


def _parse(ev: dict) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ev["date"])
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def high_impact(currencies: list[str], frm: datetime, to: datetime) -> list[dict]:
    """HIGH-impact events for the given currencies within [frm, to] (UTC)."""
    if not currencies:
        return []
    ccy = {c.upper() for c in currencies}
    out = []
    for ev in _load():
        if str(ev.get("impact", "")).lower() != "high":
            continue
        if str(ev.get("country", "")).upper() not in ccy:
            continue
        dt = _parse(ev)
        if dt and frm <= dt <= to:
            out.append({"title": ev.get("title"), "ccy": ev.get("country"),
                        "at": dt.isoformat(timespec="minutes")})
    return out


def blackout(symbol: str, now: datetime | None = None,
             window_min: int | None = None) -> dict | None:
    """If a HIGH-impact event is within ±window of `now`, return it (else None)."""
    now = now or datetime.now(timezone.utc)
    w = timedelta(minutes=window_min or config.NEWS_BLACKOUT_MIN)
    hits = high_impact(config.SYMBOL_CCY.get(symbol, []), now - w, now + w)
    return hits[0] if hits else None


def upcoming(symbol: str, horizon_h: float, now: datetime | None = None) -> list[dict]:
    """HIGH-impact events within the trade horizon (for tagging)."""
    now = now or datetime.now(timezone.utc)
    return high_impact(config.SYMBOL_CCY.get(symbol, []), now, now + timedelta(hours=horizon_h))
