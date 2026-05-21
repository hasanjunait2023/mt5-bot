"""Supply & Demand zone detection + lifecycle tracker.

Detection rule (simple but effective):
  A zone forms from an "imbalance candle" — a strong-impulse bar (range >=
  2.0 × ATR(14)) where the prior candle's body was small (consolidation).
  The prior small-body candle is the origin zone:
    - Bearish impulse → SUPPLY zone (origin candle's high/low define the box)
    - Bullish impulse → DEMAND zone

Lifecycle states:
  fresh   — never tested by a subsequent bar
  tested  — at least one bar wicked inside but didn't break
  broken  — a bar closed beyond the opposite edge → invalidated, removed

Per symbol, we keep the last N active zones per timeframe (H1 + H4 by default).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class Zone:
    symbol: str
    timeframe: str               # "H1" | "H4"
    side: str                    # "supply" | "demand"
    top: float
    bottom: float
    created_ts: float            # epoch seconds
    created_bar: int             # epoch of origin bar
    state: str = "fresh"         # fresh | tested | broken
    test_count: int = 0
    last_test_ts: Optional[float] = None
    strength: float = 1.0        # impulse-range / ATR multiple

    def height(self) -> float:
        return abs(self.top - self.bottom)

    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def bar_overlaps(self, low: float, high: float) -> bool:
        return not (high < self.bottom or low > self.top)

    def to_public(self) -> dict:
        return asdict(self)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l),
                    (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


class ZoneTracker:
    """Per-symbol zone store. Update with .ingest(symbol, tf, df) each tick."""

    IMPULSE_ATR_MULT = 2.0       # impulse bar range >= this × ATR
    PRIOR_BODY_MAX   = 0.5       # prior candle body must be <= half its range
    MAX_ZONES_PER_TF = 8
    SCAN_LOOKBACK    = 50        # scan only last N bars per ingest

    def __init__(self):
        self._zones: dict[str, dict[str, list[Zone]]] = {}   # symbol -> tf -> [Zone]

    # ── ingestion ────────────────────────────────────────────────────────
    def ingest(self, symbol: str, tf_label: str, df: pd.DataFrame) -> None:
        if df is None or len(df) < 30:
            return
        atr = _atr(df, 14)
        store = self._zones.setdefault(symbol, {}).setdefault(tf_label, [])

        # 1. Update existing zones (test / break)
        latest = df.iloc[-1]
        for z in list(store):
            if z.bar_overlaps(float(latest["low"]), float(latest["high"])):
                z.test_count += 1
                z.last_test_ts = _time.time()
                if z.state == "fresh":
                    z.state = "tested"
            # break detection: close beyond opposite edge
            if z.side == "supply" and latest["close"] > z.top:
                store.remove(z)
                continue
            if z.side == "demand" and latest["close"] < z.bottom:
                store.remove(z)
                continue

        # 2. Scan recent bars for new zones (don't double-count by created_bar)
        existing_bars = {z.created_bar for z in store}
        scan_from = max(2, len(df) - self.SCAN_LOOKBACK)
        for i in range(scan_from, len(df) - 1):    # leave last bar out
            atr_i = atr.iloc[i]
            if atr_i <= 0 or pd.isna(atr_i):
                continue
            impulse = df.iloc[i]
            prior   = df.iloc[i - 1]

            imp_range = float(impulse["high"] - impulse["low"])
            if imp_range < atr_i * self.IMPULSE_ATR_MULT:
                continue

            prior_range = float(prior["high"] - prior["low"])
            if prior_range <= 0:
                continue
            prior_body  = float(abs(prior["close"] - prior["open"]))
            if prior_body / prior_range > self.PRIOR_BODY_MAX:
                continue

            is_bull = impulse["close"] > impulse["open"]
            side    = "demand" if is_bull else "supply"
            top     = float(prior["high"])
            bot     = float(prior["low"])
            origin_ts = int(prior["time"].timestamp())

            if origin_ts in existing_bars:
                continue
            z = Zone(
                symbol=symbol, timeframe=tf_label, side=side,
                top=top, bottom=bot,
                created_ts=_time.time(), created_bar=origin_ts,
                strength=round(imp_range / atr_i, 2),
            )
            store.append(z)

        # 3. Cap store size — keep newest N
        if len(store) > self.MAX_ZONES_PER_TF:
            store.sort(key=lambda z: z.created_ts, reverse=True)
            del store[self.MAX_ZONES_PER_TF:]

    # ── queries ──────────────────────────────────────────────────────────
    def zones_for(self, symbol: str, tf: Optional[str] = None) -> list[Zone]:
        per_tf = self._zones.get(symbol, {})
        if tf:
            return list(per_tf.get(tf, []))
        out: list[Zone] = []
        for v in per_tf.values():
            out.extend(v)
        return out

    def zone_at_price(self, symbol: str, price: float,
                      tf: Optional[str] = None) -> Optional[Zone]:
        for z in self.zones_for(symbol, tf):
            if z.contains(price):
                return z
        return None

    def near_zones(self, symbol: str, price: float, atr_units: float,
                   tf: Optional[str] = None) -> list[Zone]:
        """Zones within `atr_units` ATR of current price."""
        # caller passes distance threshold already in price-units; here we
        # simply filter by absolute distance to zone mid.
        out = []
        for z in self.zones_for(symbol, tf):
            if abs(z.mid() - price) <= atr_units:
                out.append(z)
        return out

    def snapshot(self) -> dict:
        return {sym: {tf: [z.to_public() for z in zs] for tf, zs in tfs.items()}
                for sym, tfs in self._zones.items()}
