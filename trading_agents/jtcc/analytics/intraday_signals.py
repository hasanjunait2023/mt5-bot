"""Intraday signal helpers — Silver Bullet windows, ORB windows, session timing.

These are PURE Python time-based predicates. Used by M3 scalping strategies.
All times in Bangladesh time (UTC+6).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BD_TZ = ZoneInfo("Asia/Dhaka")


def _now_bd() -> datetime:
    return datetime.now(tz=BD_TZ)


def is_silver_bullet_window(now_bd: datetime | None = None) -> dict:
    """ICT Silver Bullet trading windows:
    - London Silver Bullet: 14:00-15:00 BD
    - NY AM Silver Bullet:  21:00-22:00 BD
    """
    now = now_bd or _now_bd()
    h, m = now.hour, now.minute
    in_london = h == 14
    in_ny_am = h == 21
    active = in_london or in_ny_am
    return {
        "active": active,
        "session": "london_sb" if in_london else "ny_am_sb" if in_ny_am else None,
        "minutes_remaining": (60 - m) if active else 0,
        "next_window_minutes_away": (
            0 if active
            else ((14 - h) * 60 - m) if h < 14
            else ((21 - h) * 60 - m) if h < 21
            else ((38 - h) * 60 - m)  # tomorrow's London window
        ),
    }


def is_london_open_window(now_bd: datetime | None = None,
                          start_hour: int = 13, duration_min: int = 60) -> dict:
    """London open breakout window: 13:00-14:00 BD (1h after open)."""
    now = now_bd or _now_bd()
    minutes_since_open = (now.hour - start_hour) * 60 + now.minute
    active = 0 <= minutes_since_open < duration_min and now.hour <= start_hour + 1
    return {
        "active": active,
        "minutes_since_open": minutes_since_open if active else 0,
        "minutes_remaining": (duration_min - minutes_since_open) if active else 0,
    }


def is_ny_open_window(now_bd: datetime | None = None,
                      start_hour: int = 18, duration_min: int = 60) -> dict:
    """NY open breakout window: 18:00-19:00 BD."""
    now = now_bd or _now_bd()
    minutes_since_open = (now.hour - start_hour) * 60 + now.minute
    active = 0 <= minutes_since_open < duration_min and now.hour <= start_hour + 1
    return {
        "active": active,
        "minutes_since_open": minutes_since_open if active else 0,
        "minutes_remaining": (duration_min - minutes_since_open) if active else 0,
    }


def is_asian_lull_window(now_bd: datetime | None = None) -> dict:
    """Asian lull / mid-day low-volatility window — good for VWAP reversion.
    Approx 11:00-13:00 BD (end of Asian, before London open).
    """
    now = now_bd or _now_bd()
    h = now.hour
    active = 11 <= h < 13
    return {"active": active}


def get_all_intraday_signals(now_bd: datetime | None = None) -> dict:
    """One-shot snapshot of all intraday time-based signals."""
    now = now_bd or _now_bd()
    sb = is_silver_bullet_window(now)
    return {
        "bd_time": now.strftime("%H:%M:%S"),
        "silver_bullet_window": sb["active"],
        "silver_bullet_session": sb["session"],
        "silver_bullet_minutes_remaining": sb["minutes_remaining"],
        "london_open_window": is_london_open_window(now)["active"],
        "ny_open_window": is_ny_open_window(now)["active"],
        "asian_lull_window": is_asian_lull_window(now)["active"],
    }
