"""Layer 1: Market structure — BOS, CHoCH, MSS, swing highs/lows, trend. Pure Python."""

from typing import Any

from .base_agent import BaseAgent


def _swing_points(highs: list, lows: list, closes: list, length: int = 5) -> dict:
    """Detect swing highs and lows using fractal logic."""
    if len(highs) < length * 2 + 1:
        return {"swing_highs": [], "swing_lows": []}

    swing_highs = []
    swing_lows = []
    n = len(highs)
    half = length

    for i in range(half, n - half):
        # Swing high: highest in window
        if highs[i] == max(highs[i - half: i + half + 1]):
            swing_highs.append({"idx": i, "price": highs[i]})
        # Swing low: lowest in window
        if lows[i] == min(lows[i - half: i + half + 1]):
            swing_lows.append({"idx": i, "price": lows[i]})

    return {"swing_highs": swing_highs[-10:], "swing_lows": swing_lows[-10:]}


def _classify_structure(swing_highs: list, swing_lows: list) -> dict:
    """Classify HH/HL/LH/LL and determine trend."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"trend": "NEUTRAL", "structure": "UNDEFINED", "hh": False, "hl": False, "lh": False, "ll": False}

    h1, h2 = swing_highs[-2]["price"], swing_highs[-1]["price"]
    l1, l2 = swing_lows[-2]["price"], swing_lows[-1]["price"]

    hh = h2 > h1
    hl = l2 > l1
    lh = h2 < h1
    ll = l2 < l1

    if hh and hl:
        trend = "BULLISH"
        structure = "HH_HL"
    elif lh and ll:
        trend = "BEARISH"
        structure = "LH_LL"
    elif hh and ll:
        trend = "NEUTRAL"
        structure = "EXPANDING"
    elif lh and hl:
        trend = "NEUTRAL"
        structure = "CONTRACTING"
    else:
        trend = "NEUTRAL"
        structure = "MIXED"

    return {"trend": trend, "structure": structure, "hh": hh, "hl": hl, "lh": lh, "ll": ll}


def _detect_bos(closes: list, swing_highs: list, swing_lows: list, trend: str) -> bool:
    """BOS = close beyond last swing in trend direction (close-based, not wick)."""
    if not closes:
        return False
    c = closes[-1]
    if trend == "BULLISH" and swing_highs:
        return c > swing_highs[-1]["price"]
    if trend == "BEARISH" and swing_lows:
        return c < swing_lows[-1]["price"]
    return False


def _detect_choch(closes: list, swing_highs: list, swing_lows: list, trend: str) -> bool:
    """CHoCH = first close break against established trend (reversal signal)."""
    if not closes:
        return False
    c = closes[-1]
    if trend == "BULLISH" and swing_lows:
        return c < swing_lows[-1]["price"]
    if trend == "BEARISH" and swing_highs:
        return c > swing_highs[-1]["price"]
    return False


def _detect_mss(closes: list, highs: list, lows: list, swing_highs: list,
                swing_lows: list, trend: str, atr: float) -> bool:
    """MSS = CHoCH + displacement candle (body > 1.5× ATR)."""
    if len(closes) < 2 or atr <= 0:
        return False
    choch = _detect_choch(closes, swing_highs, swing_lows, trend)
    if not choch:
        return False
    body = abs(closes[-1] - closes[-2])
    return body > 1.5 * atr


def _key_levels(swing_highs: list, swing_lows: list) -> list[float]:
    levels = [sh["price"] for sh in swing_highs[-3:]] + [sl["price"] for sl in swing_lows[-3:]]
    return sorted(set(round(l, 5) for l in levels))


def _dealing_range(swing_highs: list, swing_lows: list) -> dict:
    if not swing_highs or not swing_lows:
        return {"high": 0.0, "low": 0.0, "mid": 0.0, "premium": 0.0, "discount": 0.0}
    high = max(sh["price"] for sh in swing_highs[-3:])
    low = min(sl["price"] for sl in swing_lows[-3:])
    mid = (high + low) / 2
    return {
        "high": round(high, 5),
        "low": round(low, 5),
        "mid": round(mid, 5),
        "premium": round(high - (high - low) * 0.25, 5),   # top 25%
        "discount": round(low + (high - low) * 0.25, 5),   # bottom 25%
    }


class MarketStructureAgent(BaseAgent):
    name = "market_structure"

    def __init__(self, swing_length: int = 5) -> None:
        super().__init__()
        self.swing_length = swing_length

    async def analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ohlcv = ctx.get("ohlcv", {})
        highs = ohlcv.get("high", [])
        lows = ohlcv.get("low", [])
        closes = ohlcv.get("close", [])
        atr = ctx.get("momentum", {}).get("atr", 0.0)

        if len(closes) < self.swing_length * 3:
            return {"trend": "NEUTRAL", "bos": False, "choch": False, "mss": False,
                    "key_levels": [], "dealing_range": {}, "structure": "UNDEFINED"}

        swings = _swing_points(highs, lows, closes, self.swing_length)
        sh = swings["swing_highs"]
        sl = swings["swing_lows"]
        struct = _classify_structure(sh, sl)
        trend = struct["trend"]

        bos = _detect_bos(closes, sh, sl, trend)
        choch = _detect_choch(closes, sh, sl, trend)
        mss = _detect_mss(closes, highs, lows, sh, sl, trend, atr)

        return {
            "trend": trend,
            "structure": struct["structure"],
            "hh": struct["hh"],
            "hl": struct["hl"],
            "lh": struct["lh"],
            "ll": struct["ll"],
            "bos": bos,
            "choch": choch,
            "mss": mss,
            "key_levels": _key_levels(sh, sl),
            "dealing_range": _dealing_range(sh, sl),
            "last_swing_high": sh[-1]["price"] if sh else None,
            "last_swing_low": sl[-1]["price"] if sl else None,
        }
