"""Purpose gate — Urban Forex "you need a reason" rule.

Per Navin (Urban Forex, Iconic 2022):
  STRONG purpose = Orange or Red G7 news event within ±60 min.
  WEAK   purpose = Within 90 min of a major session open (London/NY/Frankfurt)
                   OR inside the London↔NY overlap window.
  NO purpose     = Anywhere else during the session with no news → C-class.
                   Being "in the London session" alone is NOT purpose.

Why the distinction matters for class:
  A-class: requires STRONG purpose (real news driving the move).
  B-class: WEAK purpose is sufficient if the other filters agree.
  C-class: no purpose of either kind → stand aside.

PurposeResult now exposes .strong (news-driven) and .weak (session-open/overlap)
so confluence.py can enforce the A-class stricter gate.
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
    ok: bool      # True if strong OR weak purpose (any gate fires)
    strong: bool  # True only for Orange/Red G7 news (A-class requires this)
    sources: list[str]
    session_ok: bool   # weak: near session open or in overlap
    news_ok: bool      # strong: orange/red G7 news within window


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
    def __init__(self, news_provider: Optional[NewsProvider] = None,
                 open_window_min: int = SESSION_OPEN_WINDOW_MIN):
        self.news = news_provider or NewsProvider()
        self._open_window_min = open_window_min

    def evaluate(self, symbol: str, now: Optional[datetime] = None) -> PurposeResult:
        now = now or datetime.now(timezone.utc)
        sources: list[str] = []

        # STRONG purpose: Orange/Red G7 news
        base, quote = split_pair(symbol)
        ccys = {c for c in (base, quote) if c in G7}
        events = self.news.active(ccys, now) if ccys else []
        news_ok = bool(events)
        for e in events:
            impact_label = "🔴" if e["impact"] in ("high", "red") else "🟠"
            sources.append(f"{impact_label} {e['currency']} {e['impact']} ({e['title'] or 'news'})")

        # WEAK purpose: near session open or in London↔NY overlap
        # NOT "being in the session" — that is too broad and not Navin's rule.
        session_ok, sess_label = self._session_purpose(now, self._open_window_min)
        # Asia session opens (Wellington/Tokyo) count as weak purpose for commodity ccys
        if not session_ok:
            session_ok, sess_label = self._asia_session_purpose(
                symbol, now, self._open_window_min)
        if session_ok and not news_ok:
            sources.append(f"{sess_label} (weak — session open/overlap)")
        elif session_ok:
            sources.append(sess_label)

        ok     = news_ok or session_ok
        strong = news_ok   # A-class gate requires this
        return PurposeResult(ok=ok, strong=strong, sources=sources,
                             session_ok=session_ok, news_ok=news_ok)

    @staticmethod
    def _session_purpose(now: datetime,
                         window_min: int = SESSION_OPEN_WINDOW_MIN) -> tuple[bool, str]:
        """True near London/NY open window or inside London-NY overlap.

        Open times (UTC, DST heuristic months 3-10 = summer):
          London: 07:00 summer / 08:00 winter
          New York: 13:00 summer / 14:00 winter
        London-NY overlap (~13:00-17:00 UTC) treated as weak purpose even
        without a session-open event — high institutional participation window.

        Being anywhere else "in the session" is NOT purpose per Navin.
        Scalp mode: pass window_min=60 to restrict to the tighter open window.
        """
        # No session opens on weekends
        if now.weekday() >= 5:
            return False, ""

        # London-NY overlap: use sessions helper; fall back to hour check
        try:
            from ..alpha_desk.sessions import is_overlap
            in_overlap = is_overlap(now)
        except Exception:
            in_overlap = 13 <= now.hour < 17

        if in_overlap:
            return True, "London-NY overlap"

        # DST heuristic: months 3-10 inclusive = clocks forward
        is_summer = 3 <= now.month <= 10
        london_open_h = 7 if is_summer else 8
        ny_open_h     = 13 if is_summer else 14

        now_min = now.hour * 60 + now.minute
        for open_h, label in ((london_open_h, "London open"),
                              (ny_open_h,     "New York open")):
            mins_since = now_min - open_h * 60
            if 0 <= mins_since <= window_min:
                return True, f"{label} +{mins_since:.0f}min"

        return False, ""

    @staticmethod
    def _asia_session_purpose(symbol: str, now: datetime,
                              window_min: int) -> tuple[bool, str]:
        """Wellington/Sydney/Tokyo opens for NZD, AUD, JPY pairs.

        These currencies have primary institutional participation during Asia
        session, not London/NY. Treating Wellington/Tokyo opens as weak purpose
        for these pairs matches Navin's 'you need a reason' intent.

        Open times (UTC, DST heuristic months 3-10 = summer):
          Wellington/Sydney: 22:00 summer / 21:00 winter
          Tokyo:             00:00 summer / 23:00 winter (previous-day midnight)
        """
        from .correlation import split_pair
        ASIA_CCYS = {"NZD", "AUD", "JPY"}
        base, quote = split_pair(symbol)
        if not (base in ASIA_CCYS or quote in ASIA_CCYS):
            return False, ""
        if now.weekday() >= 5:
            return False, ""

        is_summer = 3 <= now.month <= 10
        wellington_h = 22 if is_summer else 21
        tokyo_h      = 0  if is_summer else 23   # midnight UTC

        now_min = now.hour * 60 + now.minute
        for open_h, label in ((wellington_h, "Wellington/Sydney open"),
                              (tokyo_h,      "Tokyo open")):
            open_min = open_h * 60
            # Modulo handles midnight boundary (e.g. now=00:30, open=00:00 → delta=30)
            delta = (now_min - open_min) % (24 * 60)
            if 0 <= delta <= window_min:
                return True, f"{label} +{delta:.0f}min"

        return False, ""
