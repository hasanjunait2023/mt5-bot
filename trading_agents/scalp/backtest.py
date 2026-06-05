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
    detect_liquidity_sweep, find_fvg_zones, find_inverse_fvg,
    detect_trendline_break, session_volume_profile,
)
from trading_agents.strength.strength import (
    PAIRS28, MAJORS, currency_strength, MIN_DIFF,
)
from trading_agents.strength.entry import (
    adr_from_m3, atr_expansion_ok, m3_signal, ADR_USED_MAX,
)
from trading_agents.iconic.correlation import split_pair

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
# Real-cost spreads for the 28 FX majors/crosses (GS13 strength-scalp). JPY pairs
# quote to 3 digits → ~0.015 (1.5 pip); the rest ~0.0002 (2 pip). Conservative so
# the 2yr backtest reflects honest demo costs.
for _p in PAIRS28:
    if _p in TYPICAL_SPREADS:
        continue
    TYPICAL_SPREADS[_p] = 0.015 if _p.endswith("JPY") else 0.0002

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
    "GS12": ["XAUUSD"],
    "GSVP": ["BTCUSD", "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD"],
    "GS13": list(PAIRS28),
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


# GS12 tunable params — mutated in-place by optimize_gs12.py before each run.
GS12_PARAMS: dict[str, Any] = {
    "sweep_lookback": 5,        # fractal lookback for the swept swing
    "min_depth_atr": 0.15,      # wick must pierce the level by >= this many ATR
    "conf_window": 8,           # sweep must be within last N bars (recency)
    "trend_swing_lookback": 3,  # swing lookback for trendline anchors
    "fit_swings": 2,            # how many swings define the trendline
    "rr": 2.0,                  # reward:risk
    "sl_buffer_atr": 0.5,       # SL beyond the sweep wick by this many ATR
    "use_ifvg_only": True,      # True: require a true inverse-FVG in direction
    "session_filter": False,    # London/NY kill-zones only
    "htf_bias": False,          # require EMA(htf_ema) trend alignment
    "htf_ema": 200,             # length of the trend-bias EMA (HTF proxy)
    "min_displacement_atr": 0.0,  # require break bar body >= this*ATR (ICT displacement)
    "atr_period": 14,
}


def _gs12_ict_simple(bars: dict, t_i: int,
                     spread: float, symbol: str = "XAUUSD") -> dict | None:
    """GS12: "Stupid-Simple" ICT triad — Liquidity Sweep -> Inverse FVG -> Trendline Break.

    From the supplied strategy document. Three confirmations in sequence:
      1) Liquidity sweep: stop-hunt beyond a prior swing low (bull) / high (bear),
         price closing back through the level (depth-filtered to skip tick noise).
      2) Inverse FVG (or fresh FVG) in the reversal direction — the sentiment shift.
      3) Trendline / market-structure break confirming the prior trend ended.
    Direction-matched: all three must agree. SL beyond the sweep wick, TP at RR.
    Tunable via GS12_PARAMS.
    """
    P = GS12_PARAMS
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    o = bars.get("open", [])
    times = bars.get("time", [])
    if t_i < 60:
        return None
    cl, hl, ll, ol = c[:t_i + 1], h[:t_i + 1], l[:t_i + 1], o[:t_i + 1]

    if P["session_filter"] and not _session_bd(times[t_i])["any_primary"]:
        return None

    atr_val = atr(hl, ll, cl, P["atr_period"])
    if atr_val <= 0:
        return None
    price = cl[-1]

    # ICT displacement: the confirming bar must be a strong-bodied candle.
    min_disp = float(P.get("min_displacement_atr", 0.0))
    if min_disp > 0 and abs(cl[-1] - ol[-1]) < min_disp * atr_val:
        return None
    htf_len = int(P.get("htf_ema", 200))

    recent = min(int(P["conf_window"]), 8)
    sweep = detect_liquidity_sweep(hl, ll, cl, lookback=int(P["sweep_lookback"]),
                                   min_depth_atr=float(P["min_depth_atr"]),
                                   atr_val=atr_val, recent=recent)
    if not sweep:
        return None

    tb = detect_trendline_break(hl, ll, cl,
                                swing_lookback=int(P["trend_swing_lookback"]),
                                fit_swings=int(P["fit_swings"]))
    ifvgs = find_inverse_fvg(ol, hl, ll, cl, lookback=16,
                             active_within=int(P["conf_window"]))
    fvgs = find_fvg_zones(ol, hl, ll, cl, lookback=12) if not P["use_ifvg_only"] else []

    # ── Bullish setup: swept sell-side liquidity, up-break, bull IFVG/FVG ──
    if sweep["side"] == "BULL" and tb == 1:
        has_dir = any(z["flipped_side"] == "BULL" for z in ifvgs) \
            or any(z["type"] == "BULL" for z in fvgs)
        if has_dir and (not P["htf_bias"] or price > ema(cl, htf_len)):
            wick_low = min(ll[-recent:])
            sl = wick_low - P["sl_buffer_atr"] * atr_val
            risk = price - sl
            if risk > 0:
                tp = price + P["rr"] * risk
                return {"signal": "BUY", "sl": sl, "tp": tp}

    # ── Bearish setup: swept buy-side liquidity, down-break, bear IFVG/FVG ──
    if sweep["side"] == "BEAR" and tb == -1:
        has_dir = any(z["flipped_side"] == "BEAR" for z in ifvgs) \
            or any(z["type"] == "BEAR" for z in fvgs)
        if has_dir and (not P["htf_bias"] or price < ema(cl, htf_len)):
            wick_high = max(hl[-recent:])
            sl = wick_high + P["sl_buffer_atr"] * atr_val
            risk = sl - price
            if risk > 0:
                tp = price - P["rr"] * risk
                return {"signal": "SELL", "sl": sl, "tp": tp}

    return None


# Strategy dispatch table
# ── GS-VP: Adaptive Volume-Profile (regime-aware) ────────────────────────────
#
# VP levels from the prior completed Daily session (built from the M15 series by
# session_volume_profile). Each bar: classify regime, run the matching playbook,
# then apply a TIERED VOLUME-TRUST gate (MT5 spot/metals carry only tick volume —
# real traded volume exists only on crypto, so FX must lean on price-action):
#   - primary    (BTCUSD): real volume — a VP level + M15 rejection can trigger.
#   - confirm    (XAU/XAG): tick-vol proxy — also require momentum or an aligned sweep.
#   - confluence (EUR/GBP): tick-vol only — VP only locates the level; an aligned
#                           liquidity sweep MUST trigger.
# Playbooks: A = VA-reversion (balance, TP=POC magnet), B = breakout-retest
# (imbalance, TP=2R), C = naked-POC magnet folded into A's POC target.

_VP_TIER = {
    "BTCUSD": "primary",
    "XAUUSD": "confirm", "XAGUSD": "confirm",
    "EURUSD": "confluence", "GBPUSD": "confluence",
}
_VP_BINS = {"BTCUSD": 50, "XAUUSD": 50, "XAGUSD": 40, "EURUSD": 50, "GBPUSD": 50}
_VP_SL_ATR = {"BTCUSD": 1.0, "XAUUSD": 0.8, "XAGUSD": 0.9, "EURUSD": 0.7, "GBPUSD": 0.7}
_VP_BAL_FRAC = 0.75   # VA width <= this * prior-day range  → "balanced"
_VP_NEAR_ATR = 0.20   # touch tolerance around a VP level, in ATR
_VP_MIN_RR = 1.0      # skip trades whose reward/risk is below this


def _gsvp_adaptive(bars: dict, t_i: int,
                   spread: float, symbol: str = "BTCUSD") -> dict | None:
    """GS-VP: regime-adaptive volume-profile strategy (M15 entries)."""
    c = bars.get("close", [])
    h = bars.get("high", [])
    l = bars.get("low", [])
    o = bars.get("open", [])
    v = bars.get("volume", [])
    times = bars.get("time", [])
    if t_i < 60 or not v:
        return None
    # Trailing window keeps every per-bar computation O(W), so a 2-year M15
    # walk-forward stays O(n) instead of O(n²). ~300 M15 bars ≈ 3 sessions,
    # enough for the prior-day profile + ATR/EMA context.
    n = t_i + 1
    s = max(0, n - 300)
    cl, hl, ll = c[s:n], h[s:n], l[s:n]
    tw, vw = times[s:n], v[s:n]
    has_open = bool(o)

    tier = _VP_TIER.get(symbol, "confluence")
    # Session filter: FX/metals trade only in London/NY kill-zones; crypto 24/7.
    if symbol != "BTCUSD" and not _session_bd(times[t_i])["any_primary"]:
        return None

    atr15 = atr(hl, ll, cl, 14)
    if atr15 <= 0:
        return None

    vp = session_volume_profile(tw, hl, ll, vw, as_of_idx=len(tw) - 1,
                                bins=_VP_BINS.get(symbol, 50))
    if not vp or vp["total_vol"] <= 0:
        return None
    poc, vah, val = vp["poc"], vp["vah"], vp["val"]
    rng = vp["day_high"] - vp["day_low"]
    if rng <= 0 or vah <= val:
        return None

    price = cl[-1]
    prev = cl[-2]
    popen = o[t_i] if has_open else prev
    # HTF trend bias (M15 EMA50 vs EMA200). Breakouts need a GENUINE trend
    # (gap >= 0.3 ATR), else the break is chop and the retest fails.
    ema_fast, ema_slow = ema(cl, 50), ema(cl, 200)
    trend_gap = ema_fast - ema_slow
    up_str = trend_gap >= 0.3 * atr15
    dn_str = trend_gap <= -0.3 * atr15
    # Candle anatomy → wick-rejection confirmation (a real rejection, not a touch).
    bar_rng = max(hl[-1] - ll[-1], 1e-12)
    lower_wick = min(price, popen) - ll[-1]
    upper_wick = hl[-1] - max(price, popen)
    bull_rej = price > popen and lower_wick >= 0.4 * bar_rng   # rejected the lows
    bear_rej = price < popen and upper_wick >= 0.4 * bar_rng   # rejected the highs
    flat = abs(ema_fast - ema_slow) <= 0.5 * atr15             # no strong trend
    tol = _VP_NEAR_ATR * atr15
    sl_atr = _VP_SL_ATR.get(symbol, 0.8)

    sweep = detect_liquidity_sweep(hl, ll, cl, lookback=5, min_depth_atr=0.15,
                                   atr_val=atr15, recent=3)

    def _confirm(side: str) -> bool:
        aligned = bool(sweep and (
            (side == "BUY" and sweep["side"] == "BULL") or
            (side == "SELL" and sweep["side"] == "BEAR")))
        if tier == "primary":
            return True
        if tier == "confirm":
            strong = (hl[-1] - ll[-1]) >= 0.6 * atr15
            return strong or aligned
        return aligned   # confluence-only (FX): sweep must trigger

    def _mk(side: str, sl: float, tp: float, pb: str = "") -> dict | None:
        risk, rew = abs(price - sl), abs(tp - price)
        if risk <= 0 or rew / risk < _VP_MIN_RR:
            return None
        return {"signal": side, "sl": sl, "tp": tp, "_pb": pb}

    # Regime: close-and-hold (2 bars) outside prior value area = imbalance/trend.
    held_above = price > vah and prev > vah
    held_below = price < val and prev < val

    # Playbook B — breakout-retest (imbalance): genuine trend + rejection at the
    # retest of the broken edge, not a runaway-extended chase (<= 1.2 ATR away).
    # "Not runaway-extended" retest helps high-vol trenders (crypto/metals) but
    # starves the already-rare FX setups, so apply it only to non-FX tiers.
    near_break = tier == "confluence"
    if held_above:
        ext_ok = near_break or price <= vah + 1.2 * atr15
        if up_str and ll[-1] <= vah + tol and ext_ok and bull_rej and _confirm("BUY"):
            sl = vah - sl_atr * atr15
            return _mk("BUY", sl, price + 2.0 * (price - sl), "B")
        return None
    if held_below:
        ext_ok = near_break or price >= val - 1.2 * atr15
        if dn_str and hl[-1] >= val - tol and ext_ok and bear_rej and _confirm("SELL"):
            sl = val + sl_atr * atr15
            return _mk("SELL", sl, price - 2.0 * (sl - price), "B")
        return None

    # Playbook A — VA-reversion: only in a FLAT, balanced market, fade edge to POC.
    if flat and (vah - val) <= _VP_BAL_FRAC * rng and val <= price <= vah:
        if ll[-1] <= val + tol and price < poc and bull_rej and _confirm("BUY"):
            return _mk("BUY", val - sl_atr * atr15, poc, "A")
        if hl[-1] >= vah - tol and price > poc and bear_rej and _confirm("SELL"):
            return _mk("SELL", vah + sl_atr * atr15, poc, "A")
    return None


# ── GS13: Currency-Strength M3 scalper ───────────────────────────────────────
# The harness is single-symbol, but strength needs all 28 pairs. We precompute a
# causal strength history once (28 H1 series → trailing-session score at every H1
# close), then each per-bar call does an asof lookup by timestamp (no lookahead).

import bisect as _bisect

_GS13_H1_LIMIT = int(os.getenv("GS13_H1_LIMIT", "20000"))  # ~830 days of H1
_GS13_SESSION_WIN = 6                                      # trailing H1 bars ≈ session
_STRENGTH_TS: dict[str, list] = {}
_STRENGTH_VAL: dict[str, list] = {}
_STRENGTH_BUILT = False


def _build_strength_history(limit_h1: int = _GS13_H1_LIMIT) -> None:
    """Fetch 28 H1 series once; compute trailing-session strength at each H1 close."""
    global _STRENGTH_BUILT, _STRENGTH_TS, _STRENGTH_VAL
    if _STRENGTH_BUILT:
        return
    log.info("GS13: building strength history (28 pairs, %d H1 bars)...", limit_h1)
    series: dict[str, dict] = {}
    for sym in PAIRS28:
        b = _fetch_bars(sym, "H1", limit_h1)
        if b and b.get("close") and len(b["close"]) >= 2:
            series[sym] = b
    if not series:
        log.error("GS13: no H1 series fetched — strength history empty")
        _STRENGTH_BUILT = True
        return
    sym_times = {s: series[s]["time"] for s in series}
    spine = sorted(series[max(series, key=lambda s: len(series[s]["time"]))]["time"])
    hx_ts = {c: [] for c in MAJORS}
    hx_val = {c: [] for c in MAJORS}
    for t in spine:
        pb = {}
        for s, ts in sym_times.items():
            j = _bisect.bisect_right(ts, t)
            if j < 2:
                continue
            i0 = max(0, j - _GS13_SESSION_WIN)
            b = series[s]
            pb[s] = {"high": b["high"][i0:j], "low": b["low"][i0:j],
                     "close": b["close"][i0:j]}
        score = currency_strength(pb)
        for c, v in score.items():
            hx_ts[c].append(t)
            hx_val[c].append(v)
    _STRENGTH_TS, _STRENGTH_VAL = hx_ts, hx_val
    _STRENGTH_BUILT = True
    log.info("GS13: strength history built (%d H1 points)", len(spine))


def _strength_at(t: int) -> dict:
    """Asof lookup: latest computed strength with H1-close time <= t (step-hold)."""
    out = {}
    for c in MAJORS:
        ts = _STRENGTH_TS.get(c, [])
        j = _bisect.bisect_right(ts, t) - 1
        out[c] = _STRENGTH_VAL[c][j] if j >= 0 else 0
    return out


def _gs13_m3_strength_scalp(bars: dict, t_i: int, spread: float,
                            symbol: str = "EURUSD") -> dict | None:
    """M3 EMA200/9-15 + RSI scalp, biased by -7..+7 currency strength.

    Bias from strength[base]-strength[quote] (skip |diff|<3); momentum gate via
    ADR-used + ATR expansion; entry/SL/TP identical to the live agent (shared
    trading_agents.strength.entry).
    """
    if not _STRENGTH_BUILT:
        _build_strength_history()
    times = bars.get("time", [])
    if t_i < 200 or t_i >= len(times):
        return None
    score = _strength_at(int(times[t_i]))
    base, quote = split_pair(symbol)
    if base not in score or quote not in score:
        return None
    diff = score[base] - score[quote]
    if abs(diff) < MIN_DIFF:
        return None
    bias = "BUY" if diff > 0 else "SELL"

    c = bars["close"][:t_i + 1]
    h = bars["high"][:t_i + 1]
    l = bars["low"][:t_i + 1]
    adr_val, used = adr_from_m3(times[:t_i + 1], h, l, 14)
    if used > ADR_USED_MAX:
        return None
    if not atr_expansion_ok(h, l, c):
        return None
    return m3_signal(h, l, c, bias)


STRATEGIES = {
    "GS13": ("M3", _gs13_m3_strength_scalp),
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
    "GS12": ("M3", _gs12_ict_simple),
    "GSVP": ("M15", _gsvp_adaptive),
}

# Register factory-generated strategies (GS50+). AST-validated + isolated; a bad
# generated module is logged and skipped, never fatal to the hand-written core.
try:
    from trading_agents.factory import generated_loader as _gen_loader
    _gen_loader.register_into(STRATEGIES, STRATEGY_SYMBOLS)
except Exception as _gen_e:  # noqa: BLE001
    log.warning("generated-strategy loader unavailable: %s", _gen_e)


def refresh_generated() -> list[str]:
    """Register factory-generated strategies written AFTER this module was imported.

    Long-lived processes (factory runner, paper soak) import backtest once at start,
    so a strategy the factory codegens later is absent from STRATEGIES until this is
    called. Only NEW files are exec'd — the id is derived from the filename
    (gs50_slug.py → GS50) so already-registered modules are skipped without re-exec.
    Returns the ids newly registered.
    """
    new: list[str] = []
    try:
        from trading_agents.factory import generated_loader as _gl
    except Exception:
        return new
    if not _gl.GENERATED_DIR.exists():
        return new
    for path in sorted(_gl.GENERATED_DIR.glob("gs*_*.py")):
        sid_guess = path.stem.split("_")[0].upper()  # gs50_foo -> GS50
        if sid_guess in STRATEGIES:
            continue
        try:
            mod = _gl.load_module(path)
            sid, tf, syms, fn = _gl._extract(mod)
            if sid in STRATEGIES:
                continue
            STRATEGIES[sid] = (tf, fn)
            STRATEGY_SYMBOLS[sid] = syms
            new.append(sid)
            log.info("[backtest] refreshed generated strategy %s from %s", sid, path.name)
        except Exception as e:  # noqa: BLE001 — isolation is the point
            log.error("[backtest] refresh skip %s: %s", path.name, e)
    return new


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
