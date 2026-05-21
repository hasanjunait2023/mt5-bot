"""Order-flow signals: absorption + order blocks.

ABSORPTION:
  Heavy tick-volume with tiny range = institutions absorbing flow.
  Trigger when volume z-score (last 20) > 1.5 AND range < 0.6 × ATR(14).
  Direction inferred: if close > mid → buyers absorbing → bullish bias.

ORDER BLOCKS:
  The last opposite-direction candle before a strong impulsive move.
  - Bullish OB: last bearish candle before a strong bullish impulse
  - Bearish OB: last bullish candle before a strong bearish impulse
  Mitigation = price returning to that candle's body later. Mitigation is
  the actual entry signal; the OB itself is just a marked level.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class AbsorptionEvent:
    symbol: str
    timeframe: str
    side: str          # "bull" | "bear"
    price: float
    vol_z: float
    range_ratio: float
    bar_ts: int

    def to_public(self) -> dict:
        return asdict(self)


@dataclass
class OrderBlock:
    symbol: str
    timeframe: str
    side: str          # "bull" | "bear"
    top: float
    bottom: float
    created_bar: int
    mitigated: bool = False
    mitigated_ts: Optional[float] = None

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def to_public(self) -> dict:
        return asdict(self)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l),
                    (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


class OrderFlowDetector:
    ABSORPTION_VOL_Z   = 1.5
    ABSORPTION_RANGE_R = 0.6      # range / ATR
    OB_IMPULSE_ATR     = 2.0
    MAX_OBS            = 6

    def __init__(self):
        self._obs: dict[str, dict[str, list[OrderBlock]]] = {}

    # ── absorption (real-time, per latest bar) ────────────────────────
    def detect_absorption(self, symbol: str, tf: str,
                          df: pd.DataFrame) -> Optional[AbsorptionEvent]:
        if df is None or len(df) < 25:
            return None
        if "tick_volume" not in df.columns:
            return None
        v = df["tick_volume"].astype(float)
        vol_mean = v.tail(20).mean()
        vol_std  = v.tail(20).std() or 1.0
        last = df.iloc[-1]
        vol_z = (float(last["tick_volume"]) - vol_mean) / vol_std
        atr  = float(_atr(df, 14).iloc[-1] or 0.0)
        if atr <= 0:
            return None
        rng = float(last["high"] - last["low"])
        range_ratio = rng / atr
        if vol_z < self.ABSORPTION_VOL_Z:
            return None
        if range_ratio > self.ABSORPTION_RANGE_R:
            return None
        mid = (last["high"] + last["low"]) / 2
        side = "bull" if last["close"] >= mid else "bear"
        return AbsorptionEvent(
            symbol=symbol, timeframe=tf, side=side,
            price=float(last["close"]),
            vol_z=round(vol_z, 2),
            range_ratio=round(range_ratio, 2),
            bar_ts=int(last["time"].timestamp()),
        )

    # ── order-block scanner ─────────────────────────────────────────────
    def scan_order_blocks(self, symbol: str, tf: str, df: pd.DataFrame) -> None:
        if df is None or len(df) < 30:
            return
        atr = _atr(df, 14)
        store = self._obs.setdefault(symbol, {}).setdefault(tf, [])

        # Update existing OBs (mitigation check)
        last = df.iloc[-1]
        for ob in list(store):
            if not ob.mitigated and ob.contains(float(last["close"])):
                ob.mitigated = True
                ob.mitigated_ts = _time.time()
            # invalidate if price closed beyond the far side
            if ob.side == "bull" and last["close"] < ob.bottom - atr.iloc[-1] * 0.5:
                store.remove(ob)
            elif ob.side == "bear" and last["close"] > ob.top + atr.iloc[-1] * 0.5:
                store.remove(ob)

        existing = {ob.created_bar for ob in store}
        for i in range(max(2, len(df) - 50), len(df) - 1):
            atr_i = atr.iloc[i]
            if atr_i <= 0 or pd.isna(atr_i):
                continue
            imp = df.iloc[i]
            imp_range = float(imp["high"] - imp["low"])
            if imp_range < atr_i * self.OB_IMPULSE_ATR:
                continue
            prior = df.iloc[i - 1]
            imp_bull = imp["close"] > imp["open"]
            prior_bear = prior["close"] < prior["open"]
            if imp_bull and prior_bear:
                side = "bull"
                top, bot = float(prior["high"]), float(prior["low"])
            elif (not imp_bull) and (not prior_bear):
                side = "bear"
                top, bot = float(prior["high"]), float(prior["low"])
            else:
                continue
            origin_ts = int(prior["time"].timestamp())
            if origin_ts in existing:
                continue
            store.append(OrderBlock(
                symbol=symbol, timeframe=tf, side=side,
                top=top, bottom=bot, created_bar=origin_ts,
            ))

        # cap
        if len(store) > self.MAX_OBS:
            store.sort(key=lambda o: o.created_bar, reverse=True)
            del store[self.MAX_OBS:]

    def obs_for(self, symbol: str, tf: Optional[str] = None) -> list[OrderBlock]:
        per_tf = self._obs.get(symbol, {})
        if tf:
            return list(per_tf.get(tf, []))
        out: list[OrderBlock] = []
        for v in per_tf.values():
            out.extend(v)
        return out

    def snapshot(self) -> dict:
        return {sym: {tf: [o.to_public() for o in obs] for tf, obs in tfs.items()}
                for sym, tfs in self._obs.items()}
