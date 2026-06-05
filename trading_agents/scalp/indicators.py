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


# ── Session timing (BD time kill-zones) ───────────────────────────────────────

def session_info(t_unix: int) -> dict:
    """Session/kill-zone flags for a unix timestamp (Asia/Dhaka hours).

    Mirrors backtest._session_bd so factory-generated strategies can filter by
    session without importing from the backtest module. Pure + dependency-free.
    """
    from datetime import datetime as _dt
    h = _dt.fromtimestamp(t_unix, tz=BD_TZ).hour
    return {
        "hour": h,
        "london_kz": 13 <= h < 16,
        "ny_kz": 18 <= h < 21,
        "asian_kz": 7 <= h < 11,
        "london_open": h == 13,
        "ny_open": h == 18,
        "any_primary": (13 <= h < 16) or (18 <= h < 21),
    }


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


# ── ADR (Average Daily Range) ────────────────────────────────────────────────

def adr(d1_highs: list[float], d1_lows: list[float], period: int = 14) -> float:
    """Average Daily Range = mean of the last `period` COMPLETED daily H-L.

    Pass D1 bars; the still-forming current day (last bar) is excluded so the
    average reflects settled ranges only.
    """
    if len(d1_highs) < period + 1:
        return 0.0
    rngs = [d1_highs[i] - d1_lows[i]
            for i in range(len(d1_highs) - period - 1, len(d1_highs) - 1)]
    return sum(rngs) / len(rngs) if rngs else 0.0


def adr_used_frac(today_high: float, today_low: float, adr_val: float) -> float:
    """Fraction of ADR already covered by today's range (1.0 = exhausted)."""
    if adr_val <= 0:
        return 1.0
    return (today_high - today_low) / adr_val


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


# ── ICT triad detectors (Sweep → Inverse FVG → Trendline break) ────────────────
# Used by GS12. Pure-Python, list-based; operate on the full history slice the
# backtest engine passes (cl = closes[:t_i+1], etc.). All return plain dicts/ints.

def _swing_points(highs: list[float], lows: list[float],
                  lookback: int = 3) -> dict[str, list[tuple[int, float]]]:
    """Fractal swing highs/lows as (index, price) lists, oldest→newest.

    A bar i is a swing high if its high is the max of [i-lookback, i+lookback]
    (strict, unique on the left). Mirror for swing lows. Excludes the final
    `lookback` bars (not yet confirmable).
    """
    sh: list[tuple[int, float]] = []
    sl: list[tuple[int, float]] = []
    n = len(highs)
    if n < lookback * 2 + 1:
        return {"highs": sh, "lows": sl}
    for i in range(lookback, n - lookback):
        win_h = highs[i - lookback: i + lookback + 1]
        win_l = lows[i - lookback: i + lookback + 1]
        if highs[i] == max(win_h) and highs[i] > max(highs[i - lookback: i]):
            sh.append((i, highs[i]))
        if lows[i] == min(win_l) and lows[i] < min(lows[i - lookback: i]):
            sl.append((i, lows[i]))
    return {"highs": sh, "lows": sl}


def detect_liquidity_sweep(highs: list[float], lows: list[float],
                           closes: list[float], lookback: int = 5,
                           min_depth_atr: float = 0.15,
                           atr_val: float = 0.0,
                           recent: int = 3) -> dict | None:
    """Stop-hunt sweep at/near the current bar.

    BULL sweep: one of the last `recent` bars wicked below a prior swing low,
    and the current close is back above that level (sell-side liquidity grab).
    BEAR sweep: wicked above a prior swing high, current close back below.

    `min_depth_atr` filters tick-noise: the wick must pierce the level by at
    least that many ATRs. Returns {side, level, depth_atr} or None.
    """
    n = len(closes)
    if n < lookback * 2 + 3 or atr_val <= 0:
        return None
    # Prior swing levels, ignoring the most recent `recent` bars (the sweep window).
    prior_h = highs[: n - recent]
    prior_l = lows[: n - recent]
    sw_lo = swing_low(prior_l, lookback)
    sw_hi = swing_high(prior_h, lookback)
    price = closes[-1]
    win_lo = min(lows[-recent:])
    win_hi = max(highs[-recent:])

    if sw_lo is not None and win_lo < sw_lo and price > sw_lo:
        depth = (sw_lo - win_lo) / atr_val
        if depth >= min_depth_atr:
            return {"side": "BULL", "level": sw_lo, "depth_atr": round(depth, 3)}
    if sw_hi is not None and win_hi > sw_hi and price < sw_hi:
        depth = (win_hi - sw_hi) / atr_val
        if depth >= min_depth_atr:
            return {"side": "BEAR", "level": sw_hi, "depth_atr": round(depth, 3)}
    return None


def find_fvg_zones(opens: list[float], highs: list[float], lows: list[float],
                   closes: list[float], lookback: int = 12) -> list[dict]:
    """3-candle Fair Value Gaps in the last `lookback` bars.

    Bull FVG at i:  lows[i+1] > highs[i-1]  → gap [highs[i-1], lows[i+1]]
    Bear FVG at i:  highs[i+1] < lows[i-1]  → gap [highs[i+1], lows[i-1]]
    idx = i+1 (the bar completing the gap).
    """
    zones: list[dict] = []
    n = len(closes)
    start = max(1, n - 1 - lookback)
    for i in range(start, n - 1):
        if lows[i + 1] > highs[i - 1]:
            zones.append({"type": "BULL", "bottom": highs[i - 1],
                          "top": lows[i + 1], "idx": i + 1})
        elif highs[i + 1] < lows[i - 1]:
            zones.append({"type": "BEAR", "bottom": highs[i + 1],
                          "top": lows[i - 1], "idx": i + 1})
    return zones


def find_inverse_fvg(opens: list[float], highs: list[float], lows: list[float],
                     closes: list[float], lookback: int = 16,
                     active_within: int = 6) -> list[dict]:
    """Inverse FVGs: a FVG that price has CLOSED through, flipping polarity.

    A bull FVG breached by a later close below its bottom flips to a BEAR IFVG
    (the old support box now acts as resistance). A bear FVG breached by a later
    close above its top flips to a BULL IFVG (old resistance now support).

    Returns zones violated within the last `active_within` bars:
    {flipped_side, top, bottom, idx_violated}.
    """
    n = len(closes)
    out: list[dict] = []
    zones = find_fvg_zones(opens, highs, lows, closes, lookback)
    for z in zones:
        gi = z["idx"]
        # Bounded forward scan: a violation relevant to "now" must land within
        # lookback+active_within bars of the gap (older flips are stale). Keeps
        # this O(window) per bar instead of O(n).
        scan_end = min(n, gi + 1 + lookback + active_within)
        for j in range(gi + 1, scan_end):
            if z["type"] == "BULL" and closes[j] < z["bottom"]:
                if n - 1 - j <= active_within:
                    out.append({"flipped_side": "BEAR", "top": z["top"],
                                "bottom": z["bottom"], "idx_violated": j})
                break
            if z["type"] == "BEAR" and closes[j] > z["top"]:
                if n - 1 - j <= active_within:
                    out.append({"flipped_side": "BULL", "top": z["top"],
                                "bottom": z["bottom"], "idx_violated": j})
                break
    return out


def detect_trendline_break(highs: list[float], lows: list[float],
                           closes: list[float], swing_lookback: int = 3,
                           fit_swings: int = 2) -> int:
    """Break of a swing-anchored trendline. +1 up-break, -1 down-break, 0 none.

    Up-break: connect the last two DESCENDING swing highs into a line, project
    to the current bar; current close above the line = trend change up.
    Down-break: connect the last two ASCENDING swing lows; close below = down.
    Falls back to MSS (close beyond the most recent swing) when too few swings.
    """
    n = len(closes)
    sp = _swing_points(highs, lows, swing_lookback)
    sh, sl = sp["highs"], sp["lows"]
    price = closes[-1]
    x = n - 1

    # Up-break via descending trendline through last two swing highs.
    if len(sh) >= fit_swings:
        a, b = sh[-fit_swings], sh[-1]
        if b[1] < a[1] and b[0] != a[0]:  # descending
            m = (b[1] - a[1]) / (b[0] - a[0])
            proj = b[1] + m * (x - b[0])
            if price > proj:
                return 1
    # Down-break via ascending trendline through last two swing lows.
    if len(sl) >= fit_swings:
        a, b = sl[-fit_swings], sl[-1]
        if b[1] > a[1] and b[0] != a[0]:  # ascending
            m = (b[1] - a[1]) / (b[0] - a[0])
            proj = b[1] + m * (x - b[0])
            if price < proj:
                return -1
    # Fallback: market-structure break (close beyond most recent swing).
    if sh and price > sh[-1][1]:
        return 1
    if sl and price < sl[-1][1]:
        return -1
    return 0


# ── Session Volume Profile (POC / VAH / VAL / HVN / LVN) ──────────────────────
#
# Computed from bars, NOT read from any TV indicator. Volume basis is the bar
# `tick_volume` (MT5 spot/crypto have no real traded-volume tape) — a proxy,
# strongest on 24/7 crypto. The profile of a completed session is fixed, so it
# is cached per (prior_day, price-magnitude) to keep backtests near O(n).

_VP_CACHE: dict = {}


def _day_start_unix(t_unix: int, tz=BD_TZ) -> int:
    from datetime import datetime as _dt
    d = _dt.fromtimestamp(t_unix, tz=tz).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp())


def session_volume_profile(times: list[int], highs: list[float],
                           lows: list[float], vols: list[float],
                           as_of_idx: int | None = None, *,
                           bins: int = 50, value_area_pct: float = 0.70,
                           edge_frac: float = 0.12, round_dp: int | None = None,
                           tz=BD_TZ) -> dict | None:
    """Volume-by-price profile of the PRIOR completed session (calendar day in
    `tz`), as seen at bar `as_of_idx`. Volume distributed evenly across each
    bar's [low, high]. Returns POC / VAH / VAL (70% value area) plus interior
    LVN/HVN price levels, or None if there is not enough data.
    """
    if not times:
        return None
    if as_of_idx is None:
        as_of_idx = len(times) - 1
    if as_of_idx < 0 or as_of_idx >= len(times):
        return None

    cur_day = _day_start_unix(times[as_of_idx], tz)
    prior_day = None
    for i in range(as_of_idx, -1, -1):
        d = _day_start_unix(times[i], tz)
        if d < cur_day:
            prior_day = d
            break
    if prior_day is None:
        return None

    idxs = [i for i in range(as_of_idx + 1)
            if _day_start_unix(times[i], tz) == prior_day]
    if len(idxs) < max(20, bins // 2):
        return None

    lo = min(lows[i] for i in idxs)
    hi = max(highs[i] for i in idxs)
    if hi <= lo:
        return None

    if round_dp is None:
        # Magnitude-aware precision: gold/crypto fine at 2dp; FX/silver need more
        # (else 1.16xxx collapses to 1.16 and all levels alias). 2dp default
        # preserves prior behaviour for high-priced symbols.
        round_dp = 2 if hi >= 100 else 5
    # Precision-safe cache key: int(hi) aliased same-magnitude days (FX, silver),
    # returning a stale profile. Key on the exact band + binning instead.
    key = (prior_day, round(lo, 8), round(hi, 8), bins, round(value_area_pct, 4))
    cached = _VP_CACHE.get(key)
    if cached is not None:
        return cached

    binsz = (hi - lo) / bins
    vol = [0.0] * bins
    for i in idxs:
        i0 = max(0, int((lows[i] - lo) / binsz))
        i1 = min(bins - 1, int((highs[i] - lo) / binsz))
        share = vols[i] / (i1 - i0 + 1)
        for k in range(i0, i1 + 1):
            vol[k] += share

    total = sum(vol)
    if total <= 0:
        return None

    poc_i = max(range(bins), key=lambda k: vol[k])

    # Expand value area outward from POC until value_area_pct of volume covered.
    covered = vol[poc_i]
    lo_i = hi_i = poc_i
    target = total * value_area_pct
    while covered < target and (lo_i > 0 or hi_i < bins - 1):
        below = vol[lo_i - 1] if lo_i > 0 else -1.0
        above = vol[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += vol[hi_i]
        else:
            lo_i -= 1
            covered += vol[lo_i]

    def _price(k: float) -> float:
        return lo + (k + 0.5) * binsz

    # Interior local minima / maxima (skip outer tails — trivially thin).
    e = int(bins * edge_frac)
    lvn, hvn = [], []
    for k in range(max(1, e), min(bins - 1, bins - e)):
        if vol[k] <= vol[k - 1] and vol[k] <= vol[k + 1]:
            lvn.append(round(_price(k), round_dp))
        if vol[k] >= vol[k - 1] and vol[k] >= vol[k + 1]:
            hvn.append(round(_price(k), round_dp))

    result = {
        "poc": round(_price(poc_i), round_dp),
        "vah": round(lo + (hi_i + 1) * binsz, round_dp),
        "val": round(lo + lo_i * binsz, round_dp),
        "day_high": round(hi, round_dp),
        "day_low": round(lo, round_dp),
        "bin_size": round(binsz, 6),
        "total_vol": round(total, 2),
        "lvn": lvn,
        "hvn": hvn,
        "prior_day": prior_day,
    }
    _VP_CACHE[key] = result
    return result
