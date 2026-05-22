"""Scalping indicator library — pure-Python, zero external deps.

All functions operate on plain Python lists of floats (OHLCV bars from MT5
bridge). Each returns a single scalar (last value) unless noted.

Indicators included:
  _ema_arr      — full EMA array
  ema           — last EMA value
  rsi           — RSI(n) last value
  stoch         — Stochastic %K and %D last values
  bollinger     — BB upper/mid/lower + width + %B last values
  keltner       — Keltner Channel upper/mid/lower last values
  vwap_session  — intraday VWAP for current session (list of times required)
  atr           — ATR(n) last value
  ema_cross     — fast/slow EMA cross detection (+1 bull, -1 bear, 0 none)
"""
from __future__ import annotations
import math
from zoneinfo import ZoneInfo

BD_TZ = ZoneInfo("Asia/Dhaka")


# ── Core helpers ────────────────────────────────────────────────────────────

def _ema_arr(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def ema(closes: list[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    return _ema_arr(closes, period)[-1]


def atr(highs: list[float], lows: list[float], closes: list[float],
        period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs:
        return 0.0
    # Wilder smoothing
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


# ── RSI ─────────────────────────────────────────────────────────────────────

def rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1 + rs), 2)


# ── Stochastic ──────────────────────────────────────────────────────────────

def stoch(highs: list[float], lows: list[float], closes: list[float],
          k_period: int = 14, d_period: int = 3,
          smooth_k: int = 3) -> dict[str, float]:
    """Returns %K and %D (last values). smooth_k=1 → fast stoch, 3 → slow."""
    if len(closes) < k_period + d_period:
        return {"k": 50.0, "d": 50.0}
    raw_k = []
    for i in range(k_period - 1, len(closes)):
        window_h = max(highs[i - k_period + 1: i + 1])
        window_l = min(lows[i - k_period + 1: i + 1])
        rng = window_h - window_l
        if rng == 0:
            raw_k.append(50.0)
        else:
            raw_k.append(100.0 * (closes[i] - window_l) / rng)
    # Smooth %K
    if smooth_k > 1 and len(raw_k) >= smooth_k:
        smoothed_k = _ema_arr(raw_k, smooth_k)
    else:
        smoothed_k = raw_k
    # %D = SMA of smoothed %K
    k_val = smoothed_k[-1]
    d_val = sum(smoothed_k[-d_period:]) / min(len(smoothed_k), d_period)
    return {"k": round(k_val, 2), "d": round(d_val, 2)}


# ── Bollinger Bands ──────────────────────────────────────────────────────────

def bollinger(closes: list[float], period: int = 20,
              std_mult: float = 2.0) -> dict[str, float]:
    if len(closes) < period:
        p = closes[-1] if closes else 0.0
        return {"upper": p, "mid": p, "lower": p, "width": 0.0, "pct_b": 0.5}
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((c - mid) ** 2 for c in window) / period
    std = math.sqrt(variance)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = (upper - lower) / mid if mid != 0 else 0.0
    price = closes[-1]
    pct_b = (price - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
    return {
        "upper": round(upper, 5),
        "mid": round(mid, 5),
        "lower": round(lower, 5),
        "width": round(width, 5),
        "pct_b": round(pct_b, 3),
    }


# ── Keltner Channel ──────────────────────────────────────────────────────────

def keltner(highs: list[float], lows: list[float], closes: list[float],
            ema_period: int = 20, atr_period: int = 14,
            atr_mult: float = 2.0) -> dict[str, float]:
    if len(closes) < ema_period:
        p = closes[-1] if closes else 0.0
        return {"upper": p, "mid": p, "lower": p}
    mid = ema(closes, ema_period)
    atr_val = atr(highs, lows, closes, atr_period)
    upper = mid + atr_mult * atr_val
    lower = mid - atr_mult * atr_val
    price = closes[-1]
    return {
        "upper": round(upper, 5),
        "mid": round(mid, 5),
        "lower": round(lower, 5),
        "above_upper": price > upper,
        "below_lower": price < lower,
    }


# ── VWAP (intraday session) ───────────────────────────────────────────────────

def vwap_session(highs: list[float], lows: list[float], closes: list[float],
                 volumes: list[float], times_unix: list[int],
                 session_start_bd_hour: int = 0) -> dict[str, float]:
    """VWAP anchored to session start hour (BD time)."""
    from datetime import datetime as _dt
    cum_pv, cum_v, tps = 0.0, 0.0, []
    for i, ts in enumerate(times_unix):
        bd = _dt.fromtimestamp(ts, tz=BD_TZ)
        if bd.hour < session_start_bd_hour:
            continue
        tp = (highs[i] + lows[i] + closes[i]) / 3
        v = max(volumes[i], 1.0)
        cum_pv += tp * v
        cum_v += v
        tps.append(tp)
    if not tps or cum_v == 0:
        p = closes[-1] if closes else 0.0
        return {"vwap": p, "upper": p, "lower": p}
    vwap_val = cum_pv / cum_v
    devs = [tp - vwap_val for tp in tps]
    sigma = math.sqrt(sum(d * d for d in devs) / len(devs)) if len(devs) > 1 else 0.0
    return {
        "vwap": round(vwap_val, 5),
        "upper": round(vwap_val + 2 * sigma, 5),
        "lower": round(vwap_val - 2 * sigma, 5),
    }


# ── EMA Cross signal ─────────────────────────────────────────────────────────

def ema_cross(closes: list[float], fast: int, slow: int) -> int:
    """Returns +1 (bullish cross this bar), -1 (bearish cross), 0 (no cross)."""
    if len(closes) < slow + 2:
        return 0
    fast_arr = _ema_arr(closes, fast)
    slow_arr = _ema_arr(closes, slow)
    prev_diff = fast_arr[-2] - slow_arr[-2]
    curr_diff = fast_arr[-1] - slow_arr[-1]
    if prev_diff < 0 and curr_diff >= 0:
        return 1   # bullish cross
    if prev_diff > 0 and curr_diff <= 0:
        return -1  # bearish cross
    return 0


def ema_above(closes: list[float], fast: int, slow: int) -> bool:
    """True if fast EMA is currently above slow EMA."""
    if len(closes) < slow:
        return False
    return _ema_arr(closes, fast)[-1] > _ema_arr(closes, slow)[-1]


# ── Swing high/low ──────────────────────────────────────────────────────────

def swing_high(highs: list[float], lookback: int = 5) -> float | None:
    if len(highs) < lookback * 2 + 1:
        return None
    for i in range(len(highs) - lookback - 1, lookback - 1, -1):
        candidate = highs[i]
        if all(candidate >= highs[j] for j in range(i - lookback, i + lookback + 1)):
            return candidate
    return None


def swing_low(lows: list[float], lookback: int = 5) -> float | None:
    if len(lows) < lookback * 2 + 1:
        return None
    for i in range(len(lows) - lookback - 1, lookback - 1, -1):
        candidate = lows[i]
        if all(candidate <= lows[j] for j in range(i - lookback, i + lookback + 1)):
            return candidate
    return None


# ── FVG detection ────────────────────────────────────────────────────────────

def has_bullish_fvg(highs: list[float], lows: list[float],
                    closes: list[float], lookback: int = 10) -> bool:
    """True if there's an unfilled bullish FVG in the last N bars."""
    if len(highs) < 3:
        return False
    for i in range(max(1, len(highs) - lookback), len(highs) - 1):
        if lows[i + 1] > highs[i - 1] if i >= 1 else False:
            return True
    return False


def has_bearish_fvg(highs: list[float], lows: list[float],
                    closes: list[float], lookback: int = 10) -> bool:
    if len(highs) < 3:
        return False
    for i in range(max(1, len(highs) - lookback), len(highs) - 1):
        if i >= 1 and highs[i + 1] < lows[i - 1]:
            return True
    return False
