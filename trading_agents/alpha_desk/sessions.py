"""Trading session boundaries — DST-aware, computed from real market hours.

Each major centre is defined by its LOCAL business hours + IANA timezone, so
daylight-saving shifts (London BST↔GMT, New York EDT↔EST, Sydney AEDT↔AEST)
are handled automatically by `zoneinfo`. Tokyo never observes DST.

For scoring/UI we collapse the four centres into three "sessions":
  asia   = Sydney OR Tokyo active
  london = London active
  ny     = New York active
  (off)  = none active / weekend

Priority when overlapping: ny > london > asia. Use `is_overlap()` to detect
the London↔New York peak-liquidity window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

SessionName = Literal["asia", "london", "ny", "off"]

BRIEF_OFFSET_MIN = 30          # fire pre-session brief this many minutes early

# Asian-range window in UTC for liquidity detection. Tokyo never observes DST,
# so the main Asian session is a fixed 00:00–09:00 UTC year-round.
ASIA_START = time(0, 0)
ASIA_END   = time(9, 0)


@dataclass(frozen=True)
class Centre:
    key: str
    label: str
    tz: str                    # IANA timezone
    open_hour: int             # local hour (24h)
    close_hour: int


# Real market centres — local 8AM–5PM (Tokyo 9AM–6PM) business hours.
CENTRES: dict[str, Centre] = {
    "sydney": Centre("sydney", "🇦🇺 Sydney",   "Australia/Sydney", 8, 17),
    "tokyo":  Centre("tokyo",  "🇯🇵 Tokyo",    "Asia/Tokyo",       9, 18),
    "london": Centre("london", "🌅 London",    "Europe/London",    8, 17),
    "ny":     Centre("ny",     "🗽 New York",  "America/New_York", 8, 17),
}

# Collapsed 3-session model used by scoring + UI.
SESSION_LABELS: dict[str, str] = {
    "asia":   "🌏 Asia",
    "london": "🌅 London",
    "ny":     "🗽 New York",
    "off":    "💤 Off-session",
}

# Which centre's open drives each pre-session brief.
BRIEF_CENTRES: dict[str, str] = {
    "asia":   "tokyo",         # main Asian open = Tokyo 09:00 JST (00:00 UTC)
    "london": "london",
    "ny":     "ny",
}

# Compat shim — some modules check `if session in SESSIONS`.
SESSIONS = {k: SESSION_LABELS[k] for k in ("asia", "london", "ny")}


# ── core helpers ─────────────────────────────────────────────────────────────

def _now(now_utc: Optional[datetime]) -> datetime:
    return now_utc or datetime.now(timezone.utc)


def is_centre_active(centre_key: str, now_utc: Optional[datetime] = None) -> bool:
    """True if `centre_key` is in its local business hours (weekdays only)."""
    c = CENTRES[centre_key]
    local = _now(now_utc).astimezone(ZoneInfo(c.tz))
    if local.weekday() >= 5:                 # 5=Sat 6=Sun → forex closed
        return False
    return c.open_hour <= local.hour < c.close_hour


def current_session(now_utc: Optional[datetime] = None) -> SessionName:
    """Collapsed session with priority ny > london > asia."""
    if is_centre_active("ny", now_utc):
        return "ny"
    if is_centre_active("london", now_utc):
        return "london"
    if is_centre_active("tokyo", now_utc) or is_centre_active("sydney", now_utc):
        return "asia"
    return "off"


def is_overlap(now_utc: Optional[datetime] = None) -> bool:
    """London ↔ New York overlap = peak liquidity window."""
    return is_centre_active("london", now_utc) and is_centre_active("ny", now_utc)


def session_label(name: str) -> str:
    return SESSION_LABELS.get(name, name)


def active_centres(now_utc: Optional[datetime] = None) -> list[str]:
    return [k for k in CENTRES if is_centre_active(k, now_utc)]


# ── session-open scheduling (DST-aware, weekend-skipping) ────────────────────

def next_centre_open(centre_key: str, now_utc: Optional[datetime] = None) -> datetime:
    """Next UTC datetime that `centre_key` opens (skips weekends)."""
    c = CENTRES[centre_key]
    tz = ZoneInfo(c.tz)
    now = _now(now_utc)
    local_now = now.astimezone(tz)
    cand = local_now.replace(hour=c.open_hour, minute=0, second=0, microsecond=0)
    if cand <= local_now:
        cand += timedelta(days=1)
    while cand.weekday() >= 5:                # skip Sat/Sun opens
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def next_brief(now_utc: Optional[datetime] = None) -> tuple[SessionName, datetime]:
    """Return (session, UTC datetime) of the next pre-session brief."""
    now = _now(now_utc)
    candidates: list[tuple[str, datetime]] = []
    for sess, centre_key in BRIEF_CENTRES.items():
        open_utc = next_centre_open(centre_key, now)
        brief_at = open_utc - timedelta(minutes=BRIEF_OFFSET_MIN)
        if brief_at <= now:                  # brief window already passed → next day
            open_utc = next_centre_open(centre_key, open_utc + timedelta(minutes=1))
            brief_at = open_utc - timedelta(minutes=BRIEF_OFFSET_MIN)
        candidates.append((sess, brief_at))
    candidates.sort(key=lambda c: c[1])
    return candidates[0]                       # (session, brief_utc)


def session_table(now_utc: Optional[datetime] = None) -> list[dict]:
    """Human-readable table of every centre's current open/close in UTC + BD."""
    now = _now(now_utc)
    out = []
    for key, c in CENTRES.items():
        tz = ZoneInfo(c.tz)
        local = now.astimezone(tz)
        open_local  = local.replace(hour=c.open_hour,  minute=0, second=0, microsecond=0)
        close_local = local.replace(hour=c.close_hour, minute=0, second=0, microsecond=0)
        open_utc  = open_local.astimezone(timezone.utc)
        close_utc = close_local.astimezone(timezone.utc)
        out.append({
            "centre": key, "label": c.label,
            "open_utc":  open_utc.strftime("%H:%M"),
            "close_utc": close_utc.strftime("%H:%M"),
            "open_bd":   (open_utc  + timedelta(hours=6)).strftime("%H:%M"),
            "close_bd":  (close_utc + timedelta(hours=6)).strftime("%H:%M"),
            "active":    is_centre_active(key, now),
        })
    return out
