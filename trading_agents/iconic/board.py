"""Board layer — the whole-board view Navin's Iconic method runs on.

The single-pair agent only ever saw one symbol, so the currency-strength /
leader / group-roll-over machinery in confluence.py had nothing to chew on.
This module supplies the missing piece: the 28 G7 FX pairs and a real
8-currency strength meter computed across the entire board, which is exactly
what `IconicConfluenceScorer.classify_group` was built to consume.

Strength model (proxy — see urbanforex_iconic_trader_PLAN.md Part B):
  For each pair, a directional score d = clip((close - ema200)/(k·ATR), -1, +1)
  on the setup TF. d>0 means the BASE is winning. Each currency's raw strength
  is the mean of (+d where it is base) and (-d where it is quote) across every
  pair it appears in. Raw (~[-1,+1]) is scaled to the 0..10 band the scorer
  expects (5 = neutral) using the board's own max magnitude, so the strongest /
  weakest currencies span the full range — relative strength is what drives the
  leader and group decisions, mirroring the course's ±7 meter.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .pattern import atr
from .correlation import split_pair, G7

# CAD is in the board even though correlation.G7 excludes it from the news set;
# it still carries strength and forms groups (USDCAD, CADJPY, ...).
BOARD_CCYS = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CHF", "CAD")

# 28 unique G7+CAD FX pairs in conventional quoting order.
BOARD_PAIRS = (
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD",
    "AUDJPY", "AUDCHF", "AUDNZD", "AUDCAD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF", "CHFJPY",
)

STRENGTH_ATR_K = 3.0      # EMA-distance saturates at this many ATRs
_EPS = 1e-9


def _pair_directional(df: pd.DataFrame) -> Optional[float]:
    """Signed, ATR-normalised distance of close from EMA200 on the setup TF.

    +1 → base currency strongly winning; -1 → quote strongly winning.
    Returns None if the frame can't be scored.
    """
    if df is None or len(df) < 30 or "ema200" not in df.columns:
        return None
    a = atr(df)
    if a <= 0:
        return None
    last = df.iloc[-1]
    dist = (float(last["close"]) - float(last["ema200"])) / (STRENGTH_ATR_K * a)
    return max(-1.0, min(1.0, dist))


def compute_strength(snapshots: dict, *, setup_tf: str = "H1") -> dict[str, float]:
    """Board-wide currency strength {ccy: 0..10} (5 = neutral).

    `snapshots` maps symbol -> {"tfs": {tf: df, ...}, ...} as fed to the scorer.
    Only pairs whose both legs are board currencies contribute.
    """
    acc: dict[str, list[float]] = {c: [] for c in BOARD_CCYS}
    for sym, snap in snapshots.items():
        base, quote = split_pair(sym)
        if base not in BOARD_CCYS or quote not in BOARD_CCYS:
            continue
        tfs = snap.get("tfs", {}) if isinstance(snap, dict) else {}
        d = _pair_directional(tfs.get(setup_tf))
        if d is None:
            continue
        acc[base].append(+d)
        acc[quote].append(-d)

    raw = {c: (sum(v) / len(v)) if v else 0.0 for c, v in acc.items()}
    peak = max((abs(r) for r in raw.values()), default=0.0)
    if peak < _EPS:
        return {c: 5.0 for c in BOARD_CCYS}
    # scale so the strongest/weakest span ~[0,10] around neutral 5
    return {c: round(5.0 + 5.0 * (r / peak), 2) for c, r in raw.items()}


def strength_table(strength: dict[str, float]) -> list[dict]:
    """Sorted strongest→weakest, for the dashboard board view."""
    return [
        {"currency": c, "strength": s, "scale7": round((s - 5.0) / 5.0 * 7.0, 2)}
        for c, s in sorted(strength.items(), key=lambda kv: kv[1], reverse=True)
    ]


# ── self-test ──────────────────────────────────────────────────────────────
def _synth(close: float, ema: float, n: int = 60) -> pd.DataFrame:
    rows = [{"open": close, "high": close + 2, "low": close - 2,
             "close": close, "ema200": ema} for _ in range(n)]
    return pd.DataFrame(rows)


def _run_selftest() -> None:
    # USD strong everywhere, JPY weak everywhere
    snaps = {
        "USDJPY": {"tfs": {"H1": _synth(150, 145)}},   # USD base, above ema → USD strong
        "USDCHF": {"tfs": {"H1": _synth(0.92, 0.90)}},
        "USDCAD": {"tfs": {"H1": _synth(1.40, 1.38)}},
        "EURUSD": {"tfs": {"H1": _synth(1.05, 1.08)}},  # USD quote, price below ema → USD strong
        "EURJPY": {"tfs": {"H1": _synth(165, 160)}},    # JPY quote weak
        "GBPJPY": {"tfs": {"H1": _synth(190, 185)}},
    }
    s = compute_strength(snaps)
    print("strength:", s)
    for row in strength_table(s):
        print(f"  {row['currency']}  {row['strength']:.2f}  (scale7 {row['scale7']:+.2f})")
    assert s["USD"] > 6.0, "USD should read strong"
    assert s["JPY"] < 4.0, "JPY should read weak"
    print("\nboard self-test OK")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _run_selftest()
