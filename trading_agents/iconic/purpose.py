"""Purpose gate — Urban Forex "you need a reason" rule.

A high-volume move only travels if it has a Purpose: a major session OPEN, or a
scheduled medium/high-impact (orange/red) news event on a G7 currency. No
purpose → the move drifts and dies → don't trade (it stays C-class).

Sessions reuse the DST-aware alpha_desk.sessions module. News is pluggable: a
JSON calendar file (configs/news_calendar.json) feeds the default provider; wire
a live ForexFactory/FXStreet fetcher into NewsProvider later without touching
callers.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .correlation import G7, split_pair

log = logging.getLogger("IconicPurpose")

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CALENDAR = BASE_DIR / "configs" / "news_calendar.json"

SESSION_OPEN_WINDOW_MIN = 90    # "near a session open" = within this many min after open
NEWS_WINDOW_MIN         = 60    # news is in play within ± this many min
IMPACT_OK = ("high", "red", "medium", "orange")   # course: orange + red only


@dataclass
class PurposeResult:
    ok: bool
    sources: list[str]          # human-readable purpose reasons
    session_ok: bool
    news_ok: bool


class NewsProvider:
    """Loads orange/red G7 events from a JSON calendar.

    Schema: [{"time_utc": "2026-05-21T12:30:00Z", "currency": "USD",
              "impact": "high", "title": "CPI"}].
    Missing/blank file → no news (news_ok stays False; session can still carry).
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_CALENDAR
        self._events: list[dict] = []
        self._mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                self._events = []
                return
            mtime = self.path.stat().st_mtime
            if mtime == self._mtime and self._events:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            out = []
            for ev in data if isinstance(data, list) else []:
                impact = str(ev.get("impact", "")).lower()
                ccy = str(ev.get("currency", "")).upper()
                if impact not in IMPACT_OK or ccy not in G7:
                    continue
                try:
                    t = datetime.fromisoformat(str(ev["time_utc"]).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                out.append({"time": t, "currency": ccy, "impact": impact,
                            "title": ev.get("title", "")})
            self._events = out
            self._mtime = mtime
        except Exception:
            log.exception("news calendar load failed: %s", self.path)
            self._events = []

    def active(self, currencies: set[str], now: datetime,
               window_min: int = NEWS_WINDOW_MIN) -> list[dict]:
        self._load()
        lo = now - timedelta(minutes=window_min)
        hi = now + timedelta(minutes=window_min)
        return [e for e in self._events
                if e["currency"] in currencies and lo <= e["time"] <= hi]


class PurposeGate:
    def __init__(self, news_provider: Optional[NewsProvider] = None):
        self.news = news_provider or NewsProvider()

    def evaluate(self, symbol: str, now: Optional[datetime] = None) -> PurposeResult:
        now = now or datetime.now(timezone.utc)
        sources: list[str] = []

        session_ok, sess_label = self._session_purpose(now)
        if session_ok:
            sources.append(sess_label)

        base, quote = split_pair(symbol)
        ccys = {c for c in (base, quote) if c in G7}
        events = self.news.active(ccys, now) if ccys else []
        news_ok = bool(events)
        for e in events:
            sources.append(f"📰 {e['currency']} {e['impact']} ({e['title'] or 'news'})")

        return PurposeResult(ok=session_ok or news_ok, sources=sources,
                             session_ok=session_ok, news_ok=news_ok)

    @staticmethod
    def _session_purpose(now: datetime) -> tuple[bool, str]:
        """True near a major session open (London/NY/Frankfurt) or in overlap."""
        try:
            from ..alpha_desk.sessions import (is_overlap, current_session,
                                               next_centre_open)
        except Exception:
            return False, ""
        if is_overlap(now):
            return True, "🟢 London↔NY overlap"
        sess = current_session(now)
        # "near an open" = within SESSION_OPEN_WINDOW_MIN after a major centre opened
        for key, label in (("london", "🌅 London open"),
                           ("ny", "🗽 New York open")):
            # next_centre_open returns the NEXT open; previous open = next - 1 day,
            # so check minutes since the most recent open by walking back.
            nxt = next_centre_open(key, now)
            prev = nxt - timedelta(days=1)
            mins_since = (now - prev).total_seconds() / 60
            if 0 <= mins_since <= SESSION_OPEN_WINDOW_MIN:
                return True, label
        if sess in ("london", "ny"):
            return True, f"🕒 {sess.upper()} session"
        return False, ""
