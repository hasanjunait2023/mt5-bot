"""Iconic A/B/C confluence scorer (Phase 1).

Combines the three measurable filters into Navin's classification:

  A-class : Volume Pop  +  Purpose  +  strong correlation lineup
  B-class : Volume Pop  +  Purpose  +  neutral correlation
  C-class : anything else (no volume, no purpose, or correlation contradicts)
            → stand aside

Input contract matches what SignalEngine feeds Alpha Desk:
  snapshot = {"tfs": {"M1","M3","M15","H1"[, "H4"]}, "align": "bull"|"bear"|"none"}
  strength = {currency: 0..10}   (5 = neutral)
TF dataframes carry open/high/low/close/ema200/tick_volume.

This is the confluence layer only. Set 1/2, Test 1/2 and money-spot detection
(the pattern layer) are Phase 2 — this scorer answers "is the context A/B/C and
which way", not "is price at a precise trigger".
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import volume as vol
from .correlation import correlation_tier, pair_strength, split_pair, pick_leader
from .purpose import PurposeGate, NewsProvider

log = logging.getLogger("IconicConfluence")

# setup TF (where the Set 1/2 + volume pop lives) and the digestion TF.
SETUP_TF      = "H1"
PULLBACK_TF   = "M15"

# score weights (0..100) for the dashboard scoreboard.
W_VOLUME      = 35
W_PURPOSE     = 25
W_CORR        = 40


@dataclass
class IconicScore:
    symbol: str
    side: str                       # BUY | SELL | NONE
    klass: str                      # A | B | C | none
    score: float                    # 0..100
    volume_ok: bool
    purpose_ok: bool
    correlation: str                # strong | neutral | contradicts | n/a
    directional: float              # base7-quote7 in trade direction
    base7: float
    quote7: float
    is_leader: bool                 # set by classify_group across a currency group
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)    # warnings (climax, etc.)
    ts: str = ""

    def to_public(self) -> dict:
        return asdict(self)


class IconicConfluenceScorer:
    def __init__(self, news_provider: Optional[NewsProvider] = None):
        self.purpose = PurposeGate(news_provider=news_provider)

    # ── single symbol ────────────────────────────────────────────────────
    def classify(self, symbol: str, snapshot: dict, strength: dict, *,
                 now: Optional[datetime] = None) -> IconicScore:
        now = now or datetime.now(timezone.utc)
        ts = now.isoformat(timespec="seconds")
        align = snapshot.get("align", "none")
        tfs = snapshot.get("tfs", {})

        side = "BUY" if align == "bull" else ("SELL" if align == "bear" else "NONE")
        if side == "NONE" or SETUP_TF not in tfs:
            return IconicScore(symbol, "NONE", "none", 0.0, False, False,
                               "n/a", 0.0, 0.0, 0.0, False,
                               reasons=["[ ] No directional alignment"], ts=ts)

        reasons: list[str] = []
        flags: list[str] = []

        # 1) Volume Pop on the setup TF -------------------------------------
        vs = vol.read(tfs[SETUP_TF])
        volume_ok = vs.has_pop
        if vs.is_climax:
            flags.append("⚠️ Climax volume — possible reversal (cashing out)")
        if volume_ok:
            reasons.append(f"[✓] Volume pop on {SETUP_TF} "
                           f"(mean {vs.pop_mean_ratio}×, max {vs.pop_max_ratio}× MA)")
        else:
            reasons.append(f"[ ] No volume pop on {SETUP_TF} "
                           f"(mean {vs.pop_mean_ratio}× MA)")
        # digestion check: pullback TF should be quiet
        if PULLBACK_TF in tfs:
            pvs = vol.read(tfs[PULLBACK_TF])
            if pvs.is_low:
                reasons.append(f"[✓] {PULLBACK_TF} pullback volume low (digesting)")
            else:
                flags.append(f"⚠️ {PULLBACK_TF} pullback volume not low "
                             f"({pvs.last_ratio}× MA) — counter-flow risk")

        # 2) Purpose (session/news) -----------------------------------------
        pr = self.purpose.evaluate(symbol, now=now)
        purpose_ok = pr.ok
        if purpose_ok:
            reasons.append(f"[✓] Purpose: {', '.join(pr.sources)}")
        else:
            reasons.append("[ ] No Purpose (no session open / no orange-red G7 news)")

        # 3) Correlation lineup ---------------------------------------------
        corr, directional = correlation_tier(side, symbol, strength)
        ps = pair_strength(symbol, strength)
        if corr == "strong":
            reasons.append(f"[✓] Correlation strong (dir {directional:+.1f}; "
                           f"{ps.base}{ps.base7:+.1f} {ps.quote}{ps.quote7:+.1f})")
        elif corr == "neutral":
            reasons.append(f"[~] Correlation neutral (dir {directional:+.1f}) → caps at B")
        else:
            reasons.append(f"[✗] Correlation contradicts (dir {directional:+.1f})")

        # ── classify ────────────────────────────────────────────────────
        if volume_ok and purpose_ok and corr == "strong":
            klass = "A"
        elif volume_ok and purpose_ok and corr == "neutral":
            klass = "B"
        else:
            klass = "C"

        # ── 0..100 score for the dashboard ──────────────────────────────
        v_pts = W_VOLUME if volume_ok else 0
        p_pts = W_PURPOSE if purpose_ok else 0
        # correlation scaled by directional magnitude (cap at DIR_STRONG)
        from .correlation import DIR_STRONG
        c_frac = max(0.0, min(1.0, directional / DIR_STRONG))
        c_pts = round(W_CORR * c_frac, 1)
        score = round(min(100.0, v_pts + p_pts + c_pts), 1)

        return IconicScore(
            symbol=symbol, side=side, klass=klass, score=score,
            volume_ok=volume_ok, purpose_ok=purpose_ok,
            correlation=corr, directional=round(directional, 2),
            base7=ps.base7, quote7=ps.quote7, is_leader=False,
            reasons=reasons, flags=flags, ts=ts,
        )

    # ── whole scan: classify all + mark leaders per currency group ───────
    def classify_group(self, snapshots: dict, strength: dict, *,
                       now: Optional[datetime] = None) -> dict[str, IconicScore]:
        now = now or datetime.now(timezone.utc)
        scores: dict[str, IconicScore] = {}
        for sym, snap in snapshots.items():
            try:
                scores[sym] = self.classify(sym, snap, strength, now=now)
            except Exception:
                log.exception("iconic classify failed: %s", sym)

        # group tradeable (A/B) symbols by their dominant currency, flag leader
        by_ccy: dict[str, list[str]] = {}
        for sym, sc in scores.items():
            if sc.klass not in ("A", "B"):
                continue
            base, quote = split_pair(sym)
            # dominant = the currency with larger |scale7| drives the group
            dom = base if abs(sc.base7) >= abs(sc.quote7) else quote
            if dom:
                by_ccy.setdefault(dom, []).append(sym)
        for dom, syms in by_ccy.items():
            if not syms:
                continue
            side = scores[syms[0]].side
            leader = pick_leader(syms, side, strength)
            if leader and leader in scores:
                scores[leader].is_leader = True
                scores[leader].reasons.append(f"[★] Leader of {dom} group")
        return scores


# ── self-test ────────────────────────────────────────────────────────────
def _synth_df(n: int, vol_profile: list[float], *, bullish: bool) -> pd.DataFrame:
    """Build a synthetic OHLC+tick_volume df. vol_profile sets the LAST bars'
    volume; earlier bars sit at a calm baseline (=100)."""
    base_vol = [100.0] * (n - len(vol_profile)) + list(vol_profile)
    closes = list(range(1000, 1000 + n)) if bullish else list(range(1000 + n, 1000, -1))
    rows = []
    for i in range(n):
        c = float(closes[i])
        rows.append({"open": c - 1, "high": c + 2, "low": c - 2, "close": c,
                     "ema200": c - 50 if bullish else c + 50,
                     "tick_volume": base_vol[i]})
    return pd.DataFrame(rows)


def _run_selftest() -> None:
    scorer = IconicConfluenceScorer(news_provider=NewsProvider())
    # A-class candidate: bull align, volume pop on H1, quiet M15, strong USD-weak
    pop = [180, 210, 240]                     # collective rise (~2x baseline)
    quiet = [60, 55, 50]                      # below MA
    snap_bull = {"align": "bull",
                 "tfs": {"H1": _synth_df(60, pop, bullish=True),
                         "M15": _synth_df(60, quiet, bullish=True)}}
    # EURUSD BUY wants EUR strong, USD weak
    strength = {"EUR": 9.5, "USD": 1.0, "GBP": 8.0, "JPY": 2.0}
    from datetime import datetime as _dt
    noon = _dt(2026, 5, 21, 13, 0, tzinfo=timezone.utc)   # London/NY overlap-ish
    sc = scorer.classify("EURUSD", snap_bull, strength, now=noon)
    print(f"EURUSD → class={sc.klass} side={sc.side} score={sc.score} "
          f"vol={sc.volume_ok} purpose={sc.purpose_ok} corr={sc.correlation}")
    for r in sc.reasons:
        print("   ", r)
    for f in sc.flags:
        print("   ", f)

    # C-class: no volume pop (flat), neutral strength
    snap_flat = {"align": "bull",
                 "tfs": {"H1": _synth_df(60, [100, 100, 100], bullish=True),
                         "M15": _synth_df(60, [100, 100, 100], bullish=True)}}
    sc2 = scorer.classify("AUDUSD", snap_flat, {"AUD": 5.0, "USD": 5.0}, now=noon)
    print(f"\nAUDUSD → class={sc2.klass} score={sc2.score} (expect C)")

    # group leader test
    snaps = {"EURUSD": snap_bull,
             "GBPUSD": {"align": "bull", "tfs": snap_bull["tfs"]}}
    grp = scorer.classify_group(snaps, strength, now=noon)
    leaders = [s for s, v in grp.items() if v.is_leader]
    print(f"\nGroup leaders: {leaders}")
    assert sc.side == "BUY"
    print("\nself-test OK")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO)
    _run_selftest()
