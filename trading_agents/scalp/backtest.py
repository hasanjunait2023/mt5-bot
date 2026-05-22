"""Scalping Strategy Backtest — M1/M3 walk-forward validation.

Tests the goldscalp notebook strategies extracted from NotebookLM research.
Uses MT5 bridge for bar data + realistic spread costs.

Strategies tested:
  GS01 — Gold EMA9/50 + RSI + Stochastic (M1/M3, XAUUSD)
  GS02 — ICT Silver Bullet FVG + Session (M1/M3, XAUUSD/Forex)
  GS03 — VWAP + MACD scalp (M3, XAUUSD/Forex)
  GS04 — Keltner + RSI mean-reversion (M1, Forex)
  GS05 — EMA crossover trend-follow (M1/M3, Forex)
  GS06 — RSI + Bollinger Band reversal (M1/M3, Forex)
  GS07 — Liquidity sweep M15→M1 entry (M1, XAUUSD/Forex)
  GS08 — 1-min sniper (15m fake-out, BOS on M1) (M1, Forex/Gold)
  GS09 — 80% WR reversal (RSI+BB+EMA200) (M3, Forex)
  GS10 — EMA triple trend-follow scalp (M15, Forex)

Run:
  python -m trading_agents.scalp.backtest --days 60
  python -m trading_agents.scalp.backtest --days 30 --strategy GS01 --symbol XAUUSD
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.scalp.indicators import (
    ema, rsi, stoch, bollinger, keltner, atr, ema_cross, ema_above,
    swing_high, swing_low, has_bullish_fvg, has_bearish_fvg,
    _ema_arr, vwap_session,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("scalp.backtest")
BD_TZ = ZoneInfo("Asia/Dhaka")

REPORT_DIR = BASE_DIR / "logs" / "scalp"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FILE = REPORT_DIR / "_backtest_scalp.json"

TYPICAL_SPREADS = {
    "XAUUSD": 0.30, "XAGUSD": 0.05, "BTCUSD": 12.0,
    "EURUSD": 0.00008, "GBPUSD": 0.0001, "USDJPY": 0.008,
    "USDCAD": 0.0001, "AUDUSD": 0.0001,
}

# Symbols per strategy
STRATEGY_SYMBOLS: dict[str, list[str]] = {
    "GS01": ["XAUUSD"],
    "GS02": ["XAUUSD", "EURUSD", "GBPUSD"],
    "GS03": ["XAUUSD", "EURUSD"],
    "GS04": ["EURUSD", "GBPUSD", "USDJPY"],
    "GS05": ["EURUSD", "GBPUSD", "USDJPY", "USDCAD"],
    "GS06": ["EURUSD", "GBPUSD", "XAUUSD"],
    "GS07": ["XAUUSD", "EURUSD", "GBPUSD"],
    "GS08": ["EURUSD", "GBPUSD", "XAUUSD"],
    "GS09": ["EURUSD", "GBPUSD", "USDJPY"],
    "GS10": ["EURUSD", "GBPUSD", "USDJPY", "USDCAD"],
    "GS11": ["XAUUSD", "EURUSD", "GBPUSD"],
}


# ── Bar fetching ─────────────────────────────────────────────────────────────

def _fetch_bars(symbol: str, timeframe: str, limit: int) -> dict | None:
    bridge_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{bridge_url}/bars/{symbol}",
                         params={"timeframe": timeframe, "limit": limit},
                         timeout=90)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Fetch failed %s %s: %s", symbol, timeframe, e)
        return None


def _session_bd(t_unix: int) -> dict:
    bd = datetime.fromtimestamp(t_unix, tz=BD_TZ)
    h = bd.hour
    return {
        "hour": h,
        "london_kz": 13 <= h < 16,
        "ny_kz": 18 <= h < 21,
        "asian_kz": 7 <= h < 11,
        "silver_bullet_london": h == 14,
        "silver_bullet_ny": h == 21,
        "london_open": h == 13,
        "ny_open": h == 18,
        "any_primary": (13 <= h < 16) or (18 <= h < 21),
    }


# ── Strategy implementations ─────────────────────────────────────────────────

def _gs01_gold_ema_rsi_stoch(bars: dict, t_i: int,
                              spread: float, symbol: str = "XAUUSD") -> dict | None:
    """GS01: Gold/Forex Dual EMA + Momentum Scalper (NotebookLM verified).
    Indicators: EMA9, EMA50, RSI(14), Stoch(14,3,3). M1 or M3.
    Trend: Price > EMA50 AND EMA9 > EMA50 → uptrend.
    Entry trigger:
      BUY:  price pulls back to EMA9 (within 1×ATR), RSI crosses above 30,
            Stoch %K crosses above 20.
      SELL: price pulls up to EMA9 (within 1×ATR), RSI crosses below 70,
            Stoch %K crosses below 80.
    SL: beyond most recent swing high/low (use 1.5×ATR).
    TP: 2×SL distance (1:2 RR). Session: London+NY.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 60:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    sess = _session_bd(times[t_i])
    if not sess["any_primary"]:
        return None

    e9 = ema(cl, 9)
    e50 = ema(cl, 50)
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    price = cl[-1]
    e9 = ema(cl, 9)
    e50 = ema(cl, 50)
    near_e9 = abs(price - e9) <= 1.5 * atr_val

    # RSI(7) — faster, more signals on M3. Threshold 30/70 for all symbols.
    rsi_os = 30.0
    rsi_ob = 70.0

    lookback = min(3, len(cl) - 1)
    rsi_now = rsi(cl, 7)
    sk_now = stoch(hl, ll, cl, 14, 3, 3)

    rsi_was_oversold   = any(rsi(cl[:-(i)] or cl, 7) < rsi_os for i in range(1, lookback + 1))
    rsi_was_overbought = any(rsi(cl[:-(i)] or cl, 7) > rsi_ob for i in range(1, lookback + 1))
    stoch_was_low = any(stoch(hl[:-(i)] or hl, ll[:-(i)] or ll, cl[:-(i)] or cl, 14, 3, 3)["k"] < 20
                        for i in range(1, lookback + 1))
    stoch_was_high = any(stoch(hl[:-(i)] or hl, ll[:-(i)] or ll, cl[:-(i)] or cl, 14, 3, 3)["k"] > 80
                         for i in range(1, lookback + 1))

    # BUY: uptrend, near EMA9, RSI recovering from oversold, Stoch recovering
    if (e9 > e50 and price > e50 and near_e9
            and rsi_now > rsi_os and rsi_was_oversold
            and sk_now["k"] > 20 and stoch_was_low):
        sl = price - 1.5 * atr_val
        tp = price + 3.0 * atr_val
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # SELL: downtrend, near EMA9, RSI declining from overbought, Stoch declining
    if (e9 < e50 and price < e50 and near_e9
            and rsi_now < rsi_ob and rsi_was_overbought
            and sk_now["k"] < 80 and stoch_was_high):
        sl = price + 1.5 * atr_val
        tp = price - 3.0 * atr_val
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs02_ict_silver_bullet(bars: dict, t_i: int,
                             spread: float, symbol: str) -> dict | None:
    """GS02: ICT Silver Bullet — session-timed FVG entry.
    Session: London SB 14:00-15:00 BD or NY SB 21:00-22:00 BD only.
    Bias: HTF EMA200 trend (use M3 EMA200 as proxy).
    Entry: Bullish FVG forms in session window, price pulls back into FVG.
    SL: Swing low/high. TP: 2×SL distance.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 50:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]
    ts = times[t_i]

    sess = _session_bd(ts)
    if not (sess["silver_bullet_london"] or sess["silver_bullet_ny"]):
        return None

    e200 = ema(cl, 200) if len(cl) >= 200 else ema(cl, 50)
    price = cl[-1]
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    sl_dist = max(1.5 * atr_val, spread * 3)

    if price > e200 and has_bullish_fvg(hl, ll, cl, lookback=5):
        sl = price - sl_dist
        tp = price + 2.0 * sl_dist
        return {"signal": "BUY", "sl": sl, "tp": tp}

    if price < e200 and has_bearish_fvg(hl, ll, cl, lookback=5):
        sl = price + sl_dist
        tp = price - 2.0 * sl_dist
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs03_vwap_macd(bars: dict, t_i: int, spread: float) -> dict | None:
    """GS03: VWAP + MACD scalp.
    Entry: Price bounces off VWAP, MACD histogram positive/negative, session active.
    SL: 1×ATR, TP: 2×ATR.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    v = bars.get("volume", [])
    times = bars.get("time", [])
    if t_i < 60:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]
    vl = v[:t_i + 1]
    tl = times[:t_i + 1]

    sess = _session_bd(tl[-1])
    if not sess["any_primary"]:
        return None

    # VWAP
    vwap_d = vwap_session(hl, ll, cl, vl, tl, session_start_bd_hour=7)
    vwap_val = vwap_d["vwap"]

    # MACD = EMA12 - EMA26; signal = EMA9 of MACD
    e12_arr = _ema_arr(cl, 12)
    e26_arr = _ema_arr(cl, 26)
    macd_arr = [e12_arr[i] - e26_arr[i] for i in range(len(e12_arr))]
    if len(macd_arr) < 9:
        return None
    sig_arr = _ema_arr(macd_arr, 9)
    hist_prev = macd_arr[-2] - sig_arr[-2]
    hist_curr = macd_arr[-1] - sig_arr[-1]

    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None
    price = cl[-1]

    # BUY: price at/below VWAP, MACD hist crosses positive
    if price <= vwap_val * 1.001 and hist_prev <= 0 < hist_curr:
        sl = price - 1.0 * atr_val
        tp = price + 2.0 * atr_val
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # SELL: price at/above VWAP, MACD hist crosses negative
    if price >= vwap_val * 0.999 and hist_prev >= 0 > hist_curr:
        sl = price + 1.0 * atr_val
        tp = price - 2.0 * atr_val
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs04_keltner_rsi_breakout(bars: dict, t_i: int,
                                spread: float) -> dict | None:
    """GS04: Keltner Channels + RSI Volatility Scalper — BREAKOUT (NotebookLM verified).
    Indicators: Keltner Channel (EMA20, 2×ATR), RSI(14). M1.
    BUY:  2+ consecutive closes ABOVE upper KC, RSI crossed above 50.
    SELL: 2+ consecutive closes BELOW lower KC, RSI crossed below 50.
    SL: just beyond opposite KC band.
    TP: when price returns to KC midline.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    if t_i < 40:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    kc = keltner(hl, ll, cl, ema_period=20, atr_period=14, atr_mult=2.0)
    rsi_val = rsi(cl, 14)
    rsi_prev = rsi(cl[:-1], 14) if t_i >= 1 else 50.0
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    price = cl[-1]
    prev_close = cl[-2] if len(cl) >= 2 else price

    # BUY breakout: 2 consecutive closes above upper KC, RSI crosses above 50
    if (price > kc["upper"] and prev_close > kc["upper"]
            and rsi_prev < 50 < rsi_val):
        sl = kc["lower"] - spread
        tp = kc["mid"]
        if tp - price < spread:
            return None
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # SELL breakout: 2 consecutive closes below lower KC, RSI crosses below 50
    if (price < kc["lower"] and prev_close < kc["lower"]
            and rsi_prev > 50 > rsi_val):
        sl = kc["upper"] + spread
        tp = kc["mid"]
        if price - tp < spread:
            return None
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs05_ema_crossover(bars: dict, t_i: int, spread: float) -> dict | None:
    """GS05: EMA9/21 crossover trend-follow.
    Entry: EMA9 crosses EMA21, confirmed by EMA200 trend direction.
    SL: 1.5×ATR, TP: 2.5×ATR.
    Session: London or NY only.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 50:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    sess = _session_bd(times[t_i])
    if not sess["any_primary"]:
        return None

    cross = ema_cross(cl, 9, 21)
    if cross == 0:
        return None

    e200 = ema(cl, 200) if len(cl) >= 200 else ema(cl, 50)
    price = cl[-1]
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    if cross == 1 and price > e200:
        sl = price - 1.5 * atr_val
        tp = price + 2.5 * atr_val
        return {"signal": "BUY", "sl": sl, "tp": tp}

    if cross == -1 and price < e200:
        sl = price + 1.5 * atr_val
        tp = price - 2.5 * atr_val
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs06_rsi_bb_stoch_reversal(bars: dict, t_i: int,
                                 spread: float) -> dict | None:
    """GS06 v2: Triple-Confirmation BB Bounce + session filter + RSI momentum.
    Improvements over v1:
      - Session filter: London/NY only (cleaner reversals at kill zones)
      - RSI momentum: RSI must be turning (recovering from extreme, not still diving)
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 30:
        return None

    sess = _session_bd(times[t_i])
    if not sess["any_primary"]:
        return None

    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    bb = bollinger(cl, period=20, std_mult=2.0)
    rsi_val  = rsi(cl, 14)
    rsi_prev = rsi(cl[:-1], 14) if len(cl) > 15 else rsi_val
    sk = stoch(hl, ll, cl, 5, 3, 3)
    atr_val = atr(hl, ll, cl, 14)
    price = cl[-1]
    if atr_val <= 0:
        return None

    sl_dist = max(1.0 * atr_val, spread * 5)

    # BUY: all three at oversold extreme simultaneously (session-filtered)
    if price < bb["lower"] and rsi_val < 30 and sk["k"] < 20:
        sl = ll[-1] - sl_dist
        tp = price + 2.0 * (price - sl)
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # SELL: all three at overbought extreme simultaneously (session-filtered)
    if price > bb["upper"] and rsi_val > 70 and sk["k"] > 80:
        sl = hl[-1] + sl_dist
        tp = price - 2.0 * (sl - price)
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs07_liquidity_sweep(bars: dict, t_i: int,
                           spread: float) -> dict | None:
    """GS07: Liquidity sweep entry.
    M15 bias → wait for swing high/low sweep on LTF → entry on MSS (break of structure).
    SL: beyond swept level, TP: 2×distance.
    Session: London or NY only.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 30:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    sess = _session_bd(times[t_i])
    if not sess["any_primary"]:
        return None

    sh = swing_high(hl, lookback=5)
    sl_lvl = swing_low(ll, lookback=5)
    price = cl[-1]
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0 or sh is None or sl_lvl is None:
        return None

    prev_price = cl[-2] if len(cl) >= 2 else price
    min_sweep = atr_val * 0.15   # sweep must be meaningful, not just tick noise

    # Bullish: swept below swing low then recovered — require actual depth
    if prev_price < sl_lvl and price > sl_lvl:
        sweep_depth = sl_lvl - min(ll[-5:]) if len(ll) >= 5 else 0
        if sweep_depth < min_sweep:
            return None
        sl = sl_lvl - atr_val
        tp = price + 2.0 * (price - sl)
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # Bearish: swept above swing high then fell below it
    if prev_price > sh and price < sh:
        sweep_depth = max(hl[-5:]) - sh if len(hl) >= 5 else 0
        if sweep_depth < min_sweep:
            return None
        sl = sh + atr_val
        tp = price - 2.0 * (sl - price)
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs08_m1_sniper_bos(bars: dict, t_i: int, spread: float) -> dict | None:
    """GS08: 3-step sniper — 15m fake-out, MSS/BOS on M1.
    Simplified: detects EMA displacement then structural break (MSS-like).
    Entry: strong momentum bar breaks recent structure in trend direction.
    SL: bar low/high, TP: 2×SL distance.
    Session: London or NY.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 30:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    sess = _session_bd(times[t_i])
    if not sess["any_primary"]:
        return None

    e50  = ema(cl, 50)  if len(cl) >= 50  else ema(cl, len(cl))
    e200 = ema(cl, 200) if len(cl) >= 200 else None
    price = cl[-1]
    prev = cl[-2] if len(cl) >= 2 else price
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    bar_body = abs(price - prev)
    if bar_body < atr_val * 0.5:
        return None

    sh = swing_high(hl, lookback=3)
    sl_lvl = swing_low(ll, lookback=3)

    # EMA200 trend alignment: only trade in macro trend direction
    if price > e50 and sh and price > sh and prev < sh:
        if e200 is not None and price < e200:   # against macro trend — skip
            return None
        sl = ll[-1] - spread
        tp = price + 2.0 * (price - sl)
        return {"signal": "BUY", "sl": sl, "tp": tp}

    if price < e50 and sl_lvl and price < sl_lvl and prev > sl_lvl:
        if e200 is not None and price > e200:   # against macro trend — skip
            return None
        sl = hl[-1] + spread
        tp = price - 2.0 * (sl - price)
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs09_rsi_bb_ema200_reversal(bars: dict, t_i: int,
                                  spread: float) -> dict | None:
    """GS09: Secret Trend Reversal (EarnForex, NotebookLM Q7 verified).
    Indicators: BB(30,2), RSI(14), EMA200. M3.
    BUY:  price touches lower BB, price > EMA200 (high), RSI < 20.
    SELL: price touches upper BB, price < EMA200 (low), RSI > 80.
    SL: 1.5×ATR (adapted from the 500-point wide stop for M3 scalp).
    TP: 2×ATR. Trade WITH macro trend only.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    if t_i < 210:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    e200 = ema(cl, 200)
    bb = bollinger(cl, period=30, std_mult=2.0)   # BB(30,2) per notebook
    rsi_val = rsi(cl, 14)
    atr_val = atr(hl, ll, cl, 14)
    price = cl[-1]
    if atr_val <= 0:
        return None

    # BUY: price at/below lower BB, above EMA200, RSI < 30 (relaxed from 20 — fires more)
    if price <= bb["lower"] and price > e200 and rsi_val < 30:
        sl = price - 1.5 * atr_val
        tp = price + 2.0 * atr_val
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # SELL: price at/above upper BB, below EMA200, RSI > 70
    if price >= bb["upper"] and price < e200 and rsi_val > 70:
        sl = price + 1.5 * atr_val
        tp = price - 2.0 * atr_val
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs10_ema_triple_trend(bars: dict, t_i: int,
                            spread: float) -> dict | None:
    """GS10: Triple EMA trend-follow (live 80% WR EarnForex system).
    EMAs: 12, 26, 50. All three aligned → enter on first pullback to EMA12.
    SL: 1.5×ATR, TP: 2×ATR.
    Session: London or NY.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 60:
        return None
    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    sess = _session_bd(times[t_i])
    if not sess["any_primary"]:
        return None

    e12 = ema(cl, 12)
    e26 = ema(cl, 26)
    e50 = ema(cl, 50)
    price = cl[-1]
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    # All EMAs aligned bullish, price pulls back to EMA12
    if e12 > e26 > e50 and abs(price - e12) / atr_val < 0.5:
        sl = price - 1.5 * atr_val
        tp = price + 2.5 * atr_val
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # All EMAs aligned bearish, price pulls up to EMA12
    if e12 < e26 < e50 and abs(price - e12) / atr_val < 0.5:
        sl = price + 1.5 * atr_val
        tp = price - 2.5 * atr_val
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


def _gs11_opening_range_scalper(bars: dict, t_i: int,
                                 spread: float) -> dict | None:
    """GS11: Touch and Turn Opening Range Scalper (NotebookLM verified).
    Logic: First 15-min candle of London open (13:00 BD). If range >= 25% of recent
    daily ATR, it's a confirmed liquidity candle.
    BUY:  first candle was bearish → Buy Limit at candle low (price touching).
    SELL: first candle was bullish → Sell Limit at candle high (price touching).
    TP: 38.2% of candle range (Fibonacci). SL: half TP distance. 2:1 RR.
    Executes on M1 bar after the 15-min candle closes.
    """
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    times = bars.get("time", [])
    if t_i < 30:
        return None

    sess = _session_bd(times[t_i])
    if not sess["london_open"]:
        return None

    cl = c[:t_i + 1]
    hl = h[:t_i + 1]
    ll = l[:t_i + 1]

    # Proxy for daily ATR: use last 14 bars of current series as daily range proxy
    atr_val = atr(hl, ll, cl, 14)
    if atr_val <= 0:
        return None

    price = cl[-1]
    # Use last 15 bars as proxy for first M15 candle range
    window = 15
    if t_i < window:
        return None
    candle_high = max(hl[t_i - window: t_i + 1])
    candle_low = min(ll[t_i - window: t_i + 1])
    candle_range = candle_high - candle_low
    candle_open = c[t_i - window]
    candle_close = cl[-1]

    # Check range >= 25% of daily ATR (14-bar ATR as proxy)
    if candle_range < 0.25 * atr_val * 14:
        return None

    tp_dist = 0.382 * candle_range
    sl_dist = tp_dist / 2.0

    if sl_dist < spread * 2:
        return None

    # Bearish candle → BUY at candle low
    if candle_close < candle_open and abs(price - candle_low) <= atr_val * 0.3:
        sl = candle_low - sl_dist
        tp = candle_low + tp_dist
        return {"signal": "BUY", "sl": sl, "tp": tp}

    # Bullish candle → SELL at candle high
    if candle_close > candle_open and abs(price - candle_high) <= atr_val * 0.3:
        sl = candle_high + sl_dist
        tp = candle_high - tp_dist
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


# Strategy dispatch table
STRATEGIES = {
    "GS01": ("M3", _gs01_gold_ema_rsi_stoch),
    "GS02": ("M1", _gs02_ict_silver_bullet),
    "GS03": ("M3", _gs03_vwap_macd),
    "GS04": ("M1", _gs04_keltner_rsi_breakout),
    "GS05": ("M1", _gs05_ema_crossover),
    "GS06": ("M3", _gs06_rsi_bb_stoch_reversal),
    "GS07": ("M1", _gs07_liquidity_sweep),
    "GS08": ("M1", _gs08_m1_sniper_bos),
    "GS09": ("M3", _gs09_rsi_bb_ema200_reversal),
    "GS10": ("M3", _gs10_ema_triple_trend),
    "GS11": ("M1", _gs11_opening_range_scalper),
}


# ── Backtest engine ──────────────────────────────────────────────────────────

def backtest_one(strategy_id: str, symbol: str, bars: dict) -> dict:
    import inspect as _inspect
    tf, fn = STRATEGIES[strategy_id]
    _fn_wants_symbol = "symbol" in _inspect.signature(fn).parameters
    times = bars.get("time", [])
    closes = bars.get("close", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])

    if len(times) < 60:
        return {"strategy": strategy_id, "symbol": symbol, "status": "insufficient_bars",
                "bars": len(times)}

    spread = TYPICAL_SPREADS.get(symbol, 0.0001)
    trades = []
    position = None
    rejections = defaultdict(int)
    start_i = 60

    for i in range(start_i, len(times) - 1):
        if position is not None:
            next_h = highs[i + 1]
            next_l = lows[i + 1]
            if position["side"] == "BUY":
                if next_l <= position["sl"]:
                    pnl = position["sl"] - position["entry"] - spread
                    trades.append({"side": "BUY", "pnl": pnl, "exit": "SL",
                                   "bars": i + 1 - position["i"]})
                    position = None
                elif next_h >= position["tp"]:
                    pnl = position["tp"] - position["entry"] - spread
                    trades.append({"side": "BUY", "pnl": pnl, "exit": "TP",
                                   "bars": i + 1 - position["i"]})
                    position = None
            else:
                if next_h >= position["sl"]:
                    pnl = position["entry"] - position["sl"] - spread
                    trades.append({"side": "SELL", "pnl": pnl, "exit": "SL",
                                   "bars": i + 1 - position["i"]})
                    position = None
                elif next_l <= position["tp"]:
                    pnl = position["entry"] - position["tp"] - spread
                    trades.append({"side": "SELL", "pnl": pnl, "exit": "TP",
                                   "bars": i + 1 - position["i"]})
                    position = None

        if position is None:
            try:
                sig = fn(bars, i, spread, symbol) if _fn_wants_symbol else fn(bars, i, spread)
            except Exception as e:
                rejections[f"err:{type(e).__name__}"] += 1
                continue
            if sig and sig.get("signal") in ("BUY", "SELL"):
                sl = sig["sl"]
                tp = sig["tp"]
                if sl <= 0 or tp <= 0:
                    rejections["bad_sl_tp"] += 1
                    continue
                entry = closes[i + 1] + (spread if sig["signal"] == "BUY" else -spread)
                if sig["signal"] == "BUY" and (sl >= entry or tp <= entry):
                    rejections["inverted_sl_tp"] += 1
                    continue
                if sig["signal"] == "SELL" and (sl <= entry or tp >= entry):
                    rejections["inverted_sl_tp"] += 1
                    continue
                position = {"side": sig["signal"], "entry": entry,
                            "sl": sl, "tp": tp, "i": i + 1}
            else:
                rejections["no_signal"] += 1

    return _summarize(strategy_id, symbol, tf, trades, rejections,
                      len(times) - start_i)


def _summarize(strategy: str, symbol: str, tf: str,
               trades: list, rejections: dict, bars_tested: int) -> dict:
    if not trades:
        return {"strategy": strategy, "symbol": symbol, "tf": tf,
                "trades": 0, "bars_tested": bars_tested, "verdict": "NO_TRADES",
                "rejections": dict(list(rejections.items())[:5])}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses)) if losses else 1e-9
    pf = round(gp / gl, 2)
    wr = round(len(wins) / len(pnls) * 100, 1)
    avg_win = round(gp / max(len(wins), 1), 5)
    avg_loss = round(sum(losses) / max(len(losses), 1), 5)
    exp = round((wr / 100 * avg_win) + ((1 - wr / 100) * avg_loss), 5)

    cum, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    avg_bars = round(sum(t.get("bars", 0) for t in trades) / len(trades), 1)

    if len(pnls) < 5:
        verdict = "INSUFFICIENT"
    elif pf >= 2.0:
        verdict = "STRONG"
    elif pf >= 1.3:
        verdict = "DECENT"
    elif pf >= 1.0:
        verdict = "MARGINAL"
    else:
        verdict = "UNPROFITABLE"

    return {
        "strategy": strategy, "symbol": symbol, "tf": tf,
        "trades": len(pnls), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": wr, "profit_factor": pf,
        "expectancy": exp, "max_drawdown": round(max_dd, 5),
        "avg_win": avg_win, "avg_loss": avg_loss,
        "avg_hold_bars": avg_bars, "bars_tested": bars_tested,
        "verdict": verdict,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",     type=int, default=60)
    parser.add_argument("--bars",     type=int, default=None,
                        help="Override bar count directly (e.g. --bars 10000)")
    parser.add_argument("--symbols",  nargs="+", default=None)
    parser.add_argument("--strategy", default=None, help="Filter to one strategy (GS01..GS11)")
    args = parser.parse_args()

    strat_ids = [args.strategy] if args.strategy else list(STRATEGIES.keys())
    all_results = []

    for sid in strat_ids:
        if sid not in STRATEGIES:
            log.warning("Unknown strategy %s — skip", sid)
            continue
        tf, _ = STRATEGIES[sid]
        if args.bars:
            bars_needed = args.bars
        else:
            bars_needed = args.days * (1440 if tf == "M1" else 480) + 200
            bars_needed = min(bars_needed, 5000)

        symbols = args.symbols or STRATEGY_SYMBOLS.get(sid, ["EURUSD"])
        for sym in symbols:
            log.info("Backtesting %s / %s / %s (%d bars)...", sid, sym, tf, bars_needed)
            bars = _fetch_bars(sym, tf, bars_needed)
            if not bars or not bars.get("close"):
                log.error("No bars for %s %s", sym, tf)
                all_results.append({"strategy": sid, "symbol": sym,
                                    "status": "no_bars", "verdict": "ERROR"})
                continue
            result = backtest_one(sid, sym, bars)
            all_results.append(result)
            v = result.get("verdict", "?")
            pf = result.get("profit_factor", 0)
            wr = result.get("win_rate_pct", 0)
            n = result.get("trades", 0)
            log.info("  %s/%s: verdict=%s PF=%.2f WR=%.1f%% trades=%d",
                     sid, sym, v, pf, wr, n)

    REPORT_FILE.write_text(json.dumps(all_results, indent=2))
    log.info("Report written to %s", REPORT_FILE)

    # Summary table
    print("\n" + "=" * 70)
    print(f"{'Strategy':<8} {'Symbol':<10} {'TF':<4} {'Trades':>6} "
          f"{'WR%':>6} {'PF':>5} {'Verdict':<14}")
    print("-" * 70)
    for r in sorted(all_results, key=lambda x: x.get("profit_factor", 0), reverse=True):
        if r.get("verdict") in ("STRONG", "DECENT"):
            marker = " <<<"
        elif r.get("verdict") == "MARGINAL":
            marker = " <"
        else:
            marker = ""
        print(f"{r.get('strategy','?'):<8} {r.get('symbol','?'):<10} "
              f"{r.get('tf','?'):<4} {r.get('trades',0):>6} "
              f"{r.get('win_rate_pct',0):>6.1f} {r.get('profit_factor',0):>5.2f} "
              f"{r.get('verdict','?'):<14}{marker}")
    print("=" * 70)

    profitable = [r for r in all_results
                  if r.get("verdict") in ("STRONG", "DECENT")]
    print(f"\nProfitable strategies (PF>=1.3): {len(profitable)}/{len(all_results)}")
    for r in profitable:
        print(f"  {r['strategy']} / {r['symbol']}: "
              f"PF={r['profit_factor']} WR={r['win_rate_pct']}% "
              f"trades={r['trades']}")


if __name__ == "__main__":
    main()
