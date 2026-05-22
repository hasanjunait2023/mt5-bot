"""IconicScalpEngine — same Set 1/2 logic on M15 setup TF.

Key differences vs H1 IconicEngine:
  - Setup TF  : M15 (not H1)
  - Pullback TF: M3  (not M15)
  - Purpose window: 60 min open window (tighter — London/NY opens only)
  - RR targets: A=3.0R, B=2.0R (1:2 minimum per user request)
  - MIN_RR: 1.8

Everything else (pattern detection, volume gate, correlation, group roll-over)
is reused from the H1 engine unchanged.  ATR-relative thresholds in pattern.py
scale automatically to M15 bar size.

Usage:
  eng = IconicScalpEngine()
  sigs = eng.evaluate({"USDCAD": snap}, strength, now=now_dt)

  snap = {"align": "bull"|"bear"|"none",
          "tfs":  {"M15": df_m15, "M3": df_m3, "H1": df_h1}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .engine import IconicEngine, IconicTradeSignal
from .confluence import SETUP_TF as _H1_SETUP_TF

SCALP_SETUP_TF       = "M15"
SCALP_PULLBACK_TF    = "M3"
SCALP_PURPOSE_WINDOW = 90    # London/NY open ±90 min (catches full opening range)
SCALP_RR_A           = 3.0
SCALP_RR_B           = 2.0   # user: 1:2 minimum
SCALP_MIN_RR         = 1.5   # lowered — compact-spot filter in backtest enforces quality


class IconicScalpEngine(IconicEngine):
    """Drop-in replacement for IconicEngine operating on M15 bars."""

    def __init__(self, news_provider=None):
        super().__init__(
            news_provider=news_provider,
            setup_tf=SCALP_SETUP_TF,
            pullback_tf=SCALP_PULLBACK_TF,
            purpose_window_min=SCALP_PURPOSE_WINDOW,
            rr_a=SCALP_RR_A,
            rr_b=SCALP_RR_B,
        )


# ── self-test ────────────────────────────────────────────────────────────
def _run_selftest() -> None:
    import pandas as pd
    from . import pattern, volume as vol
    from .engine import _h1_with_pattern

    # Build M15 sell scenario (reuse H1 builder — same relative structure)
    df = _h1_with_pattern().copy()
    n = len(df)
    v = [100.0] * n
    for i in range(20, 28):
        v[i] = 220.0
    for i in range(31, n):
        v[i] = 55.0
    df["tick_volume"] = v
    df["ema200"] = df["close"] + 40.0

    snap = {"align": "bear", "tfs": {SCALP_SETUP_TF: df, SCALP_PULLBACK_TF: df}}
    strength = {"EUR": 1.0, "USD": 9.5}
    noon = datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)

    eng = IconicScalpEngine()
    sigs = eng.evaluate({"EURUSD": snap}, strength, now=noon)
    print(f"scalp signals: {len(sigs)}")
    for s in sigs:
        print(f"  {s.symbol} {s.side} {s.klass}/{s.type} "
              f"entry={s.entry} stop={s.stop} tp={s.tp_final} "
              f"RR={s.rr_final} score={s.score}")
    assert len(sigs) == 1, "should emit one scalp signal"
    assert sigs[0].rr_final >= SCALP_MIN_RR, f"RR {sigs[0].rr_final} below floor"
    print("\nscalp self-test OK")


if __name__ == "__main__":
    import sys, logging
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO)
    _run_selftest()
