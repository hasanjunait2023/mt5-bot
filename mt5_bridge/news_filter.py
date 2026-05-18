# encoding: utf-8
"""
news_filter.py — Forex Factory economic calendar integration.
Fetches weekly events, caches to disk, provides blackout window checks.
No API key required. Free endpoint.
"""
import json
import time
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_PATH      = Path(__file__).parent / "_ff_calendar_cache.json"
CACHE_TTL_SEC   = 6 * 3600   # refresh every 6 hours

# Forex Factory uses country names that map directly to currency codes
# e.g. "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"
HIGH_IMPACT = "High"

# Symbols where only the USD side matters (metals/crypto)
COMMODITY_QUOTE_ONLY = {"XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD"}


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> Optional[List[Dict]]:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) > CACHE_TTL_SEC:
            return None
        return data["events"]
    except Exception:
        return None


def _save_cache(events: List[Dict]) -> None:
    try:
        CACHE_PATH.write_text(
            json.dumps({"ts": time.time(), "events": events}, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass


# ── Calendar fetch ─────────────────────────────────────────────────────────────

def fetch_ff_calendar(force_refresh: bool = False) -> List[Dict]:
    """
    Fetch and cache the Forex Factory weekly calendar.
    Returns list of event dicts:
      {title, country, date, impact, forecast, previous}
    impact values: "High", "Medium", "Low", "Non-Economic", "Holiday"
    """
    if not force_refresh:
        cached = _load_cache()
        if cached is not None:
            return cached

    if not HAS_REQUESTS:
        print("[news_filter] WARNING: 'requests' not installed. News filter disabled.")
        return []

    try:
        resp = requests.get(FF_CALENDAR_URL, timeout=10)
        resp.raise_for_status()
        events = resp.json()
        _save_cache(events)
        return events
    except Exception as e:
        print(f"[news_filter] Failed to fetch FF calendar: {e}")
        cached = _load_cache()
        return cached if cached else []


# ── Currency extraction ────────────────────────────────────────────────────────

def get_pair_currencies(symbol: str) -> List[str]:
    """
    Extract the two currency codes from a symbol string.
    EURUSD -> ["EUR", "USD"]
    XAUUSD -> ["USD"]          (XAU is a commodity, only USD side matters)
    BTCUSD -> ["USD"]
    """
    sym = symbol.upper().replace(".", "")
    if sym in COMMODITY_QUOTE_ONLY or sym[:3] in ("XAU", "XAG", "BTC", "ETH", "LTC"):
        return [sym[-3:]]
    if len(sym) >= 6:
        return [sym[:3], sym[3:6]]
    return [sym]


# ── Blackout check ─────────────────────────────────────────────────────────────

def _parse_event_time(event: Dict) -> Optional[datetime]:
    """
    Parse the 'date' field from a FF event into a UTC-aware datetime.
    FF dates look like: "2026-05-17T12:30:00-04:00"
    """
    raw = event.get("date", "")
    if not raw:
        return None
    try:
        # Python 3.7+ fromisoformat doesn't handle all ISO 8601 variants
        # Normalize: replace Z with +00:00
        raw = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_news_blackout(
    ts: datetime,
    currencies: List[str],
    buffer_minutes: int = 30,
    events: Optional[List[Dict]] = None,
) -> bool:
    """
    Return True if `ts` falls within ±buffer_minutes of any HIGH-impact
    event for any currency in `currencies`.

    ts         : timezone-aware UTC datetime (or naive treated as UTC)
    currencies : list of ISO currency codes, e.g. ["EUR", "USD"]
    events     : pre-fetched event list (optional; fetched from cache if None)
    """
    if not currencies:
        return False

    if events is None:
        events = fetch_ff_calendar()

    if not events:
        return False

    # Ensure ts is UTC-aware
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)

    window = timedelta(minutes=buffer_minutes)
    currencies_upper = {c.upper() for c in currencies}

    for ev in events:
        if ev.get("impact", "") != HIGH_IMPACT:
            continue
        country = ev.get("country", "").upper()
        if country not in currencies_upper:
            continue
        ev_time = _parse_event_time(ev)
        if ev_time is None:
            continue
        if abs(ts - ev_time) <= window:
            return True

    return False


# ── Convenience functions ──────────────────────────────────────────────────────

def get_high_impact_events(
    currencies: List[str],
    events: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Return all HIGH-impact events for the given currency list."""
    if events is None:
        events = fetch_ff_calendar()
    currencies_upper = {c.upper() for c in currencies}
    return [
        ev for ev in events
        if ev.get("impact") == HIGH_IMPACT
        and ev.get("country", "").upper() in currencies_upper
    ]


def preload_calendar() -> int:
    """Force-fetch the calendar and return the number of high-impact events."""
    events = fetch_ff_calendar(force_refresh=True)
    high = [ev for ev in events if ev.get("impact") == HIGH_IMPACT]
    print(f"[news_filter] Loaded {len(events)} events ({len(high)} high-impact)")
    return len(high)


# ── CLI test ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("Fetching Forex Factory calendar...")
    n = preload_calendar()
    events = fetch_ff_calendar()

    print(f"\nAll HIGH-impact events this week:")
    for ev in events:
        if ev.get("impact") == HIGH_IMPACT:
            print(f"  {ev.get('date','?')[:16]}  {ev.get('country','?'):4s}  {ev.get('title','?')}")

    # Test blackout for EURUSD right now
    now_utc = datetime.now(timezone.utc)
    currs   = get_pair_currencies("EURUSD")
    result  = is_news_blackout(now_utc, currs, buffer_minutes=30, events=events)
    print(f"\nEURUSD news blackout right now ({now_utc.strftime('%H:%M UTC')}): {result}")
    print("Done.")
