"""Confluence scorer + real-time alpha-signal emitter.

Inputs per symbol:
  - snapshot (tfs, align)               from SignalEngine
  - currency-strength dict              from SignalEngine
  - zones (supply/demand)               from ZoneTracker
  - pools (liquidity)                   from LiquidityTracker
  - absorption + order-blocks           from OrderFlowDetector
  - session                              from sessions module

Output: list[AlphaSignal] — fully scored, with reasons checklist.

Signal types this layer creates:
  sweep        — sweep of a liquidity pool with reversal candle
  zone         — touch + rejection at supply/demand zone
  ob_mit       — order-block mitigated with reaction
  absorption   — absorption candle in alignment direction
  confluence   — STACK: 4+ factors fire on same symbol within 30 min
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, asdict, field
from typing import Optional

import numpy as np
import pandas as pd

from .sessions import current_session, is_overlap, SessionName

log = logging.getLogger("AlphaConfluence")

CONF_MIN_EMIT = 55.0
TIER_PRIME    = 85
TIER_STRONG   = 70

# scoring caps
W_TREND  = 20
W_SESS   = 15
W_LIQ    = 20
W_ZONE   = 20
W_FLOW   = 15
W_HTF    = 10


@dataclass
class AlphaSignal:
    type: str                   # sweep | zone | ob_mit | absorption | confluence
    symbol: str
    side: str                   # BUY | SELL
    timeframe: str
    price: float
    score: float                # 0..100
    tier: str                   # PRIME 🔥 / STRONG 🟢 / WATCH 🟡
    session: SessionName
    breakdown: dict[str, float] # per-factor pts
    reasons: list[str]          # checklist [✓] items
    refs: dict                  # zone/pool/ob ids referenced
    detect_ms: float = 0.0
    df_for_chart: Optional[pd.DataFrame] = None

    def to_public(self) -> dict:
        d = asdict(self)
        d.pop("df_for_chart", None)
        return d


def _tier(score: float) -> str:
    if score >= TIER_PRIME:   return "PRIME 🔥"
    if score >= TIER_STRONG:  return "STRONG 🟢"
    return "WATCH 🟡"


class ConfluenceScorer:
    """Per-tick scorer + signal emitter. Holds a small per-symbol memory
    so we can detect the 'confluence stack' (4+ factor events within 30 min).
    """

    STACK_WINDOW_S = 30 * 60

    def __init__(self):
        # symbol -> list[(ts, type, side)]
        self._recent: dict[str, list[tuple[float, str, str]]] = {}

    def _record(self, symbol: str, sig_type: str, side: str):
        now = _time.time()
        bucket = self._recent.setdefault(symbol, [])
        bucket.append((now, sig_type, side))
        # trim outside window
        cutoff = now - self.STACK_WINDOW_S
        bucket[:] = [t for t in bucket if t[0] >= cutoff]

    def _stack_check(self, symbol: str, side: str) -> int:
        """How many distinct factor types fired same-side in window."""
        bucket = self._recent.get(symbol, [])
        types = {t[1] for t in bucket if t[2] == side}
        return len(types)

    # ── master evaluator ─────────────────────────────────────────────────
    def evaluate(self, *, symbol: str, snapshot: dict, strength: dict,
                 zones, pools, orderflow,
                 session: SessionName) -> list[AlphaSignal]:
        events: list[AlphaSignal] = []
        tfs   = snapshot["tfs"]
        align = snapshot["align"]
        if "M3" not in tfs:    # need at least M3 for entry detection
            return events
        m3  = tfs["M3"]
        h1  = tfs["H1"]
        last_m3 = m3.iloc[-1]
        price = float(last_m3["close"])
        bias_dir = None
        if align == "bull":  bias_dir = "BUY"
        elif align == "bear":bias_dir = "SELL"

        # ── factor 1: trend (0..W_TREND) ────────────────────────────────
        trend_pts = W_TREND if align in ("bull", "bear") else 0

        # ── factor 2: session (0..W_SESS) ───────────────────────────────
        # London↔NY overlap = peak liquidity → full points; single major =
        # most points; Asia = low (range-building); off-session = none.
        if is_overlap():
            sess_pts = W_SESS              # 15 — peak window
        elif session in ("london", "ny"):
            sess_pts = W_SESS - 3          # 12 — single major session
        elif session == "asia":
            sess_pts = 6
        else:
            sess_pts = 0

        # ── factor 6: higher-TF confluence (H4 not fetched here; reuse H1
        #     slope as proxy)
        htf_pts = 0
        slope = float(h1["ema200"].iloc[-1] - h1["ema200"].iloc[-20])
        if (slope > 0 and align == "bull") or (slope < 0 and align == "bear"):
            htf_pts = W_HTF

        atr_m3 = _atr_value(m3, 14)
        pip_mult = 100.0 if symbol.endswith("JPY") else (10.0 if "XAU" in symbol else 10000.0)

        # ── SWEEP detection ─────────────────────────────────────────────
        for pool in pools:
            if not pool.swept:           continue
            if not pool.swept_ts:        continue
            if _time.time() - pool.swept_ts > 5 * 60:   # only fire within 5 min of sweep
                continue
            # direction: BSL sweep (high wicked) → SELL; SSL sweep → BUY
            side = "SELL" if pool.side == "bsl" else "BUY"
            if bias_dir and side != bias_dir:
                # counter-trend sweep — lower score
                liq_pts = 8
            else:
                liq_pts = W_LIQ
            # zone confluence?
            zone_pts, zone_ref = self._zone_pts_at(zones, price)
            # order-flow
            flow_pts, flow_note = self._flow_pts(orderflow, symbol, side)
            score = trend_pts + sess_pts + liq_pts + zone_pts + flow_pts + htf_pts
            score = max(0.0, min(100.0, score))
            reasons = [
                f"[✓] {pool.kind.upper()} {pool.label} swept @ `{pool.price}`",
                f"[✓] Session: {session.upper()} (+{sess_pts})",
            ]
            if zone_ref:  reasons.append(f"[✓] At {zone_ref.side.upper()} zone {zone_ref.timeframe} (+{zone_pts})")
            if flow_note: reasons.append(f"[✓] {flow_note} (+{flow_pts})")
            if htf_pts:   reasons.append(f"[✓] H1 EMA200 slope confirms (+{htf_pts})")
            if trend_pts: reasons.append(f"[✓] Trend aligned 4/4 (+{trend_pts})")
            if score >= CONF_MIN_EMIT:
                ev = AlphaSignal(
                    type="sweep", symbol=symbol, side=side, timeframe="M3",
                    price=price, score=round(score, 1), tier=_tier(score),
                    session=session,
                    breakdown={"trend": trend_pts, "session": sess_pts,
                               "liquidity": liq_pts, "zone": zone_pts,
                               "flow": flow_pts, "htf": htf_pts},
                    reasons=reasons,
                    refs={"pool": {"kind": pool.kind, "price": pool.price,
                                   "label": pool.label}},
                    df_for_chart=m3,
                )
                events.append(ev)
                self._record(symbol, "sweep", side)

        # ── ZONE reaction ───────────────────────────────────────────────
        for z in zones:
            if not z.bar_overlaps(float(last_m3["low"]), float(last_m3["high"])):
                continue
            # body must close back in trend direction (rejection)
            body_lo = min(last_m3["open"], last_m3["close"])
            body_hi = max(last_m3["open"], last_m3["close"])
            if z.side == "supply":
                rejected = body_hi < z.top    # close back below zone
                side = "SELL"
            else:
                rejected = body_lo > z.bottom
                side = "BUY"
            if not rejected:
                continue
            if bias_dir and side != bias_dir:
                continue    # counter-trend zone rejection — skip
            zone_pts = self._zone_freshness_pts(z)
            liq_pts, _ = self._nearby_pool_pts(pools, side, price, atr_m3)
            flow_pts, flow_note = self._flow_pts(orderflow, symbol, side)
            score = trend_pts + sess_pts + liq_pts + zone_pts + flow_pts + htf_pts
            score = max(0.0, min(100.0, score))
            reasons = [
                f"[✓] {z.side.upper()} zone {z.timeframe} ({z.state}, strength {z.strength}x ATR)",
                f"[✓] Rejection candle confirmed",
                f"[✓] Session: {session.upper()} (+{sess_pts})",
            ]
            if flow_note: reasons.append(f"[✓] {flow_note} (+{flow_pts})")
            if htf_pts:   reasons.append(f"[✓] HTF slope (+{htf_pts})")
            if score >= CONF_MIN_EMIT:
                events.append(AlphaSignal(
                    type="zone", symbol=symbol, side=side, timeframe="M3",
                    price=price, score=round(score, 1), tier=_tier(score),
                    session=session,
                    breakdown={"trend": trend_pts, "session": sess_pts,
                               "liquidity": liq_pts, "zone": zone_pts,
                               "flow": flow_pts, "htf": htf_pts},
                    reasons=reasons,
                    refs={"zone": z.to_public()},
                    df_for_chart=m3,
                ))
                self._record(symbol, "zone", side)

        # ── OB mitigation ───────────────────────────────────────────────
        for ob in orderflow.obs_for(symbol):
            if not ob.mitigated:               continue
            if not ob.mitigated_ts:            continue
            if _time.time() - ob.mitigated_ts > 5 * 60:    continue
            side = "BUY" if ob.side == "bull" else "SELL"
            if bias_dir and side != bias_dir:
                continue
            zone_pts = 12        # OB is a zone-like context
            liq_pts, _ = self._nearby_pool_pts(pools, side, price, atr_m3)
            flow_pts = W_FLOW    # OB itself is order-flow context
            score = trend_pts + sess_pts + liq_pts + zone_pts + flow_pts + htf_pts
            score = max(0.0, min(100.0, score))
            reasons = [
                f"[✓] {ob.side.upper()} order-block mitigated ({ob.timeframe})",
                f"[✓] Session: {session.upper()} (+{sess_pts})",
            ]
            if liq_pts:   reasons.append(f"[✓] Liquidity context (+{liq_pts})")
            if htf_pts:   reasons.append(f"[✓] HTF slope (+{htf_pts})")
            if score >= CONF_MIN_EMIT:
                events.append(AlphaSignal(
                    type="ob_mit", symbol=symbol, side=side, timeframe="M3",
                    price=price, score=round(score, 1), tier=_tier(score),
                    session=session,
                    breakdown={"trend": trend_pts, "session": sess_pts,
                               "liquidity": liq_pts, "zone": zone_pts,
                               "flow": flow_pts, "htf": htf_pts},
                    reasons=reasons,
                    refs={"ob": ob.to_public()},
                    df_for_chart=m3,
                ))
                self._record(symbol, "ob_mit", side)

        # ── ABSORPTION ──────────────────────────────────────────────────
        abs_ev = orderflow.detect_absorption(symbol, "M3", m3)
        if abs_ev:
            side = "BUY" if abs_ev.side == "bull" else "SELL"
            if not bias_dir or side == bias_dir:
                liq_pts, _ = self._nearby_pool_pts(pools, side, price, atr_m3)
                zone_pts, _ = self._zone_pts_at(zones, price)
                flow_pts    = W_FLOW
                score = trend_pts + sess_pts + liq_pts + zone_pts + flow_pts + htf_pts
                score = max(0.0, min(100.0, score))
                reasons = [
                    f"[✓] Absorption: vol z={abs_ev.vol_z}, range {abs_ev.range_ratio}× ATR",
                    f"[✓] {side} side absorbing flow",
                    f"[✓] Session: {session.upper()} (+{sess_pts})",
                ]
                if zone_pts: reasons.append(f"[✓] At zone (+{zone_pts})")
                if liq_pts:  reasons.append(f"[✓] Near liquidity (+{liq_pts})")
                if score >= CONF_MIN_EMIT:
                    events.append(AlphaSignal(
                        type="absorption", symbol=symbol, side=side, timeframe="M3",
                        price=price, score=round(score, 1), tier=_tier(score),
                        session=session,
                        breakdown={"trend": trend_pts, "session": sess_pts,
                                   "liquidity": liq_pts, "zone": zone_pts,
                                   "flow": flow_pts, "htf": htf_pts},
                        reasons=reasons,
                        refs={"absorption": abs_ev.to_public()},
                        df_for_chart=m3,
                    ))
                    self._record(symbol, "absorption", side)

        # ── CONFLUENCE STACK (super signal) ──────────────────────────────
        if bias_dir:
            stack = self._stack_check(symbol, bias_dir)
            if stack >= 4:
                score = 100.0    # by definition the top tier
                reasons = [
                    f"[🔥] {stack} distinct factors fired in 30 min · same side",
                    f"[✓] Trend aligned 4/4",
                    f"[✓] Session: {session.upper()}",
                    f"[✓] Liquidity + zone + flow stacked",
                ]
                events.append(AlphaSignal(
                    type="confluence", symbol=symbol, side=bias_dir, timeframe="M3",
                    price=price, score=score, tier="PRIME 🔥🔥🔥",
                    session=session,
                    breakdown={"stack_factors": stack},
                    reasons=reasons, refs={"factor_count": stack},
                    df_for_chart=m3,
                ))
                # clear stack so we don't re-fire next tick
                self._recent[symbol] = []

        return events

    # ── helpers ─────────────────────────────────────────────────────────
    def _zone_pts_at(self, zones, price: float) -> tuple[float, object]:
        for z in zones:
            if z.contains(price):
                return self._zone_freshness_pts(z), z
        return 0.0, None

    @staticmethod
    def _zone_freshness_pts(z) -> float:
        if z.state == "fresh":      return W_ZONE
        if z.state == "tested" and z.test_count <= 1:   return W_ZONE * 0.6
        return W_ZONE * 0.3

    @staticmethod
    def _nearby_pool_pts(pools, side: str, price: float, atr: float) -> tuple[float, object]:
        """Pts if an unswept opposing pool sits within 1.5 ATR (room to run)."""
        if atr <= 0:    return 0.0, None
        want_side = "bsl" if side == "BUY" else "ssl"
        for p in pools:
            if p.swept or p.side != want_side:
                continue
            if abs(p.price - price) <= atr * 1.5:
                return W_LIQ * 0.6, p
        return 6.0, None

    @staticmethod
    def _flow_pts(orderflow, symbol: str, side: str) -> tuple[float, str]:
        # Recent OB mitigation in same direction = order-flow context
        obs = orderflow.obs_for(symbol)
        want = "bull" if side == "BUY" else "bear"
        for ob in obs:
            if ob.side == want and ob.mitigated and ob.mitigated_ts:
                if _time.time() - ob.mitigated_ts < 15 * 60:
                    return W_FLOW * 0.8, f"OB mitigation ({ob.timeframe})"
        return 0.0, ""


def _atr_value(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l),
                    (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1])
