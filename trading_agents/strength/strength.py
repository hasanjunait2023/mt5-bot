"""Faithful -7..+7 net-pair-win currency strength (pure Python, zero deps).

Mirrors the user's external "FX Co-Relation Strength" scanner semantics: each
currency's score = (#pairs it strengthened in) - (#pairs it weakened in) across
its 7 major matchups, so the result is naturally bounded to -7..+7. Tiered and
turned into strength-difference BUY/SELL pair suggestions, computed per session
window (Asian / London-1H / New York).

Operates on plain lists of floats (OHLC bars from the MT5 bridge). Reuses
``split_pair`` (currency split) and ``session_info`` (BD-tz hour) so there is a
single definition of those concepts in the repo.
"""
from __future__ import annotations

from typing import Optional

from trading_agents.iconic.correlation import split_pair
from trading_agents.scalp.indicators import ema, session_info

# 8 majors. Each appears in exactly 7 of the 28 pairs → net score ∈ [-7, +7].
MAJORS = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF")

# 28 unique combos in conventional broker quote order (so split_pair resolves).
PAIRS28 = (
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "USDCHF",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD",
    "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF",
    "NZDJPY", "NZDCAD", "NZDCHF",
    "CADJPY", "CADCHF", "CHFJPY",
)

# Session hour bands (Asia/Dhaka time, matching indicators.session_info killzones).
# Each band spans several H1 bars so the window return is computable.
SESSIONS = {
    "asian":     {"start_h": 7,  "end_h": 11},   # Tokyo/Sydney
    "london_1h": {"start_h": 13, "end_h": 17},   # London session
    "newyork":   {"start_h": 18, "end_h": 22},   # New York session
}

MIN_DIFF = 3   # pair suggestion threshold (|strength[base]-strength[quote]|)


def pair_vote(highs: list[float], lows: list[float], closes: list[float],
              eps: float = 2e-4) -> int:
    """Did the base currency win this matchup over the window? +1 / 0 / -1.

    Primary signal = window return (matches the scanner's "who got stronger").
    When enough bars exist, confirm direction with the EMA9/EMA15 stack so a
    whippy window that closed up but is rolling over does not over-count.
    """
    if len(closes) < 2:
        return 0
    base = closes[0]
    if base == 0:
        return 0
    ret = (closes[-1] - base) / abs(base)
    if abs(ret) < eps:
        return 0
    if len(closes) >= 15:
        e9, e15 = ema(closes, 9), ema(closes, 15)
        if ret > 0 and not (e9 > e15):
            return 0
        if ret < 0 and not (e9 < e15):
            return 0
    return 1 if ret > 0 else -1


def currency_strength(pair_bars: dict, window_bars: Optional[int] = None,
                      eps: float = 2e-4) -> dict:
    """Net-pair-win score per major from a {symbol: {high,low,close}} dict.

    ``window_bars`` (optional) keeps only the last N bars of each series before
    voting. Returns {ccy: int in [-7, +7]} for all 8 MAJORS.
    """
    score = {c: 0 for c in MAJORS}
    for sym in PAIRS28:
        b = pair_bars.get(sym)
        if not b:
            continue
        h = b.get("high", [])
        l = b.get("low", [])
        c = b.get("close", [])
        if window_bars:
            h, l, c = h[-window_bars:], l[-window_bars:], c[-window_bars:]
        base, quote = split_pair(sym)
        if base not in score or quote not in score:
            continue
        v = pair_vote(h, l, c, eps)
        if v:
            score[base] += v
            score[quote] -= v
    return score


def tier(s: int) -> str:
    """Map a -7..+7 score onto the doc's 5-tier system (sign picks the side)."""
    a = abs(s)
    if a >= 5:
        return "STRONG" if s > 0 else "WEAK"
    if a >= 2:
        return "MID_STRONG" if s > 0 else "MID_WEAK"
    return "NEUTRAL"


def suggestions(score: dict, min_diff: int = MIN_DIFF) -> list:
    """BUY/SELL pair suggestions ranked by |strength difference| (desc)."""
    out = []
    for sym in PAIRS28:
        base, quote = split_pair(sym)
        if base not in score or quote not in score:
            continue
        diff = score[base] - score[quote]
        if abs(diff) < min_diff:
            continue
        out.append({
            "symbol": sym,
            "base": base,
            "quote": quote,
            "diff": diff,
            "side": "BUY" if diff > 0 else "SELL",
        })
    out.sort(key=lambda r: abs(r["diff"]), reverse=True)
    return out


def _latest_session_slice(times: list, h_start: int, h_end: int,
                          now_unix: Optional[int] = None):
    """Index range (i0, i1) of the latest contiguous bar block inside the band."""
    in_band = []
    for i, t in enumerate(times):
        ti = int(t)
        if now_unix is not None and ti > now_unix:
            continue
        h = session_info(ti)["hour"]
        if h_start <= h < h_end:
            in_band.append(i)
    if not in_band:
        return None
    s = set(in_band)
    end = in_band[-1]
    start = end
    while (start - 1) in s:
        start -= 1
    return start, end + 1


def compute_sessions(pair_bars_full: dict, now_unix: int) -> dict:
    """Per-session strength from {symbol: {time,high,low,close}} H1 series.

    For each session, each symbol is sliced to the latest contiguous block of
    bars inside that session's hour band, then strength/tiers/suggestions are
    computed on those slices.
    """
    result = {}
    for name, win in SESSIONS.items():
        sliced = {}
        for sym, b in pair_bars_full.items():
            times = b.get("time", [])
            sl = _latest_session_slice(times, win["start_h"], win["end_h"], now_unix)
            if sl is None:
                continue
            i0, i1 = sl
            sliced[sym] = {
                "high": b.get("high", [])[i0:i1],
                "low": b.get("low", [])[i0:i1],
                "close": b.get("close", [])[i0:i1],
            }
        score = currency_strength(sliced)
        result[name] = {
            "score": score,
            "tiers": {c: tier(s) for c, s in score.items()},
            "suggestions": suggestions(score),
        }
    return result


def trade_of_the_day(sessions: dict) -> Optional[dict]:
    """Highest |diff| suggestion, preferring New York > London > Asian."""
    for key in ("newyork", "london_1h", "asian"):
        sug = (sessions.get(key) or {}).get("suggestions") or []
        if sug:
            top = sug[0]
            return {
                "symbol": top["symbol"],
                "side": top["side"],
                "diff": top["diff"],
                "session": key,
            }
    return None
