"""AlphaDeskEngine — orchestrator that consumes SignalEngine snapshots and
produces alpha signals + pre-session briefs.

Wiring: SignalEngine._scan_once() calls `alpha.consume(snapshots, strength)`
at the end of each tick (when self.alpha is not None). This keeps Alpha
Desk on the same MT5 fetch — zero extra data cost.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from .zones      import ZoneTracker
from .liquidity  import LiquidityTracker
from .orderflow  import OrderFlowDetector
from .confluence import ConfluenceScorer, AlphaSignal
from .sessions   import (current_session, BRIEF_CENTRES, BRIEF_OFFSET_MIN,
                          next_centre_open)
from .reports    import generate_session_brief

log = logging.getLogger("AlphaDesk")

BASE_DIR     = Path(__file__).resolve().parents[2]
STATE_PATH   = BASE_DIR / "logs" / "alpha" / "_alpha_state.json"
EVENTS_PATH  = BASE_DIR / "logs" / "alpha" / "_alpha_events.jsonl"
BRIEFS_PATH  = BASE_DIR / "logs" / "alpha" / "_alpha_briefs.jsonl"
CHART_DIR    = BASE_DIR / "logs" / "alpha" / "charts"

TOPIC_BRIEF      = "alpha_brief"
TOPIC_SIGNAL     = "alpha_signal"
TOPIC_CONFLUENCE = "alpha_confluence"


def _should_deliver(category: str) -> bool:
    """Delivery gate wrapper — fail-open if delivery module unavailable."""
    try:
        from ..signal_engine.delivery import should_deliver
        return should_deliver(category)
    except Exception:
        return True


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AlphaDeskEngine:
    def __init__(self, *, broadcaster=None, tracker=None):
        self.broadcaster = broadcaster
        self.tracker     = tracker

        self.zones      = ZoneTracker()
        self.liquidity  = LiquidityTracker()
        self.orderflow  = OrderFlowDetector()
        self.confluence = ConfluenceScorer()

        # ingest cadence — zones/OB only need updating on new H1/H4 bars,
        # but for V1 we update every tick (cheap enough).
        self._last_brief: dict[str, str] = {}    # session_name -> YYYY-MM-DD HH
        self._brief_lock = threading.Lock()

        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHART_DIR.mkdir(parents=True, exist_ok=True)
        self._save_state(running=True)

    # ── per-tick entry ───────────────────────────────────────────────────
    def consume(self, snapshots: dict, strength: dict, *,
                fetch_h4=None):
        """Called by SignalEngine at end of each scan tick.

        snapshots: {symbol: {"tfs": {M1, M3, M15, H1}, "align": ...}}
        strength : {currency: 0..10}
        fetch_h4 : optional callable(symbol) -> pd.DataFrame for H4 zones
                    (skip if None — H1-only zones).
        """
        if not snapshots:
            return
        sess = current_session()

        # 1) Ingest data per symbol into trackers
        for sym, snap in snapshots.items():
            tfs = snap["tfs"]
            try:
                self.zones.ingest(sym, "H1", tfs["H1"])
                if fetch_h4:
                    h4 = fetch_h4(sym)
                    if h4 is not None:
                        self.zones.ingest(sym, "H4", h4)
                self.liquidity.ingest(sym, tfs["H1"], tfs.get("H4"))
                self.orderflow.scan_order_blocks(sym, "H1", tfs["H1"])
            except Exception:
                log.exception("alpha ingest failed: %s", sym)

        # 2) Score + emit per symbol
        all_signals: list[AlphaSignal] = []
        for sym, snap in snapshots.items():
            try:
                events = self.confluence.evaluate(
                    symbol=sym, snapshot=snap, strength=strength,
                    zones=self.zones.zones_for(sym),
                    pools=self.liquidity.pools_for(sym),
                    orderflow=self.orderflow,
                    session=sess,
                )
                all_signals.extend(events)
            except Exception:
                log.exception("alpha evaluate failed: %s", sym)

        for ev in all_signals:
            try:
                self._emit(ev)
            except Exception:
                log.exception("alpha emit failed")

        # 3) Pre-session brief — fire once per session-day, ~30 min before open
        try:
            self._maybe_emit_brief(snapshots, strength)
        except Exception:
            log.exception("brief emit failed")

        self._save_state(running=True)

    # ── emit ─────────────────────────────────────────────────────────────
    def _emit(self, ev: AlphaSignal):
        # JSONL log
        try:
            EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = ev.to_public()
            with EVENTS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            log.exception("alpha events append failed")

        # render chart
        png = None
        chart_path = None
        if ev.df_for_chart is not None:
            try:
                from ..signal_engine.chart import render_signal_chart
                png = render_signal_chart(ev.df_for_chart, symbol=ev.symbol,
                                          timeframe_label=ev.timeframe,
                                          signal_type=f"ALPHA · {ev.type.upper()}",
                                          side=ev.side, bars=120)
                f = CHART_DIR / f"alpha-{ev.type}-{ev.symbol}-{int(time.time()*1000)}.png"
                f.write_bytes(png)
                chart_path = str(f.relative_to(BASE_DIR)).replace("\\", "/")
            except Exception:
                log.exception("alpha chart failed")

        # Telegram (delivery-gated)
        topic = TOPIC_CONFLUENCE if ev.type == "confluence" else TOPIC_SIGNAL
        deliver = _should_deliver(topic)
        if deliver:
            caption = self._format_caption(ev)
            try:
                from .. import telegram_hq
                if png:
                    telegram_hq.send_photo(
                        topic, png, caption,
                        dedupe_key=f"alpha|{ev.type}|{ev.symbol}|{ev.side}",
                    )
                else:
                    telegram_hq.send(topic, caption, level="INFO")
            except Exception:
                log.exception("alpha telegram send failed")

        # WS push (gated)
        if deliver and self.broadcaster:
            wpayload = ev.to_public()
            wpayload["chart_path"] = chart_path
            if png and len(png) < 250_000:
                wpayload["chart_b64"] = base64.b64encode(png).decode("ascii")
            try:
                self.broadcaster({"type": "alpha_signal", "data": wpayload})
            except Exception:
                log.exception("alpha ws broadcast failed")

        # Paper-trade tracker (alpha system)
        if self.tracker is not None:
            try:
                t_payload = {
                    "id": f"alpha-{ev.type}-{ev.symbol}-{int(time.time()*1000)}",
                    "type": ev.type, "symbol": ev.symbol, "side": ev.side,
                    "price": ev.price, "verdict": ev.tier,
                    "score": ev.score, "correlation": "N/A",
                }
                # tracker only knows {alignment, cross, touch, stacked} timeouts.
                # Map alpha types onto closest equivalent so it tracks them.
                map_to_tracker = {
                    "sweep":       "cross",
                    "zone":        "touch",
                    "ob_mit":      "touch",
                    "absorption":  "cross",
                    "confluence":  "stacked",
                }
                t_payload["type"] = map_to_tracker.get(ev.type, "cross")
                self.tracker.on_signal(t_payload, system="alpha")
            except Exception:
                log.exception("alpha tracker on_signal failed")

        log.info("ALPHA  %s  %s  %s  %s  score=%.0f  tier=%s",
                 ev.type, ev.symbol, ev.side, ev.timeframe, ev.score, ev.tier)

    # ── caption ─────────────────────────────────────────────────────────
    @staticmethod
    def _format_caption(ev: AlphaSignal) -> str:
        sym_pretty = (ev.symbol[:3] + "/" + ev.symbol[3:]) if (len(ev.symbol) == 6 and ev.symbol.isalpha()) else ev.symbol
        arrow = "🟢" if ev.side == "BUY" else ("🔴" if ev.side == "SELL" else "⚠️")
        head = {
            "sweep":       ("🌊", "LIQUIDITY SWEEP"),
            "zone":        ("🧱", "ZONE REACTION"),
            "ob_mit":      ("⚙️", "ORDER BLOCK MITIGATED"),
            "absorption":  ("🩻", "ABSORPTION DETECTED"),
            "confluence":  ("💎", "CONFLUENCE STACK"),
        }.get(ev.type, ("💎", ev.type.upper()))
        emoji, htext = head

        dp = 3 if (ev.symbol.endswith("JPY") or "OIL" in ev.symbol) else 5
        bar = "█" * int(ev.score / 10) + "░" * (10 - int(ev.score / 10))
        lines = [
            f"{emoji} *{htext}* · `{sym_pretty}`",
            "",
            f"Direction : {arrow} *{ev.side}*",
            f"Session   : *{ev.session.upper()}*",
            f"Tier      : *{ev.tier}*",
            f"Score     : `{bar}` *{ev.score:.0f}/100*",
            "",
            "*Confluence:*",
            *ev.reasons,
            "",
            f"💰 Price : `{ev.price:.{dp}f}`",
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} UTC · "
            f"{(datetime.now(timezone.utc) + timedelta(hours=6)).strftime('%H:%M')} BD · "
            f"`{ev.detect_ms:.0f} ms`",
            "",
            f"🇧🇩 _Institutional-grade confluence — {ev.side} bias_",
        ]
        return "\n".join(lines)

    # ── pre-session brief ───────────────────────────────────────────────
    def _maybe_emit_brief(self, snapshots: dict, strength: dict):
        now = datetime.now(timezone.utc)
        for sname, centre_key in BRIEF_CENTRES.items():
            open_utc = next_centre_open(centre_key, now)
            mins_to_open = (open_utc - now).total_seconds() / 60
            # fire window: between BRIEF_OFFSET_MIN and 0 min before open
            if 0 < mins_to_open <= BRIEF_OFFSET_MIN:
                key = f"{open_utc.strftime('%Y-%m-%d')}|{sname}"
                with self._brief_lock:
                    if self._last_brief.get(sname) == key:
                        continue
                    self._last_brief[sname] = key
                self._fire_brief(sname, snapshots, strength)

    def _fire_brief(self, sname: str, snapshots: dict, strength: dict):
        # Build pending setups list from recent confluence cache
        setups: list[dict] = []
        for sym, recent in self.confluence._recent.items():
            if not recent:
                continue
            # take latest signal per symbol
            recent.sort(key=lambda r: r[0], reverse=True)
            ts, sig_type, side = recent[0]
            if time.time() - ts > 30 * 60:
                continue
            score = 75    # placeholder; full version pulls from event store
            setups.append({"symbol": sym, "side": side, "score": score,
                           "tier": "STRONG 🟢", "reasons": [f"[✓] Recent {sig_type} fired"]})

        body = generate_session_brief(
            session=sname, snapshots=snapshots, strength=strength,
            zones_tracker=self.zones, liquidity_tracker=self.liquidity,
            orderflow_detector=self.orderflow,
            pending_setups=setups,
        )

        if _should_deliver(TOPIC_BRIEF):
            try:
                from .. import telegram_hq
                telegram_hq.send(TOPIC_BRIEF, body, level="INFO",
                                 title=f"📰 {sname.upper()} BRIEF")
            except Exception:
                log.exception("brief telegram send failed")

        try:
            BRIEFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with BRIEFS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _utcnow_iso(), "session": sname,
                                    "body": body}, ensure_ascii=False) + "\n")
        except Exception:
            log.exception("brief log failed")

        log.info("ALPHA BRIEF emitted for session=%s", sname)

    # ── persistence ─────────────────────────────────────────────────────
    def _save_state(self, *, running: bool):
        try:
            state = {
                "running": running,
                "updated_at": _utcnow_iso(),
                "zones_snapshot":     self.zones.snapshot(),
                "liquidity_snapshot": self.liquidity.snapshot(),
                "orderflow_snapshot": self.orderflow.snapshot(),
                "session": current_session(),
            }
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            tmp.replace(STATE_PATH)
        except Exception:
            log.debug("alpha state save failed", exc_info=True)
