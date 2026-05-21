"""Improved Signal Detector — Phase 1 quality gates + sequence detection.

Runs alongside the classic SignalEngine, consuming the same per-tick snapshots
(no extra MT5 fetches) but applying stricter rules:

ALIGNMENT
  - Boolean alignment as before
  - PLUS: H1 EMA200 slope must be in alignment direction (not flat)
  - PLUS: H1 distance from EMA200 in ATRs >= 0.5 (real extension, not noise)
  - Strength score 0-100 = slope_pts + per-TF distance_pts
  - Skip emit unless score >= 60

CROSS
  - 9/15 cross on M1 in alignment direction
  - PLUS: cross-bar body ratio >= 50% (no doji crosses)
  - PLUS: M1 RSI(14) in [25, 75] (no exhaustion entries)
  - PLUS: distance from EMA200 >= 0.3 ATR (room to run)
  - Tracks cross-back failure: if reversed within 2 bars → "CROSS FAILED" alert

TOUCH
  - M3 wick touches EMA200 in alignment direction
  - PLUS: body close stays in alignment direction (wick-only, not break-through)
  - PLUS: waits 1 more candle, only fires if rejection candle closes back in trend
  - PLUS: touch counter — if 3rd+ touch in 4h, downgrade verdict
  - Anti-spam: skip if same symbol touched within last 30 min

STACKED SETUP
  - When alignment + touch + cross all fire on same symbol within 30 min
  - Emit single super-signal `STACKED SETUP 🔥🔥🔥` to improved topic
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("ImprovedDetector")

ALIGN_MIN_SCORE   = 60.0     # min strength score to emit alignment
CROSS_BODY_MIN    = 0.50     # min body/range ratio for cross bar
CROSS_RSI_LO      = 25.0
CROSS_RSI_HI      = 75.0
CROSS_MIN_ATR_GAP = 0.30     # min distance from EMA200 (in ATRs) for cross
TOUCH_ANTISPAM_S  = 30 * 60  # 30 min
TOUCH_COUNT_WINDOW = 4 * 3600  # 4h
TOUCH_COUNT_DOWNGRADE = 3
SEQUENCE_WINDOW_S = 30 * 60   # 30 min for alignment→touch→cross


@dataclass
class ImprovedSignal:
    type: str          # alignment | cross | touch | stacked | cross_failed
    symbol: str
    side: str          # BUY | SELL
    timeframe: str
    price: float
    ema9: float
    ema15: float
    ema200: float
    score: float       # 0..100 quality
    verdict: str       # PRIME 🔥 / STRONG 🟢 / OK 🟡
    notes: list[str]   # checklist items already passed
    detect_ms: float
    df_for_chart: pd.DataFrame   # which TF df to render


def _rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    up = delta.clip(lower=0)
    dn = -delta.clip(upper=0)
    ru = up.ewm(alpha=1/period, adjust=False).mean()
    rd = dn.ewm(alpha=1/period, adjust=False).mean()
    rs = ru / rd.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return latest ATR value."""
    h = df["high"]; l = df["low"]; c = df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1])


class ImprovedDetector:
    def __init__(self):
        # cross-back tracking
        self._open_crosses: dict[str, dict] = {}    # symbol -> {bar_ts, side, bars_since}
        # touch state
        self._touch_history: dict[str, list[float]] = {}   # symbol -> [touch_ts,...]
        self._pending_touch: dict[str, dict] = {}          # symbol -> {bar_ts, side, ema200}
        # alignment state for sequence detection
        self._last_align_emit: dict[str, dict] = {}        # symbol -> {ts, side}
        self._last_touch_emit: dict[str, dict] = {}        # symbol -> {ts, side}
        self._last_cross_emit: dict[str, dict] = {}        # symbol -> {ts, side}
        self._last_stacked: dict[str, float] = {}          # symbol -> ts
        # alignment dedupe
        self._last_align_state: dict[str, str] = {}        # symbol -> "bull"/"bear"/"none"

    # ── per-tick entry ───────────────────────────────────────────────────
    def evaluate(self, snapshots: dict, strength: dict[str, float]) -> list[ImprovedSignal]:
        events: list[ImprovedSignal] = []
        now_ts = time.time()

        for symbol, snap in snapshots.items():
            tfs, align = snap["tfs"], snap["align"]
            try:
                # ALIGNMENT — improved
                ev = self._eval_alignment(symbol, tfs, align, now_ts)
                if ev: events.append(ev)

                if align == "none":
                    continue

                # CROSS — improved
                ev = self._eval_cross(symbol, tfs, align, now_ts)
                if ev: events.append(ev)

                # Cross-back guard — emit "CROSS FAILED" if reversed
                ev = self._check_cross_failure(symbol, tfs, now_ts)
                if ev: events.append(ev)

                # TOUCH — improved (with 1-bar rejection wait)
                ev = self._eval_touch(symbol, tfs, align, now_ts)
                if ev: events.append(ev)

                # SEQUENCE — alignment+touch+cross within 30 min
                ev = self._check_sequence(symbol, tfs, align, now_ts)
                if ev: events.append(ev)
            except Exception:
                log.exception("improved eval failed: %s", symbol)
        return events

    # ── alignment ────────────────────────────────────────────────────────
    def _eval_alignment(self, symbol, tfs, align, now_ts) -> Optional[ImprovedSignal]:
        prev = self._last_align_state.get(symbol, "none")
        self._last_align_state[symbol] = align
        if align not in ("bull", "bear") or prev == align:
            return None

        side = "BUY" if align == "bull" else "SELL"
        score = 0.0
        notes: list[str] = []

        # H1 EMA200 slope check (25 pts)
        h1 = tfs["H1"]
        slope = float(h1["ema200"].iloc[-1] - h1["ema200"].iloc[-20])
        slope_ok = (slope > 0 and align == "bull") or (slope < 0 and align == "bear")
        if slope_ok:
            score += 25
            notes.append(f"[✓] H1 EMA200 slope {('↑' if slope > 0 else '↓')} (trend, not flat)")
        else:
            notes.append(f"[✗] H1 EMA200 flat — possible range")

        # Per-TF distance-in-ATR (75 pts total, 18.75 each)
        for label in ("M1", "M3", "M15", "H1"):
            df = tfs[label]
            atr = _atr(df, 14)
            last = df.iloc[-1]
            dist_atr = abs(last["close"] - last["ema200"]) / atr if atr > 0 else 0
            if dist_atr >= 0.5:
                score += 18.75
                notes.append(f"[✓] {label} dist {dist_atr:.1f} ATR (>= 0.5)")
            else:
                notes.append(f"[~] {label} dist {dist_atr:.1f} ATR (weak)")

        score = round(score, 1)
        if score < ALIGN_MIN_SCORE:
            return None

        verdict = "PRIME 🔥" if score >= 85 else "STRONG 🟢" if score >= 70 else "OK 🟡"
        last = tfs["H1"].iloc[-1]
        ev = ImprovedSignal(
            type="alignment", symbol=symbol, side=side, timeframe="H1",
            price=float(last["close"]),
            ema9=float(last["ema9"]), ema15=float(last["ema15"]),
            ema200=float(last["ema200"]),
            score=score, verdict=verdict, notes=notes,
            detect_ms=0.0, df_for_chart=tfs["H1"],
        )
        self._last_align_emit[symbol] = {"ts": now_ts, "side": side}
        return ev

    # ── cross ────────────────────────────────────────────────────────────
    def _eval_cross(self, symbol, tfs, align, now_ts) -> Optional[ImprovedSignal]:
        m1 = tfs["M1"]
        if len(m1) < 3:
            return None
        a, b = m1.iloc[-2], m1.iloc[-1]
        prev_up = a["ema9"] > a["ema15"]
        curr_up = b["ema9"] > b["ema15"]
        if prev_up == curr_up:
            return None
        cross_dir = "up" if curr_up else "down"
        want = "up" if align == "bull" else "down"
        if cross_dir != want:
            return None

        bar_ts = int(b["time"].timestamp())
        existing = self._open_crosses.get(symbol)
        if existing and existing.get("bar_ts") == bar_ts:
            return None

        # Quality gates
        notes: list[str] = []
        score = 0.0

        # Body ratio
        body = abs(b["close"] - b["open"])
        rng = max(b["high"] - b["low"], 1e-9)
        body_ratio = body / rng
        if body_ratio >= CROSS_BODY_MIN:
            score += 30
            notes.append(f"[✓] Body ratio {body_ratio:.0%} (>= 50%)")
        else:
            notes.append(f"[✗] Body ratio {body_ratio:.0%} (doji-ish)")
            return None    # hard gate

        # RSI not extreme
        rsi_v = float(_rsi(m1["close"]).iloc[-1])
        if CROSS_RSI_LO <= rsi_v <= CROSS_RSI_HI:
            score += 25
            notes.append(f"[✓] RSI(14) `{rsi_v:.1f}` not extreme")
        else:
            notes.append(f"[✗] RSI(14) `{rsi_v:.1f}` extreme")
            return None    # hard gate

        # Distance from EMA200
        atr = _atr(m1, 14)
        dist_atr = abs(b["close"] - b["ema200"]) / atr if atr > 0 else 0
        if dist_atr >= CROSS_MIN_ATR_GAP:
            score += 25
            notes.append(f"[✓] Distance from EMA200 {dist_atr:.1f} ATR (room to run)")
        else:
            notes.append(f"[~] Close to EMA200 ({dist_atr:.1f} ATR)")
            score += 10

        # Alignment 4/4 implied
        notes.append(f"[✓] {'Bullish' if align == 'bull' else 'Bearish'} alignment 4/4")
        score += 20

        side = "BUY" if cross_dir == "up" else "SELL"
        verdict = "PRIME 🔥" if score >= 90 else "STRONG 🟢" if score >= 75 else "OK 🟡"

        # Register for cross-back tracking
        self._open_crosses[symbol] = {
            "bar_ts": bar_ts, "side": side, "bars_since": 0,
            "entry_idx": len(m1) - 1,
        }

        ev = ImprovedSignal(
            type="cross", symbol=symbol, side=side, timeframe="M1",
            price=float(b["close"]),
            ema9=float(b["ema9"]), ema15=float(b["ema15"]),
            ema200=float(b["ema200"]),
            score=round(score, 1), verdict=verdict, notes=notes,
            detect_ms=0.0, df_for_chart=m1,
        )
        self._last_cross_emit[symbol] = {"ts": now_ts, "side": side}
        return ev

    def _check_cross_failure(self, symbol, tfs, now_ts) -> Optional[ImprovedSignal]:
        oc = self._open_crosses.get(symbol)
        if not oc:
            return None
        m1 = tfs["M1"]
        last = m1.iloc[-1]
        last_bar_ts = int(last["time"].timestamp())
        if last_bar_ts == oc["bar_ts"]:
            return None    # same bar — nothing to check
        oc["bars_since"] += 1

        # If reversed within 2 bars, emit failure
        curr_up = last["ema9"] > last["ema15"]
        cross_back = (oc["side"] == "BUY" and not curr_up) or (oc["side"] == "SELL" and curr_up)
        if cross_back and oc["bars_since"] <= 2:
            ev = ImprovedSignal(
                type="cross_failed", symbol=symbol,
                side="EXIT", timeframe="M1",
                price=float(last["close"]),
                ema9=float(last["ema9"]), ema15=float(last["ema15"]),
                ema200=float(last["ema200"]),
                score=0.0, verdict="EXIT ⚠️",
                notes=[f"[!] Previous {oc['side']} cross reversed in {oc['bars_since']} bar(s)",
                       f"[!] Exit if you took the trade"],
                detect_ms=0.0, df_for_chart=m1,
            )
            del self._open_crosses[symbol]
            return ev

        # Cleanup after 3 bars
        if oc["bars_since"] > 3:
            del self._open_crosses[symbol]
        return None

    # ── touch (with rejection-bar wait) ──────────────────────────────────
    def _eval_touch(self, symbol, tfs, align, now_ts) -> Optional[ImprovedSignal]:
        m3 = tfs["M3"]
        if len(m3) < 2:
            return None
        b = m3.iloc[-1]
        bar_ts = int(b["time"].timestamp())

        # Stage 2: pending touch awaiting rejection-bar confirmation
        pending = self._pending_touch.get(symbol)
        if pending and pending["bar_ts"] != bar_ts:
            # new bar arrived — does it close in alignment direction?
            side = pending["side"]
            close_ok = (side == "BUY" and b["close"] > b["open"]) or \
                       (side == "SELL" and b["close"] < b["open"])
            del self._pending_touch[symbol]
            if not close_ok:
                return None

            # touch count for downgrade
            hist = self._touch_history.setdefault(symbol, [])
            hist[:] = [t for t in hist if now_ts - t < TOUCH_COUNT_WINDOW]
            hist.append(now_ts)
            touch_count = len(hist)

            notes: list[str] = [
                f"[✓] {'Bullish' if align == 'bull' else 'Bearish'} alignment 4/4",
                f"[✓] Wick touched EMA200 (body stayed in trend)",
                f"[✓] Rejection candle closed {'up' if side == 'BUY' else 'down'} (confirmed)",
                f"[~] Touch count last 4h: {touch_count}",
            ]
            score = 80.0
            if touch_count >= TOUCH_COUNT_DOWNGRADE:
                score -= 25.0
                notes.append(f"[!] Trend tiring ({touch_count} touches — downgraded)")
            verdict = "PRIME 🔥" if score >= 80 else "STRONG 🟢" if score >= 65 else "OK 🟡"

            ev = ImprovedSignal(
                type="touch", symbol=symbol, side=side, timeframe="M3",
                price=float(b["close"]),
                ema9=float(b["ema9"]), ema15=float(b["ema15"]),
                ema200=float(b["ema200"]),
                score=round(score, 1), verdict=verdict, notes=notes,
                detect_ms=0.0, df_for_chart=m3,
            )
            self._last_touch_emit[symbol] = {"ts": now_ts, "side": side}
            return ev

        # Stage 1: detect wick-only touch on current bar
        if pending and pending["bar_ts"] == bar_ts:
            return None   # still waiting on rejection bar

        if not (b["low"] <= b["ema200"] <= b["high"]):
            return None
        # wick-only: body must not cross EMA200
        body_lo = min(b["open"], b["close"])
        body_hi = max(b["open"], b["close"])
        if body_lo <= b["ema200"] <= body_hi:
            return None    # body crossed = trend break, not touch

        side = "BUY" if align == "bull" else "SELL"

        # anti-spam: same symbol touched in last 30 min?
        last_touch = self._last_touch_emit.get(symbol)
        if last_touch and now_ts - last_touch["ts"] < TOUCH_ANTISPAM_S:
            return None

        # body must stay in trend direction
        body_in_trend = (align == "bull" and b["close"] > b["ema200"]) or \
                       (align == "bear" and b["close"] < b["ema200"])
        if not body_in_trend:
            return None

        # register pending — wait for next bar's rejection
        self._pending_touch[symbol] = {"bar_ts": bar_ts, "side": side,
                                       "ema200": float(b["ema200"])}
        return None

    # ── sequence detection ──────────────────────────────────────────────
    def _check_sequence(self, symbol, tfs, align, now_ts) -> Optional[ImprovedSignal]:
        last_stack = self._last_stacked.get(symbol, 0)
        if now_ts - last_stack < SEQUENCE_WINDOW_S:
            return None

        a = self._last_align_emit.get(symbol)
        t = self._last_touch_emit.get(symbol)
        c = self._last_cross_emit.get(symbol)
        if not (a and t and c):
            return None
        # all three within window?
        oldest = min(a["ts"], t["ts"], c["ts"])
        if now_ts - oldest > SEQUENCE_WINDOW_S:
            return None
        # all same side?
        if not (a["side"] == t["side"] == c["side"]):
            return None

        side = a["side"]
        m1 = tfs["M1"]
        b = m1.iloc[-1]
        notes = [
            "[✓] Alignment fired (4-TF EMA-200 confluence)",
            "[✓] Touch fired (200 EMA pullback confirmed)",
            "[✓] Cross fired (9/15 EMA momentum)",
            "[🔥] Canonical trend-trade sequence within 30 min",
        ]
        ev = ImprovedSignal(
            type="stacked", symbol=symbol, side=side, timeframe="M1",
            price=float(b["close"]),
            ema9=float(b["ema9"]), ema15=float(b["ema15"]),
            ema200=float(b["ema200"]),
            score=100.0, verdict="STACKED 🔥🔥🔥", notes=notes,
            detect_ms=0.0, df_for_chart=m1,
        )
        self._last_stacked[symbol] = now_ts
        return ev
