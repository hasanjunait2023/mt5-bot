"""News-calendar sync — fills the gap that left Iconic A-class dead.

PurposeGate (purpose.py / NewsProvider) reads `configs/news_calendar.json` to
decide STRONG purpose (Orange/Red G7 news). That file never existed, so the
A-class gate could never fire — every Iconic signal was capped at B-class.

This module fetches the free Forex Factory weekly calendar (no API key) and
writes it into the schema NewsProvider expects:

    [{"time_utc": "2026-06-04T12:30:00Z", "currency": "USD",
      "impact": "high", "title": "CPI"}]

Self-contained on purpose — does NOT import mt5_bridge.news_filter, because the
mt5_bridge namespace package can shadow into the Windows-only MetaTrader5 import
on the live (Linux) box. The fetch is one URL; we own it here.

Usage:
  python -m trading_agents.iconic.news_sync            # fetch + write once
  python -m trading_agents.iconic.news_sync --quiet    # for cron/timer
  from trading_agents.iconic.news_sync import sync; sync()   # in-process
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("iconic.news_sync")

BASE_DIR      = Path(__file__).resolve().parents[2]
CALENDAR_PATH = BASE_DIR / "configs" / "news_calendar.json"

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Forex Factory impact label -> NewsProvider impact (purpose.IMPACT_OK accepts
# high/red/medium/orange and lowercases). We keep only High + Medium = the
# "Orange + Red" set Navin's rule cares about.
_IMPACT_MAP = {"high": "high", "medium": "medium"}

# G7 only — matches correlation.G7. Other currencies are dropped (no purpose).
_G7 = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CHF"}


def _parse_ff_time(raw: str) -> Optional[datetime]:
    """FF 'date' like '2026-06-04T12:30:00-04:00' -> UTC-aware datetime."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fetch_ff_events(timeout: int = 10) -> list[dict]:
    """Raw Forex Factory weekly events (list of dicts), or [] on failure."""
    try:
        resp = requests.get(FF_CALENDAR_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("FF calendar fetch failed: %s", e)
        return []


def to_iconic_calendar(ff_events: list[dict]) -> list[dict]:
    """Transform FF events into the NewsProvider schema (G7, high/medium only)."""
    out: list[dict] = []
    for ev in ff_events:
        impact = str(ev.get("impact", "")).lower()
        if impact not in _IMPACT_MAP:
            continue
        ccy = str(ev.get("country", "")).upper()
        if ccy not in _G7:
            continue
        dt = _parse_ff_time(ev.get("date", ""))
        if dt is None:
            continue
        out.append({
            "time_utc": dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "currency": ccy,
            "impact":   _IMPACT_MAP[impact],
            "title":    ev.get("title", ""),
        })
    out.sort(key=lambda e: e["time_utc"])
    return out


def sync(*, path: Path = CALENDAR_PATH) -> int:
    """Fetch + write the iconic news calendar. Returns event count written.

    On fetch failure, leaves any existing file untouched (returns -1) so a
    transient network blip doesn't blank out the A-class gate.
    """
    ff = fetch_ff_events()
    if not ff:
        log.warning("no FF events fetched — leaving %s untouched", path.name)
        return -1
    events = to_iconic_calendar(ff)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    log.info("wrote %d G7 high/medium events -> %s", len(events), path)
    return len(events)


def main() -> None:
    import argparse
    import sys
    p = argparse.ArgumentParser(description="Sync Iconic news calendar from Forex Factory")
    p.add_argument("--quiet", action="store_true", help="only log warnings/errors")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(asctime)s  %(levelname)s  %(message)s")
    n = sync()
    if n >= 0 and not args.quiet:
        events = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
        print(f"\n{n} events written. Next 10:")
        for e in events[:10]:
            print(f"  {e['time_utc']}  {e['currency']:4s} {e['impact']:7s} {e['title']}")


if __name__ == "__main__":
    main()
