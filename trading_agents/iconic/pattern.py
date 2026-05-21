"""Pattern layer (Phase 2) — Set 1 / Set 2 / money spot / Test 1 / Test 2.

This is the hard, semi-discretionary core of the Iconic Trader method, here
reduced to deterministic rules with every fuzzy term given an objective
threshold (kept in one block so they can be tuned/ablated in Phase 3).

Structure of a SELL setup (downtrend; BUY is the mirror):
  1. Down impulse, then a pullback that FAILS to make a new low      → Set 1
  2. Price drifts up and consolidates into a range                   → money spot / Set 2
  3. First swing high inside the spot                                → Test 1
  4. A later swing high that pokes slightly ABOVE Test 1 (stop hunt) → Test 2
     (ideally on dead volume — volume confirmation is the engine's job)
  5. Entry SELL on Test 2 rejection; stop just beyond the spot/Test 2

Type, by where the money spot sits vs the Set 1 line (the pullback high):
  Type 1 : range sits clearly the "trade side" of the line (clean break)
  Type 2 : range hugs/just past the line, ends with a fake spike (stop hunt)
  Type 3 : no money spot — price ran away to a new extreme  → NO TRADE

Operates on CLOSED bars of the setup TF (default H1). Returns levels only; the
A/B/C grade, volume-dead confirmation and group roll-over gate live in the
confluence engine / Phase 3 entry logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Literal

import pandas as pd

Side = Literal["BUY", "SELL"]

# ── objective thresholds (tune in Phase 3) ────────────────────────────────
PIVOT_LEFT          = 2      # bars each side for a fractal swing pivot
PIVOT_RIGHT         = 2
ATR_PERIOD          = 14
SPOT_MIN_BARS       = 5      # money spot must be at least this many bars
SPOT_MAX_ATR        = 2.2    # ...spanning no more than this * ATR (congestion)
SPOT_MAX_LOOKBACK   = 40     # don't look further back than this for the spot
BAR_BREAK_MULT      = 1.8    # stop extending if a bar's range >> spot's avg (impulse)
PROBE_MAX_ATR       = 0.8    # Test 2 may exceed Test 1 by at most this * ATR
IMPULSE_MIN_ATR     = 2.5    # the leg into Set 1 must be a real move (>= this*ATR)


@dataclass
class Swing:
    idx: int
    price: float
    kind: str            # "high" | "low"


@dataclass
class Setup:
    symbol: str
    side: Side
    valid: bool
    type: Optional[str]             # type1 | type2 | type3 | None
    set1_line: Optional[float]      # pullback extreme that defines Set 1
    spot_lo: Optional[float]
    spot_hi: Optional[float]
    spot_start: Optional[int]
    test1_idx: Optional[int]
    test1_price: Optional[float]
    test2_idx: Optional[int]
    test2_price: Optional[float]
    entry: Optional[float]
    stop: Optional[float]
    reasons: list[str] = field(default_factory=list)

    def to_public(self) -> dict:
        return asdict(self)


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    v = tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return float(v) if pd.notna(v) else 0.0


def find_pivots(df: pd.DataFrame, left: int = PIVOT_LEFT,
                right: int = PIVOT_RIGHT) -> list[Swing]:
    """Fractal swing highs/lows on closed bars."""
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    out: list[Swing] = []
    for i in range(left, n - right):
        win_h = highs[i - left:i + right + 1]
        win_l = lows[i - left:i + right + 1]
        if highs[i] == win_h.max() and (win_h.argmax() == left):
            out.append(Swing(i, float(highs[i]), "high"))
        if lows[i] == win_l.min() and (win_l.argmin() == left):
            out.append(Swing(i, float(lows[i]), "low"))
    out.sort(key=lambda s: s.idx)
    return out


def _detect_money_spot(df: pd.DataFrame, a: float) -> Optional[tuple[int, float, float]]:
    """Most recent congestion: extend a window back from the last closed bar
    while it stays within SPOT_MAX_ATR * ATR. Returns (start_idx, lo, hi)."""
    if a <= 0:
        return None
    n = len(df)
    hi = df["high"].values
    lo = df["low"].values
    rng = hi - lo
    end = n - 1
    start = end
    cur_hi, cur_lo = hi[end], lo[end]
    range_sum, cnt = float(rng[end]), 1
    limit = max(0, n - SPOT_MAX_LOOKBACK)
    for i in range(end - 1, limit - 1, -1):
        # adaptive guard: a bar much bigger than the spot's average is an
        # impulse/retrace leg, not congestion — stop before swallowing it.
        if cnt >= 2 and rng[i] > BAR_BREAK_MULT * (range_sum / cnt):
            break
        new_hi = max(cur_hi, hi[i])
        new_lo = min(cur_lo, lo[i])
        if (new_hi - new_lo) > SPOT_MAX_ATR * a:
            break
        cur_hi, cur_lo, start = new_hi, new_lo, i
        range_sum += float(rng[i])
        cnt += 1
    if (end - start + 1) >= SPOT_MIN_BARS:
        return start, float(cur_lo), float(cur_hi)
    return None


def detect_setup(df: pd.DataFrame, side: Side, *, symbol: str = "") -> Setup:
    """Detect a Set 1/Set 2 money-spot setup on the setup-TF dataframe."""
    base = Setup(symbol, side, False, None, None, None, None, None,
                 None, None, None, None, None, None, [])
    if len(df) < ATR_PERIOD + SPOT_MIN_BARS + 4:
        base.reasons.append("[ ] Not enough bars")
        return base

    a = atr(df)
    spot = _detect_money_spot(df, a)
    if not spot:
        base.type = "type3"
        base.reasons.append("[✗] No money spot — price ran away (Type 3, no trade)")
        return base
    start, spot_lo, spot_hi = spot
    base.spot_start, base.spot_lo, base.spot_hi = start, spot_lo, spot_hi

    pivots = find_pivots(df)
    in_spot = [p for p in pivots if p.idx >= start]
    pre_spot = [p for p in pivots if p.idx < start]

    # Test 1 / Test 2 = the relevant swings inside the spot.
    # SELL → swing highs (stop-hunt pokes up); BUY → swing lows.
    want = "high" if side == "SELL" else "low"
    tests = [p for p in in_spot if p.kind == want]
    if len(tests) >= 2:
        test1 = tests[0]
        # Test 2 = a later swing that probes just beyond Test 1's extreme
        test2 = None
        for p in tests[1:]:
            beyond = (p.price > test1.price) if side == "SELL" else (p.price < test1.price)
            within = abs(p.price - test1.price) <= PROBE_MAX_ATR * a
            if beyond and within:
                test2 = p
                break
        if test2 is None:           # no clean probe → use the most extreme later swing
            test2 = max(tests[1:], key=lambda p: p.price) if side == "SELL" \
                else min(tests[1:], key=lambda p: p.price)
        base.test1_idx, base.test1_price = test1.idx, test1.price
        base.test2_idx, base.test2_price = test2.idx, test2.price
        base.reasons.append(f"[✓] Test 1 @ {test1.price:.5g}, Test 2 @ {test2.price:.5g}")
    else:
        base.reasons.append("[ ] Test 1/Test 2 not yet formed in money spot")

    # Set 1 line = last pullback extreme before the spot (the level to break).
    if pre_spot:
        line_kind = "high" if side == "SELL" else "low"
        cands = [p for p in pre_spot if p.kind == line_kind]
        if cands:
            base.set1_line = cands[-1].price

    # Type classification by spot position vs the Set 1 line.
    if base.set1_line is not None:
        line = base.set1_line
        if side == "SELL":
            if spot_lo > line:
                base.type = "type1"
            elif spot_hi > line >= spot_lo:
                base.type = "type2"
            else:
                base.type = "type3"
        else:   # BUY mirror
            if spot_hi < line:
                base.type = "type1"
            elif spot_lo < line <= spot_hi:
                base.type = "type2"
            else:
                base.type = "type3"
        base.reasons.append(f"[✓] {base.type} (spot {spot_lo:.5g}-{spot_hi:.5g} vs line {line:.5g})")
    else:
        base.reasons.append("[~] Set 1 line undetermined")

    # Entry / stop levels (structural; volume + group gate applied by engine).
    if base.test2_price is not None:
        pad = 0.25 * a
        if side == "SELL":
            base.entry = spot_lo                     # break of spot low
            base.stop = base.test2_price + pad       # just above the stop-hunt
        else:
            base.entry = spot_hi
            base.stop = base.test2_price - pad

    # Valid = a tradeable type with both tests + levels present.
    base.valid = (base.type in ("type1", "type2")
                  and base.test1_price is not None
                  and base.test2_price is not None
                  and base.entry is not None and base.stop is not None)
    base.reasons.append(f"[{'✓' if base.valid else ' '}] Setup "
                        f"{'VALID' if base.valid else 'incomplete'}")
    return base


# ── self-test ────────────────────────────────────────────────────────────
def _build_sell_scenario() -> pd.DataFrame:
    """Textbook SELL: down impulse → retrace → money spot with Test1/Test2."""
    seq: list[tuple[float, float, float, float]] = []   # o,h,l,c

    def bar(c, rng=3.0):
        return (c, c + rng, c - rng, c)

    # warm-up baseline (for ATR) — mild down drift
    price = 1120.0
    for _ in range(20):
        price -= 1.0
        seq.append(bar(price))
    # down impulse (lower lows) ~ 1100 → 1040
    for c in range(1100, 1040, -8):
        seq.append(bar(float(c), rng=5))
    # Set 1: failed new low (higher low) + retrace up to ~1052
    seq.append(bar(1044, 4))
    seq.append(bar(1050, 4))
    seq.append(bar(1052, 4))            # pullback high ~ set1 line area
    # money spot: range ~1046-1054 for several bars, with two highs
    spot_path = [1048, 1053, 1047, 1054, 1046, 1053, 1056, 1049]
    #            ^test1 ~1053+rng       ^test2 slightly higher (1056)
    for c in spot_path:
        seq.append(bar(float(c), rng=2))
    # rejection back down (entry trigger)
    seq.append(bar(1044, 3))

    return pd.DataFrame(seq, columns=["open", "high", "low", "close"])


def _run_selftest() -> None:
    df = _build_sell_scenario()
    s = detect_setup(df, "SELL", symbol="EURUSD")
    print(f"SELL setup: valid={s.valid} type={s.type}")
    print(f"  money spot : {s.spot_lo:.5g} – {s.spot_hi:.5g} (start idx {s.spot_start})")
    print(f"  set1 line  : {s.set1_line}")
    print(f"  test1/2    : {s.test1_price} / {s.test2_price}")
    print(f"  entry/stop : {s.entry} / {s.stop}")
    for r in s.reasons:
        print("   ", r)
    assert s.spot_lo is not None, "money spot must be detected"
    assert s.test1_price is not None and s.test2_price is not None, "tests must be found"
    assert s.test2_price >= s.test1_price, "Test 2 should probe above Test 1 (SELL)"
    assert s.type in ("type1", "type2", "type3"), "type must classify"

    # Type 3 (run-away): pure down trend, no congestion
    runaway = pd.DataFrame([(c, c + 3, c - 3, c) for c in range(1100, 1000, -3)],
                           columns=["open", "high", "low", "close"])
    s3 = detect_setup(runaway, "SELL", symbol="EURUSD")
    print(f"\nRun-away: type={s3.type} valid={s3.valid} (expect type3 / invalid)")
    print("\nself-test OK")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _run_selftest()
