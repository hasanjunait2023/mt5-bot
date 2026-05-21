"""
Confluence Pullback Portfolio (CPP) — multi-symbol intraday strategy
====================================================================

Design (data + external research driven, see plan):

  Trade only WITH a strong higher-timeframe trend, entered on a shallow
  pullback, exited with a strict 1:2 structure whose exit mode is chosen
  by the live volatility/trend regime.

Signal stack (every filter is a proven edge from this repo's backtests
or 2024-25 literature):

  1. HTF trend bias .... close vs HTF EMA200 (S1/S2 proven)
  2. Trend STRENGTH .... ADX(14) >= adx_min  (the single biggest edge —
                         doubled S15's profit factor; #1 ranging-loss
                         filter in the research)
  3. Pullback trigger .. price retraced to EMA21 band + Stochastic deep
                         cross from OB/OS in trend direction (S14/S15)
  4. Momentum zone ..... RSI14 inside a trend-aligned band (S1 proven)
  5. Candle quality .... signal candle closes in trade direction with a
                         real body (filters indecision bars)

Exit (where the real edge lives — repo memory: trailing-runner exit 2x'd
S1/S2 PF, fixed 2R won for mean-reverting S6):

  - Strict initial 1:2  ............. TP = entry +/- 2 * SL_distance
  - Regime == "trend" (ADX high) ... bank 50% at +1R, lock breakeven,
                                     runner trails by TRAIL*ATR off peak,
                                     no hard cap (let winners run > 2R)
  - Regime == "range" (ADX low) .... plain fixed 1:2, no trailing

This module is pure (pandas/numpy only, no MT5). `backtest_runner.py`
drives it for historical sims, `mt5_bridge/mtf_live_trader.py` drives it
live, and `S19_Confluence_Pullback.mq5` mirrors it inside MT5 — all three
share the SAME logic so backtest == demo == EA.

The same per-bar feature snapshot is also what `trade_confirmation_agent`
scores, so the AI agent and the mechanical rules judge identical inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# ── tunable parameters (the backtest/improve loop sweeps these) ────────
DEFAULT_PARAMS: dict = {
    # higher-timeframe trend
    "htf_ema": 200,          # EMA period on the HTF (H1) for bias
    "htf_min_dist_atr": 0.0, # min |price-HTF_EMA| in HTF-ATRs (0 = off)
    # trend strength
    "adx_period": 14,
    "adx_min": 22.0,         # below this -> no trade at all
    "adx_trend": 30.0,       # at/above this -> "trend" regime (runner exit)
    # pullback
    "ema_fast": 21,          # the pullback magnet on the trading TF
    "pullback_atr": 0.6,     # entry only if price came within N*ATR of EMA21
    # stochastic deep cross
    "stoch_k": 14, "stoch_d": 3, "stoch_smooth": 3,
    "stoch_os": 25.0, "stoch_ob": 75.0,
    # momentum zone
    "rsi_period": 14,
    "rsi_buy": (40.0, 68.0), "rsi_sell": (32.0, 60.0),
    # risk / exit
    "atr_period": 14,
    "sl_atr": 1.5,           # SL distance = sl_atr * ATR
    "rr": 2.0,               # strict 1:2
    # "fixed"  = clean SL / 2R-TP / time-exit (honours the literal 1:2,
    #            makes win-rate the direct lever — the default)
    # "regime" = trend bars use partial+breakeven+ATR-trailing runner
    "exit_mode": "fixed",
    "use_breakeven": False,  # fixed mode: move SL->entry at +1R (off: cleaner 1:2)
    "trail_atr": 1.2,        # regime mode: runner trail distance (ATRs) off peak
    "be_at_r": 1.0,          # regime mode: lock BE / bank partial at +be_at_r*R
    "partial_frac": 0.5,     # regime mode: fraction banked at +1R
    "max_hold_bars": 96,     # time-exit (96 M15 bars = 24h)
    "min_body_frac": 0.30,   # signal-candle body must be >= this of range
    # session (UTC hours) — London + NY overlap is where the edge lives
    "sessions": ((7, 12), (13, 17)),
    "max_trades_day": 6,     # per symbol per day (caps daily DD budget)
    "risk_pct": 1.0,         # 1% equity per trade
}


# ── indicators (self-contained so the module unit-tests standalone) ────
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def adx(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Wilder ADX + directional indicators. Returns adx/plus_di/minus_di."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr_w = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / n, adjust=False).mean() / atr_w.replace(0, np.nan)
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / n, adjust=False).mean() / atr_w.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({
        "adx": dx.ewm(alpha=1 / n, adjust=False).mean(),
        "plus_di": pdi, "minus_di": mdi,
    })


def stochastic(df: pd.DataFrame, k: int, d: int, smooth: int) -> pd.DataFrame:
    ll = df["low"].rolling(k).min()
    hh = df["high"].rolling(k).max()
    raw_k = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    sk = raw_k.rolling(smooth).mean()
    return pd.DataFrame({"k": sk, "d": sk.rolling(d).mean()})


# ── feature snapshot (one row = everything rules + agent both judge) ───
@dataclass
class Setup:
    direction: str            # "BUY" | "SELL"
    reason: str               # human-readable confluence summary
    regime: str               # "trend" | "range"
    score: float              # 0-100 deterministic confluence score
    atr: float                # trading-TF ATR (price units) at signal
    adx: float
    rsi: float
    stoch_k: float
    pullback_atr: float       # how close to EMA21 the pullback came (ATRs)
    meta: dict = field(default_factory=dict)


def prepare(m15: pd.DataFrame, htf: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annotate trading-TF and HTF frames with all indicator columns.

    Returns (m15_annotated, htf_annotated). HTF alignment to each m15 bar
    is done by the caller via an as-of lookup (same proven pattern S1v2
    uses) so this stays pure and side-effect free.
    """
    m = m15.copy()
    h = htf.copy()
    m["ema_fast"] = ema(m["close"], p["ema_fast"])
    m["rsi"] = rsi(m["close"], p["rsi_period"])
    m["atr"] = atr(m, p["atr_period"])
    adx_df = adx(m, p["adx_period"])
    m["adx"] = adx_df["adx"]
    m["plus_di"] = adx_df["plus_di"]
    m["minus_di"] = adx_df["minus_di"]
    st = stochastic(m, p["stoch_k"], p["stoch_d"], p["stoch_smooth"])
    m["stoch_k"] = st["k"]
    m["stoch_d"] = st["d"]
    h["htf_ema"] = ema(h["close"], p["htf_ema"])
    h["htf_atr"] = atr(h, p["atr_period"])
    return m, h


def _in_session(hour: int, sessions) -> bool:
    return any(a <= hour < b for a, b in sessions)


def _confluence_score(direction: str, row, prev, htf_row, p: dict) -> float:
    """Deterministic 0-100 quality score. Mirrors the EA's score and is
    the input the AI confirmation agent reasons over (and its rule-based
    fallback uses directly). Higher = cleaner setup."""
    s = 0.0
    # ADX strength: 0..30 pts, saturating
    s += min(30.0, max(0.0, (row["adx"] - p["adx_min"]) * 2.0))
    # directional agreement of DI with the trade: 15 pts
    if (direction == "BUY" and row["plus_di"] > row["minus_di"]) or \
       (direction == "SELL" and row["minus_di"] > row["plus_di"]):
        s += 15.0
    # pullback tightness to EMA21: closer = better, 20 pts
    pb = abs(row["close"] - row["ema_fast"]) / max(row["atr"], 1e-9)
    s += max(0.0, 20.0 * (1.0 - pb / max(p["pullback_atr"], 1e-9)))
    # stochastic freshness (deep cross out of OB/OS): 20 pts
    if direction == "BUY":
        s += 20.0 if prev["stoch_k"] < p["stoch_os"] else 8.0
    else:
        s += 20.0 if prev["stoch_k"] > p["stoch_ob"] else 8.0
    # candle quality: real body in trade direction, 15 pts
    rng = max(row["high"] - row["low"], 1e-9)
    body = abs(row["close"] - row["open"]) / rng
    aligned = (row["close"] > row["open"]) if direction == "BUY" else (row["close"] < row["open"])
    if aligned and body >= p["min_body_frac"]:
        s += 15.0 * min(1.0, body / 0.6)
    return round(min(100.0, s), 1)


def detect(row, prev, htf_row, p: dict, *, hour: int) -> Optional[Setup]:
    """Pure entry detector. `row` = just-closed trading-TF bar, `prev` =
    the one before it, `htf_row` = as-of HTF bar. Returns a Setup or None.

    Used identically by the backtest, the live trader, and (logic-mirrored)
    the MQL5 EA so backtest == demo == EA.
    """
    # need warm indicators
    for v in (row["adx"], row["ema_fast"], row["rsi"], row["atr"],
              row["stoch_k"], prev["stoch_k"], htf_row["htf_ema"]):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
    if not _in_session(hour, p["sessions"]):
        return None
    if row["atr"] <= 0:
        return None

    # 1+2. HTF trend bias gated by ADX strength
    if row["adx"] < p["adx_min"]:
        return None
    bias = 1 if row["close"] > htf_row["htf_ema"] else -1
    if p["htf_min_dist_atr"] > 0 and htf_row.get("htf_atr", 0):
        if abs(row["close"] - htf_row["htf_ema"]) < p["htf_min_dist_atr"] * htf_row["htf_atr"]:
            return None

    direction = "BUY" if bias == 1 else "SELL"

    # 3. pullback: price must have come back near EMA21
    pb_atr = abs(row["close"] - row["ema_fast"]) / row["atr"]
    if pb_atr > p["pullback_atr"]:
        return None

    # 3b. stochastic deep cross in trend direction
    if direction == "BUY":
        deep = prev["stoch_k"] < p["stoch_os"]
        cross = prev["stoch_k"] <= prev["stoch_d"] and row["stoch_k"] > row["stoch_d"]
        di_ok = row["plus_di"] > row["minus_di"]
    else:
        deep = prev["stoch_k"] > p["stoch_ob"]
        cross = prev["stoch_k"] >= prev["stoch_d"] and row["stoch_k"] < row["stoch_d"]
        di_ok = row["minus_di"] > row["plus_di"]
    if not (deep and cross and di_ok):
        return None

    # 4. momentum zone
    lo, hi = p["rsi_buy"] if direction == "BUY" else p["rsi_sell"]
    if not (lo <= row["rsi"] <= hi):
        return None

    # 5. candle quality
    rng = max(row["high"] - row["low"], 1e-9)
    body = abs(row["close"] - row["open"]) / rng
    aligned = (row["close"] > row["open"]) if direction == "BUY" else (row["close"] < row["open"])
    if not (aligned and body >= p["min_body_frac"]):
        return None

    regime = "trend" if row["adx"] >= p["adx_trend"] else "range"
    score = _confluence_score(direction, row, prev, htf_row, p)
    reason = (f"{direction} {regime} | ADX {row['adx']:.1f} "
              f"DI{'+' if direction == 'BUY' else '-'} | pull {pb_atr:.2f}atr "
              f"| stoch {row['stoch_k']:.0f} | RSI {row['rsi']:.0f} | score {score}")
    return Setup(direction=direction, reason=reason, regime=regime,
                 score=score, atr=float(row["atr"]), adx=float(row["adx"]),
                 rsi=float(row["rsi"]), stoch_k=float(row["stoch_k"]),
                 pullback_atr=float(pb_atr))


def sl_tp(setup: Setup, entry: float, p: dict) -> tuple[float, float, float]:
    """Strict 1:2. Returns (sl_price, tp_price, sl_distance_price)."""
    sl_dist = p["sl_atr"] * setup.atr
    if setup.direction == "BUY":
        return entry - sl_dist, entry + p["rr"] * sl_dist, sl_dist
    return entry + sl_dist, entry - p["rr"] * sl_dist, sl_dist
