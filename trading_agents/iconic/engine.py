"""IconicEngine — combines the confluence layer (Phase 1) and the pattern layer
(Phase 2) into a single actionable Iconic Trader signal.

Pipeline per symbol (setup TF = H1):
  1. Confluence A/B/C grade + side + leader        (confluence.IconicConfluenceScorer)
  2. Set 1/2 money-spot + Test 1/Test 2 levels     (pattern.detect_setup)
  3. Dead-volume confirmation on the Test 2 bar    (volume)
  4. Entry / SL from structure; TP & scale-out from the A/B class
     - A-class: hold for the move — final target = 3R proxy ("brand new extreme")
     - B-class: take the meat — final target = 1.5R proxy (nearest SNR/ATR)
     - C-class: never reaches here (filtered out)

Emits IconicTradeSignal objects. This is the Phase-3 hand-off: feed these into
the MTF backtest harness (APPLY_COSTS on) to validate per symbol before any EA.
TP "extreme" targeting is an R-multiple proxy until structural targets are wired
in Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import volume as vol
from . import pattern
from .confluence import IconicConfluenceScorer, IconicScore, SETUP_TF
from .correlation import split_pair
from .purpose import NewsProvider

log = logging.getLogger("IconicEngine")

RR_A = 3.0      # A-class: "hold aggressively to brand-new extreme" (Navin)
RR_B = 1.5      # B-class: "take the meat at nearest S/R" (Navin)
MIN_RR = 1.2    # reject setups below this floor
# Scale-out levels: partial exits at these R-multiples (10-20-30% rule)
SCALE_A = [1.0, 2.0, 2.5]   # A-class: 3 partial exits
SCALE_B = [1.0]              # B-class: 1 partial exit then hold to final TP


@dataclass
class IconicTradeSignal:
    symbol: str
    side: str               # BUY | SELL
    klass: str              # A | B
    type: str               # type1 | type2
    entry: float
    stop: float
    tp_final: float
    tp_scale: list[float]   # partial-exit levels (10/20/30 % course rule)
    risk: float
    rr_final: float
    score: float            # 0..100 confluence score
    is_leader: bool
    volume_dead: bool       # dead volume confirmed on Test 2 bar
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    ts: str = ""

    def to_public(self) -> dict:
        return asdict(self)


class IconicEngine:
    def __init__(self, news_provider: Optional[NewsProvider] = None,
                 setup_tf: str = SETUP_TF, pullback_tf: str = "M15",
                 purpose_window_min: int = 90, rr_a: float = RR_A, rr_b: float = RR_B):
        self.scorer = IconicConfluenceScorer(
            news_provider=news_provider, setup_tf=setup_tf,
            pullback_tf=pullback_tf, purpose_window_min=purpose_window_min)
        self._setup_tf = setup_tf
        self._rr_a = rr_a
        self._rr_b = rr_b

    def evaluate(self, snapshots: dict, strength: dict, *,
                 now: Optional[datetime] = None) -> list[IconicTradeSignal]:
        now = now or datetime.now(timezone.utc)
        scores = self.scorer.classify_group(snapshots, strength, now=now)

        # Build group map: dominant_ccy -> list of A/B symbols (for group roll-over)
        ab_by_dom: dict[str, list[str]] = {}
        for sym, sc in scores.items():
            if sc.klass not in ("A", "B"):
                continue
            base, quote = split_pair(sym)
            dom = base if abs(sc.base7) >= abs(sc.quote7) else quote
            if dom:
                ab_by_dom.setdefault(dom, []).append(sym)

        out: list[IconicTradeSignal] = []
        for sym, snap in snapshots.items():
            sc = scores.get(sym)
            if sc is None or sc.klass not in ("A", "B"):
                continue
            # Group roll-over gate (course Q6 step 6): leader should have at
            # least one sister pair also A/B class agreeing with the direction.
            # Soft gate: downgrades signal to note, does NOT cancel — the agent
            # is in paper-trade mode and we need trade data to validate.
            if sc.is_leader:
                base, quote = split_pair(sym)
                dom = base if abs(sc.base7) >= abs(sc.quote7) else quote
                group = ab_by_dom.get(dom, [])
                if len(group) < 2:
                    sc.flags.append("⚠️ No sister pair confirms — group roll-over unverified")
            sig = self._build(sym, snap, sc)
            if sig is not None:
                out.append(sig)
        return out

    def _build(self, sym: str, snap: dict, sc: IconicScore) -> Optional[IconicTradeSignal]:
        tfs = snap.get("tfs", {})
        if self._setup_tf not in tfs:
            return None
        setup_df = tfs[self._setup_tf]
        setup = pattern.detect_setup(setup_df, sc.side, symbol=sym)
        if not setup.valid:
            return None

        # Dead-volume confirmation on the Test 2 bar (the stop-hunt push).
        volume_dead = self._dead_at(setup_df, setup.test2_idx)

        entry, stop = float(setup.entry), float(setup.stop)
        risk = abs(entry - stop)
        if risk <= 0:
            return None
        rr = self._rr_a if sc.klass == "A" else self._rr_b
        scale_rs = SCALE_A if sc.klass == "A" else SCALE_B
        if sc.side == "SELL":
            tp_final = entry - rr * risk
            tp_scale = [entry - r * risk for r in scale_rs]
        else:
            tp_final = entry + rr * risk
            tp_scale = [entry + r * risk for r in scale_rs]
        rr_final = abs(tp_final - entry) / risk

        reasons = list(sc.reasons) + list(setup.reasons)
        flags = list(sc.flags)

        # Hard block: if Test 2 volume is NOT dead the counter-party is still
        # strong and Navin's rule is explicit: "you must stand aside".
        if not volume_dead:
            flags.append("✗ Test 2 volume not dead — CANCELLED per strategy rule")
            return None

        if rr_final < MIN_RR:
            flags.append(f"⚠️ RR {rr_final:.2f} below floor {MIN_RR}")
            return None

        return IconicTradeSignal(
            symbol=sym, side=sc.side, klass=sc.klass, type=setup.type,
            entry=round(entry, 6), stop=round(stop, 6),
            tp_final=round(tp_final, 6),
            tp_scale=[round(x, 6) for x in tp_scale],
            risk=round(risk, 6), rr_final=round(rr_final, 2),
            score=sc.score, is_leader=sc.is_leader, volume_dead=volume_dead,
            reasons=reasons, flags=flags,
            ts=now_iso(),
        )

    @staticmethod
    def _dead_at(df: pd.DataFrame, idx: Optional[int]) -> bool:
        if idx is None or "tick_volume" not in df.columns:
            return False
        ma = df["tick_volume"].astype(float).rolling(vol.VOL_MA_PERIOD).mean()
        if idx >= len(df) or pd.isna(ma.iloc[idx]) or ma.iloc[idx] <= 0:
            return False
        return float(df["tick_volume"].iloc[idx]) <= vol.DEAD_FACTOR * float(ma.iloc[idx])


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── self-test ────────────────────────────────────────────────────────────
def _h1_with_pattern() -> pd.DataFrame:
    """Pattern self-test scenario + tick_volume (pop on impulse, dead on Test 2)
    + ema200 below price-region for a bull/bear context."""
    df = pattern._build_sell_scenario().copy()
    n = len(df)
    # volume: baseline 100; pop on the impulse leg; dead during spot incl. Test 2
    v = [100.0] * n
    for i in range(20, 28):          # impulse bars → pop
        v[i] = 220.0
    for i in range(31, n):           # money spot → low/dead volume
        v[i] = 55.0
    df["tick_volume"] = v
    # ema200 above price → bearish context (close < ema200) so align=bear
    df["ema200"] = df["close"] + 40.0
    return df


def _run_selftest() -> None:
    h1 = _h1_with_pattern()
    m15 = h1.copy()                  # reuse for digestion-volume check
    snap = {"align": "bear", "tfs": {"H1": h1, "M15": m15}}
    # SELL EURUSD wants EUR weak, USD strong → strong correlation
    strength = {"EUR": 1.0, "USD": 9.5}
    noon = datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)   # overlap → purpose

    eng = IconicEngine(news_provider=NewsProvider())
    sigs = eng.evaluate({"EURUSD": snap}, strength, now=noon)
    print(f"signals: {len(sigs)}")
    for s in sigs:
        print(f"  {s.symbol} {s.side} {s.klass}/{s.type} "
              f"entry={s.entry} stop={s.stop} tp={s.tp_final} "
              f"RR={s.rr_final} score={s.score} vol_dead={s.volume_dead} leader={s.is_leader}")
        for f in s.flags:
            print("     ", f)
    assert len(sigs) == 1, "should emit one Iconic signal"
    assert sigs[0].side == "SELL" and sigs[0].klass in ("A", "B")
    assert sigs[0].volume_dead, "Test 2 should be on dead volume in this scenario"
    print("\nself-test OK")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO)
    _run_selftest()
