"""Multi-Timeframe analytics — fetches D1/H4/H1/M15/M3 bars and computes
per-timeframe trend, structure, SMC, and intraday-specific signals (VWAP,
session ranges, NR7).

Used by M3 scalping strategies (S17-S21) that need HTF bias + LTF entry.
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("jtcc.analytics.mtf")
BD_TZ = ZoneInfo("Asia/Dhaka")

# Cache TTLs per timeframe (seconds)
TTL = {
    "D1": 3600,   # 1h
    "H4": 1800,   # 30min
    "H1": 900,    # 15min
    "M15": 300,   # 5min
    "M5": 120,    # 2min
    "M3": 60,     # 1min
    "M1": 30,
}

# Default MTF stack for scalping strategies
DEFAULT_MTF_STACK = ["D1", "H4", "H1", "M15", "M3"]

_cache: dict[str, dict] = {}


def _fetch_bars(symbol: str, timeframe: str, limit: int = 200) -> dict | None:
    """Fetch bars for one TF from MT5 bridge. TTL-cached per (sym, tf)."""
    key = f"{symbol}_{timeframe}"
    cached = _cache.get(key)
    ttl = TTL.get(timeframe, 60)
    if cached and (time.time() - cached["fetched_at"]) < ttl:
        return cached["data"]
    bridge_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{bridge_url}/bars/{symbol}",
                         params={"timeframe": timeframe, "limit": limit},
                         timeout=8)
        r.raise_for_status()
        data = r.json()
        if data and data.get("close"):
            _cache[key] = {"data": data, "fetched_at": time.time()}
            return data
    except Exception as e:
        log.debug("MTF fetch failed %s %s: %s", symbol, timeframe, e)
    return None


def fetch_mtf_bars(symbol: str, timeframes: list[str] | None = None,
                   limit: int = 200) -> dict[str, dict]:
    """Fetch bars across multiple timeframes. Returns {tf: ohlcv_dict}."""
    tfs = timeframes or DEFAULT_MTF_STACK
    result = {}
    for tf in tfs:
        bars = _fetch_bars(symbol, tf, limit=limit)
        if bars:
            result[tf] = bars
    return result


# ────────────────────────────────────────────────────────────────────────────
# Per-TF lightweight indicators (reuse logic from L1 agents but per-bar set)
# ────────────────────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def _atr(highs: list[float], lows: list[float], closes: list[float],
         period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs[-period:]) / period


def _swing(highs: list[float], lows: list[float], length: int = 3) -> tuple[float | None, float | None]:
    """Last swing high + low using simple fractal."""
    if len(highs) < length * 2 + 1:
        return None, None
    sh, sl = None, None
    for i in range(len(highs) - length - 1, length - 1, -1):
        if sh is None and highs[i] == max(highs[i - length: i + length + 1]):
            sh = highs[i]
        if sl is None and lows[i] == min(lows[i - length: i + length + 1]):
            sl = lows[i]
        if sh is not None and sl is not None:
            break
    return sh, sl


def _detect_fvg(highs: list[float], lows: list[float], n_check: int = 30) -> tuple[int, int]:
    """Count bull/bear FVGs in last n_check bars. Returns (bull_count, bear_count)."""
    bull, bear = 0, 0
    for i in range(max(1, len(highs) - n_check), len(highs) - 1):
        if lows[i + 1] > highs[i - 1]:
            bull += 1
        if highs[i + 1] < lows[i - 1]:
            bear += 1
    return bull, bear


def _detect_sweep(highs: list[float], lows: list[float], closes: list[float],
                  sh: float | None, sl: float | None) -> tuple[bool, str | None]:
    """Detect liquidity sweep in last 2 bars."""
    if len(closes) < 2:
        return False, None
    c, h, l = closes[-1], highs[-1], lows[-1]
    if sl is not None and l < sl and c > sl:
        return True, "SSL_SWEEP"
    if sh is not None and h > sh and c < sh:
        return True, "BSL_SWEEP"
    return False, None


def _detect_mss(closes: list[float], sh: float | None, sl: float | None,
                atr: float) -> bool:
    """Market Structure Shift: close breaks last swing in opposite direction + displacement."""
    if len(closes) < 2 or atr <= 0:
        return False
    body = abs(closes[-1] - closes[-2])
    if body < 1.5 * atr:
        return False
    if sh is not None and closes[-1] > sh:
        return True
    if sl is not None and closes[-1] < sl:
        return True
    return False


def compute_per_tf_context(bars: dict) -> dict[str, Any]:
    """Compute trend, structure, ATR, SMC for ONE timeframe's bars."""
    closes = bars.get("close", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    if len(closes) < 30:
        return {"valid": False, "bars": len(closes)}

    ema20 = _ema(closes[-50:], 20)
    ema50 = _ema(closes[-100:], 50) if len(closes) >= 50 else ema20
    ema200 = _ema(closes[-200:], 200) if len(closes) >= 200 else ema50
    atr = _atr(highs, lows, closes)
    sh, sl = _swing(highs, lows)

    # Trend classification
    price = closes[-1]
    if price > ema50 > ema200:
        trend = "BULLISH"
    elif price < ema50 < ema200:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    sweep_detected, sweep_type = _detect_sweep(highs, lows, closes, sh, sl)
    mss = _detect_mss(closes, sh, sl, atr)
    bull_fvg, bear_fvg = _detect_fvg(highs, lows)

    # Premium/discount based on recent range
    recent_high = max(highs[-50:])
    recent_low = min(lows[-50:])
    rng = recent_high - recent_low
    mid = (recent_high + recent_low) / 2
    in_discount = price < (recent_low + rng * 0.4) if rng > 0 else False
    in_premium = price > (recent_high - rng * 0.4) if rng > 0 else False

    # OTE zone (62-79% retrace of last swing)
    in_ote = False
    if sh and sl and sh > sl:
        ote_top = sh - (sh - sl) * 0.62
        ote_bot = sh - (sh - sl) * 0.79
        in_ote = ote_bot <= price <= ote_top

    return {
        "valid": True,
        "bars": len(closes),
        "trend": trend,
        "price": round(price, 5),
        "ema20": round(ema20, 5),
        "ema50": round(ema50, 5),
        "ema200": round(ema200, 5),
        "atr": round(atr, 5),
        "last_swing_high": round(sh, 5) if sh else None,
        "last_swing_low": round(sl, 5) if sl else None,
        "sweep_detected": sweep_detected,
        "sweep_type": sweep_type,
        "mss": mss,
        "bull_fvg_count": bull_fvg,
        "bear_fvg_count": bear_fvg,
        "in_discount": in_discount,
        "in_premium": in_premium,
        "in_ote": in_ote,
        "bos": (sh is not None and price > sh) or (sl is not None and price < sl),
    }


# ────────────────────────────────────────────────────────────────────────────
# Intraday-specific signals (VWAP, session range, NR7)
# ────────────────────────────────────────────────────────────────────────────

def compute_session_range(bars: dict, start_hour_bd: int, end_hour_bd: int) -> dict:
    """Find high/low of bars within the BD-time window for the CURRENT day.

    Use case: Asian session range (07:00-13:00 BD) for London breakout strategy.
    Returns {high, low, mid, built} where built=True if window has closed.
    """
    times = bars.get("time", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    if not times or not highs:
        return {"high": 0.0, "low": 0.0, "mid": 0.0, "built": False, "bars_in_range": 0}

    now_bd = datetime.now(tz=BD_TZ)
    today_date = now_bd.date()
    range_highs, range_lows = [], []
    for i, t_unix in enumerate(times):
        try:
            bar_bd = datetime.fromtimestamp(t_unix, tz=BD_TZ)
        except Exception:
            continue
        if bar_bd.date() != today_date:
            continue
        if start_hour_bd <= bar_bd.hour < end_hour_bd:
            range_highs.append(highs[i])
            range_lows.append(lows[i])
    if not range_highs:
        return {"high": 0.0, "low": 0.0, "mid": 0.0, "built": False, "bars_in_range": 0}
    h = max(range_highs)
    l = min(range_lows)
    built = now_bd.hour >= end_hour_bd
    return {
        "high": round(h, 5),
        "low": round(l, 5),
        "mid": round((h + l) / 2, 5),
        "built": built,
        "bars_in_range": len(range_highs),
        "window": f"{start_hour_bd:02d}:00-{end_hour_bd:02d}:00 BD",
    }


def compute_orb(bars: dict, session_start_hour_bd: int, orb_minutes: int = 30) -> dict:
    """Opening Range Breakout: high/low of first N minutes of session."""
    times = bars.get("time", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    if not times:
        return {"high": 0.0, "low": 0.0, "built": False}

    now_bd = datetime.now(tz=BD_TZ)
    today_date = now_bd.date()
    end_min = orb_minutes
    range_h, range_l = [], []
    for i, t_unix in enumerate(times):
        try:
            bar_bd = datetime.fromtimestamp(t_unix, tz=BD_TZ)
        except Exception:
            continue
        if bar_bd.date() != today_date or bar_bd.hour < session_start_hour_bd:
            continue
        minute_offset = (bar_bd.hour - session_start_hour_bd) * 60 + bar_bd.minute
        if minute_offset < end_min:
            range_h.append(highs[i])
            range_l.append(lows[i])
    if not range_h:
        return {"high": 0.0, "low": 0.0, "built": False, "minutes_collected": 0}
    built = now_bd.hour > session_start_hour_bd or (
        now_bd.hour == session_start_hour_bd and now_bd.minute >= orb_minutes
    )
    return {
        "high": round(max(range_h), 5),
        "low": round(min(range_l), 5),
        "built": built,
        "minutes_collected": len(range_h),
        "window": f"{session_start_hour_bd:02d}:00 BD + {orb_minutes}min",
    }


def compute_vwap_bands(bars: dict, sigma_mult: float = 2.0) -> dict:
    """Intraday VWAP + sigma bands. Uses today's bars only (resets daily)."""
    times = bars.get("time", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    closes = bars.get("close", [])
    volumes = bars.get("volume", [])
    if not closes or not volumes:
        return {"vwap": 0.0, "upper": 0.0, "lower": 0.0, "zscore": 0.0,
                "above_upper": False, "below_lower": False, "bars": 0}

    now_bd = datetime.now(tz=BD_TZ)
    today_date = now_bd.date()
    today_idx = []
    for i, t in enumerate(times):
        try:
            if datetime.fromtimestamp(t, tz=BD_TZ).date() == today_date:
                today_idx.append(i)
        except Exception:
            continue
    if not today_idx:
        return {"vwap": 0.0, "upper": 0.0, "lower": 0.0, "zscore": 0.0,
                "above_upper": False, "below_lower": False, "bars": 0}

    cum_pv, cum_v = 0.0, 0.0
    tp_list = []
    for i in today_idx:
        tp = (highs[i] + lows[i] + closes[i]) / 3
        v = max(volumes[i], 1)
        cum_pv += tp * v
        cum_v += v
        tp_list.append(tp)
    vwap = cum_pv / cum_v if cum_v > 0 else closes[today_idx[-1]]

    # Deviation from VWAP
    deviations = [(tp - vwap) for tp in tp_list]
    if len(deviations) < 2:
        return {"vwap": round(vwap, 5), "upper": round(vwap, 5),
                "lower": round(vwap, 5), "zscore": 0.0,
                "above_upper": False, "below_lower": False, "bars": len(today_idx)}
    var = sum(d * d for d in deviations) / len(deviations)
    sigma = math.sqrt(var)
    upper = vwap + sigma_mult * sigma
    lower = vwap - sigma_mult * sigma
    current = closes[today_idx[-1]]
    z = (current - vwap) / sigma if sigma > 0 else 0.0
    return {
        "vwap": round(vwap, 5),
        "upper": round(upper, 5),
        "lower": round(lower, 5),
        "zscore": round(z, 2),
        "above_upper": current > upper,
        "below_lower": current < lower,
        "bars": len(today_idx),
        "sigma": round(sigma, 5),
    }


def compute_nr7(daily_bars: dict) -> dict:
    """Narrow Range 7 (Crabel): true if today's range < min(last 7 days' range)."""
    highs = daily_bars.get("high", [])
    lows = daily_bars.get("low", [])
    if len(highs) < 8:
        return {"is_nr7": False, "ranges": [], "today_range": 0.0}
    ranges = [highs[i] - lows[i] for i in range(-8, 0)]
    today_range = ranges[-1]
    prior_7_ranges = ranges[:-1]
    is_nr7 = today_range < min(prior_7_ranges)
    return {
        "is_nr7": is_nr7,
        "today_range": round(today_range, 5),
        "min_prior_7": round(min(prior_7_ranges), 5),
        "max_prior_7": round(max(prior_7_ranges), 5),
    }


# ────────────────────────────────────────────────────────────────────────────
# MTF Hub — orchestrates everything for one symbol
# ────────────────────────────────────────────────────────────────────────────

class MTFHub:
    """Per-symbol multi-timeframe analytics hub."""

    def for_symbol(self, symbol: str) -> dict[str, Any]:
        """Returns full MTF context for one symbol — ready to inject into MarketContext."""
        bars_by_tf = fetch_mtf_bars(symbol, timeframes=DEFAULT_MTF_STACK, limit=200)
        if not bars_by_tf:
            return {"valid": False, "reason": "no bars available"}

        result: dict[str, Any] = {"valid": True, "symbol": symbol, "stack": list(bars_by_tf.keys())}

        # Per-TF analysis
        for tf, bars in bars_by_tf.items():
            result[tf] = compute_per_tf_context(bars)

        # Intraday-specific signals (use M3 bars for VWAP precision, H4 for Asian range, M5 for ORB)
        if "M3" in bars_by_tf:
            result["vwap"] = compute_vwap_bands(bars_by_tf["M3"], sigma_mult=2.0)
        elif "M5" in bars_by_tf:
            result["vwap"] = compute_vwap_bands(bars_by_tf["M5"], sigma_mult=2.0)

        if "H1" in bars_by_tf:
            # Asian session range: 07:00-13:00 BD = approximately 6 H1 bars or equiv
            result["asian_range"] = compute_session_range(bars_by_tf["H1"], 7, 13)

        if "M5" in bars_by_tf:
            result["ny_orb"] = compute_orb(bars_by_tf["M5"], session_start_hour_bd=18, orb_minutes=30)
            result["london_orb"] = compute_orb(bars_by_tf["M5"], session_start_hour_bd=13, orb_minutes=30)

        if "D1" in bars_by_tf:
            result["nr7"] = compute_nr7(bars_by_tf["D1"])

        return result


# Global singleton
hub_mtf = MTFHub()
