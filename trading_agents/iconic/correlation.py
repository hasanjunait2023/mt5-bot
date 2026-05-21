"""Currency-strength correlation — Urban Forex ±7 model.

Course rule: read the *previous day's* Daily correlation strength on a ±7
scale; +5/-5 = clearly strong/weak (A-class eligible); ±1 = neutral (downgrades
to B-class). The "leader" pair in a group pulls back the least / holds ground.

We don't have Urban Forex's proprietary Strength Meter, so we map SignalEngine's
own 0..10 currency-strength score (5 = neutral) onto the ±7 scale. The numbers
are a proxy; the *thresholds* and decision logic mirror the course.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Course's G7 focus set (+ CAD/metals tolerated for splitting).
G7 = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CHF")
_KNOWN = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CHF", "CAD", "XAU", "XAG")

# ±7-scale thresholds (course).
STRONG_ABS  = 5.0     # |scale7| >= this → clearly strong/weak
NEUTRAL_ABS = 1.0     # |scale7| <= this → neutral

# Directional pair-strength thresholds (base7 - quote7, range -14..+14).
DIR_STRONG  = 8.0     # A-class correlation lineup
DIR_NEUTRAL = 2.0     # below this (but >0) → neutral/weak → B-class


def split_pair(symbol: str) -> tuple[Optional[str], Optional[str]]:
    """('EUR','USD') from 'EURUSD'; handles XAUUSD etc. None if not splittable."""
    s = symbol.upper().replace("/", "").replace("_", "")
    for pre in _KNOWN:
        if s.startswith(pre):
            rest = s[len(pre):]
            if rest in _KNOWN:
                return pre, rest
    if len(s) == 6 and s.isalpha():
        return s[:3], s[3:]
    return None, None


def to_scale7(strength_0_10: float) -> float:
    """Map SignalEngine 0..10 (5=neutral) onto course ±7 scale."""
    return round((float(strength_0_10) - 5.0) / 5.0 * 7.0, 2)


@dataclass
class PairStrength:
    base: Optional[str]
    quote: Optional[str]
    base7: float
    quote7: float
    diff: float          # base7 - quote7, positive favours BUY


def pair_strength(symbol: str, strength: dict) -> PairStrength:
    base, quote = split_pair(symbol)
    b7 = to_scale7(strength.get(base, 5.0)) if base else 0.0
    q7 = to_scale7(strength.get(quote, 5.0)) if quote else 0.0
    return PairStrength(base, quote, b7, q7, round(b7 - q7, 2))


def correlation_tier(side: str, symbol: str, strength: dict) -> tuple[str, float]:
    """Return ('strong'|'neutral'|'contradicts', directional_value).

    directional = +diff for BUY, -diff for SELL (higher = group backs the trade).
    """
    ps = pair_strength(symbol, strength)
    directional = ps.diff if side == "BUY" else -ps.diff
    if directional >= DIR_STRONG:
        tier = "strong"
    elif directional >= DIR_NEUTRAL:
        tier = "neutral"
    else:
        tier = "contradicts"
    return tier, round(directional, 2)


def pick_leader(group_symbols: list[str], side: str, strength: dict,
                pullbacks: Optional[dict] = None) -> Optional[str]:
    """Leader = strongest directional strength; tie-break on least pullback.

    `pullbacks` (optional): {symbol: 0..1 retrace fraction}. Lower = held ground.
    """
    best, best_key = None, None
    for sym in group_symbols:
        _, directional = correlation_tier(side, sym, strength)
        pb = (pullbacks or {}).get(sym, 0.5)
        key = (directional, -pb)          # max directional, then min pullback
        if best_key is None or key > best_key:
            best_key, best = key, sym
    return best
