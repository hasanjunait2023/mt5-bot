"""IconicRunner — in-process wrapper for SignalEngine Pass 6.

Called by SignalEngine._scan_once() with the same snapshots+strength that
Alpha Desk already consumed (Pass 5). Zero extra MT5 fetches.

Writes:
  logs/iconic/_iconic_state.json   — latest confluence scores + live signals
  logs/iconic/_iconic_events.jsonl — historical signal event log

Broadcasts:
  ws topic "iconic_signal" — each new A/B trade signal with valid pattern
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("IconicRunner")

BASE_DIR    = Path(__file__).resolve().parents[2]
STATE_PATH  = BASE_DIR / "logs" / "iconic" / "_iconic_state.json"
EVENTS_PATH = BASE_DIR / "logs" / "iconic" / "_iconic_events.jsonl"

WS_TOPIC = "iconic_signal"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class IconicRunner:
    def __init__(self, *, broadcaster=None):
        self.broadcaster = broadcaster
        self._engine = None
        self._scorer = None
        try:
            from .engine import IconicEngine
            self._engine = IconicEngine()
            self._scorer = self._engine.scorer
        except Exception:
            log.exception("IconicEngine unavailable")
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._write_state(running=True, signals_live={}, scores_all={})

    # ── per-tick entry ────────────────────────────────────────────────────
    def consume(self, snapshots: dict, strength: dict) -> None:
        if self._engine is None:
            return
        now = datetime.now(timezone.utc)
        try:
            self._run(snapshots, strength, now)
        except Exception:
            log.exception("IconicRunner tick failed")

    def _run(self, snapshots: dict, strength: dict, now: datetime) -> None:
        # All confluence scores — A/B/C for every symbol (no pattern gate)
        all_scores = self._scorer.classify_group(snapshots, strength, now=now)
        scores_all = {
            sym: {
                "klass":     sc.klass,
                "score":     round(sc.score, 1),
                "side":      sc.side,
                "is_leader": sc.is_leader,
                "reasons":   sc.reasons[:4],
                "flags":     sc.flags[:2],
                "ts":        _utcnow(),
            }
            for sym, sc in all_scores.items()
        }

        # Full trade signals — only A/B with valid Set1/2 pattern
        try:
            signals = self._engine.evaluate(snapshots, strength, now=now)
        except Exception:
            log.exception("IconicEngine.evaluate failed")
            signals = []

        signals_live: dict = {}
        for sig in signals:
            d = sig.to_public()
            signals_live[sig.symbol] = d
            self._append_event(d)
            if self.broadcaster:
                try:
                    self.broadcaster(WS_TOPIC, d)
                except Exception:
                    pass

        self._write_state(running=True, signals_live=signals_live,
                          scores_all=scores_all)

    # ── persistence ───────────────────────────────────────────────────────
    def _write_state(self, *, running: bool,
                     signals_live: dict, scores_all: dict) -> None:
        try:
            STATE_PATH.write_text(json.dumps({
                "running":      running,
                "updated_at":   _utcnow(),
                "signals_live": signals_live,
                "scores_all":   scores_all,
            }, indent=2), encoding="utf-8")
        except Exception:
            log.warning("Failed to write iconic state")

    def _append_event(self, event: dict) -> None:
        try:
            with EVENTS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            log.warning("Failed to append iconic event")
