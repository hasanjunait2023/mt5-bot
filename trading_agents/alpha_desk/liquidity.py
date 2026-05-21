"""Liquidity pool detection — where stop orders cluster.

Pool types we track:
  bsl_swing  — Buy-Side Liquidity = swing-high (stops sit above)
  ssl_swing  — Sell-Side Liquidity = swing-low (stops sit below)
  bsl_equal  — Equal highs (2+ within tolerance → magnet)
  ssl_equal  — Equal lows
  bsl_round  — Round-number above price (1.1000, 2645.00, etc.)
  ssl_round  — Round-number below price
  bsl_pdh    — Previous-day high
  ssl_pdl    — Previous-day low
  bsl_asian  — Asian-session high
  ssl_asian  — Asian-session low

Each pool tracks: price, side, kind, age_bars, distance-from-now, swept (bool).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .sessions import ASIA_START, ASIA_END


@dataclass
class Pool:
    symbol: str
    side: str           # "bsl" (above price, buy-side) | "ssl" (below price)
    kind: str           # swing | equal | round | pdh | pdl | asian
    price: float
    created_bar: int    # epoch s
    timeframe: str = "H1"
    swept: bool = False
    swept_ts: Optional[float] = None
    label: str = ""

    def to_public(self) -> dict:
        return asdict(self)


def _pip_decimals(symbol: str) -> int:
    if symbol.endswith("JPY"):  return 2
    if "OIL" in symbol:         return 2
    if symbol in ("XAUUSD",):   return 2
    if symbol in ("XAGUSD",):   return 3
    if symbol in ("BTCUSD",):   return 0
    return 4


def _swing_highs(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[int]:
    """Return bar indices where high is a swing-high (strict)."""
    h = df["high"].values
    out = []
    n = len(h)
    for i in range(left, n - right):
        win = h[i - left:i + right + 1]
        if h[i] == max(win) and (win == h[i]).sum() == 1:
            out.append(i)
    return out


def _swing_lows(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[int]:
    l = df["low"].values
    out = []
    n = len(l)
    for i in range(left, n - right):
        win = l[i - left:i + right + 1]
        if l[i] == min(win) and (win == l[i]).sum() == 1:
            out.append(i)
    return out


def _round_levels_near(price: float, dp: int, spread: float = 0.005) -> list[float]:
    """Round-number levels within `spread` (fraction of price) of current price."""
    out: list[float] = []
    if dp >= 4:                  # standard FX (1.1000, 1.1050 …)
        step = 0.0050
        anchor = round(price / step) * step
    elif dp == 2:                # JPY, XAU, oil
        step = 0.50 if price < 500 else 5.0
        anchor = round(price / step) * step
    elif dp == 3:                # XAG
        step = 0.10
        anchor = round(price / step) * step
    else:                        # BTC
        step = 500
        anchor = round(price / step) * step
    for k in (-2, -1, 0, 1, 2):
        lvl = round(anchor + k * step, dp)
        if abs(lvl - price) / max(price, 1e-9) <= spread:
            out.append(lvl)
    return out


class LiquidityTracker:
    """Per-symbol liquidity pool detector. Update by passing per-TF dataframes."""

    EQUAL_TOL_ATR     = 0.20    # equal H/L if within 0.2 × ATR
    SWING_LEFT_RIGHT  = 3
    MAX_POOLS_PER_SYM = 20

    def __init__(self):
        self._pools: dict[str, list[Pool]] = {}

    # ── ingest ───────────────────────────────────────────────────────────
    def ingest(self, symbol: str, h1: pd.DataFrame, h4: pd.DataFrame) -> None:
        if h1 is None or len(h1) < 50:
            return
        dp = _pip_decimals(symbol)
        atr = _atr_value(h1, 14)
        last = h1.iloc[-1]
        price = float(last["close"])

        store: list[Pool] = []

        # 1) Swing H/L on H1 (last ~80 bars)
        sub = h1.tail(80).reset_index(drop=True)
        for i in _swing_highs(sub, self.SWING_LEFT_RIGHT, self.SWING_LEFT_RIGHT):
            store.append(Pool(symbol=symbol, side="bsl", kind="swing",
                              price=round(float(sub.iloc[i]["high"]), dp),
                              created_bar=int(sub.iloc[i]["time"].timestamp()),
                              timeframe="H1", label="Swing High"))
        for i in _swing_lows(sub, self.SWING_LEFT_RIGHT, self.SWING_LEFT_RIGHT):
            store.append(Pool(symbol=symbol, side="ssl", kind="swing",
                              price=round(float(sub.iloc[i]["low"]), dp),
                              created_bar=int(sub.iloc[i]["time"].timestamp()),
                              timeframe="H1", label="Swing Low"))

        # 2) Equal highs / equal lows (cluster swing levels within EQUAL_TOL_ATR)
        if atr > 0:
            self._cluster_equals(store, atr)

        # 3) Round-number levels
        for lvl in _round_levels_near(price, dp):
            side = "bsl" if lvl > price else "ssl"
            store.append(Pool(symbol=symbol, side=side, kind="round",
                              price=lvl, created_bar=int(last["time"].timestamp()),
                              timeframe="H1",
                              label=f"Round {lvl}"))

        # 4) Previous-day H/L (from H1 bars of yesterday)
        now = datetime.now(timezone.utc)
        yest = (now - timedelta(days=1)).date()
        y_bars = h1[h1["time"].dt.date == yest]
        if len(y_bars) >= 12:
            pdh = float(y_bars["high"].max())
            pdl = float(y_bars["low"].min())
            store.append(Pool(symbol=symbol, side="bsl", kind="pdh",
                              price=round(pdh, dp),
                              created_bar=int(y_bars.iloc[-1]["time"].timestamp()),
                              timeframe="H1", label="Prev Day High"))
            store.append(Pool(symbol=symbol, side="ssl", kind="pdl",
                              price=round(pdl, dp),
                              created_bar=int(y_bars.iloc[-1]["time"].timestamp()),
                              timeframe="H1", label="Prev Day Low"))

        # 5) Asian-session H/L (today's 00:00-08:00 UTC, M1 ideally; use H1 if okay)
        today = now.date()
        asia_bars = h1[(h1["time"].dt.date == today) &
                       (h1["time"].dt.time >= ASIA_START) &
                       (h1["time"].dt.time <  ASIA_END)]
        if len(asia_bars) >= 4:
            ah = float(asia_bars["high"].max())
            al = float(asia_bars["low"].min())
            store.append(Pool(symbol=symbol, side="bsl", kind="asian",
                              price=round(ah, dp),
                              created_bar=int(asia_bars.iloc[-1]["time"].timestamp()),
                              timeframe="H1", label="Asian High"))
            store.append(Pool(symbol=symbol, side="ssl", kind="asian",
                              price=round(al, dp),
                              created_bar=int(asia_bars.iloc[-1]["time"].timestamp()),
                              timeframe="H1", label="Asian Low"))

        # 6) Detect sweeps — preserve swept status from prior store
        prev = self._pools.get(symbol, [])
        sweep_keys = {(p.kind, p.price, p.side): p for p in prev if p.swept}
        for p in store:
            old = sweep_keys.get((p.kind, p.price, p.side))
            if old:
                p.swept = True
                p.swept_ts = old.swept_ts

        # check whether the very latest bar swept any pool
        for p in store:
            if p.swept:
                continue
            if p.side == "bsl" and last["high"] > p.price and last["close"] < p.price:
                p.swept = True; p.swept_ts = _time.time()
            elif p.side == "ssl" and last["low"] < p.price and last["close"] > p.price:
                p.swept = True; p.swept_ts = _time.time()

        # dedupe by (kind, price, side) keeping the most recent
        dedup: dict[tuple, Pool] = {}
        for p in store:
            dedup[(p.kind, p.price, p.side)] = p
        store = list(dedup.values())

        # 7) cap size
        store.sort(key=lambda p: abs(p.price - price))   # nearest first
        self._pools[symbol] = store[:self.MAX_POOLS_PER_SYM]

    def _cluster_equals(self, store: list[Pool], atr: float):
        """Mark a swing-high / swing-low as 'equal' if within EQUAL_TOL_ATR
        of another swing of the same side. We rewrite the kind on hit."""
        tol = atr * self.EQUAL_TOL_ATR
        for side in ("bsl", "ssl"):
            swings = [p for p in store if p.side == side and p.kind == "swing"]
            for i, a in enumerate(swings):
                for b in swings[i + 1:]:
                    if abs(a.price - b.price) <= tol:
                        a.kind = "equal"
                        a.label = "Equal High" if side == "bsl" else "Equal Low"
                        b.kind = "equal"
                        b.label = a.label

    # ── queries ──────────────────────────────────────────────────────────
    def pools_for(self, symbol: str) -> list[Pool]:
        return list(self._pools.get(symbol, []))

    def nearest_pool(self, symbol: str, price: float,
                     side: Optional[str] = None,
                     unswept_only: bool = True) -> Optional[Pool]:
        pools = self.pools_for(symbol)
        if side:        pools = [p for p in pools if p.side == side]
        if unswept_only:pools = [p for p in pools if not p.swept]
        if not pools:   return None
        pools.sort(key=lambda p: abs(p.price - price))
        return pools[0]

    def snapshot(self) -> dict:
        return {sym: [p.to_public() for p in pools]
                for sym, pools in self._pools.items()}


def _atr_value(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l),
                    (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1])
