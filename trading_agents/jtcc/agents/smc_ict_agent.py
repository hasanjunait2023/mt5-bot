"""Layer 1: SMC/ICT detector — OB, FVG, liquidity sweeps, OTE zone. Pure Python."""

from typing import Any

from .base_agent import BaseAgent


def _detect_fvg(opens: list, highs: list, lows: list, closes: list) -> list[dict]:
    """Fair Value Gap: 3-candle pattern where candle[i-1].high < candle[i+1].low (bull FVG)."""
    fvgs = []
    n = len(closes)
    if n < 3:
        return fvgs
    for i in range(1, n - 1):
        bull_fvg = lows[i + 1] > highs[i - 1]  # gap above (bullish imbalance)
        bear_fvg = highs[i + 1] < lows[i - 1]  # gap below (bearish imbalance)
        if bull_fvg:
            fvgs.append({"type": "BULL", "top": lows[i + 1], "bottom": highs[i - 1],
                         "idx": i, "mid": (lows[i + 1] + highs[i - 1]) / 2})
        if bear_fvg:
            fvgs.append({"type": "BEAR", "top": lows[i - 1], "bottom": highs[i + 1],
                         "idx": i, "mid": (lows[i - 1] + highs[i + 1]) / 2})
    return fvgs[-5:]  # last 5 FVGs


def _detect_order_blocks(opens: list, highs: list, lows: list, closes: list) -> list[dict]:
    """Order Block: last opposite candle before BOS. Simplified: last bearish before bullish BOS."""
    obs = []
    n = len(closes)
    if n < 5:
        return obs
    for i in range(2, n - 2):
        # Bullish OB: last bearish candle before price takes out a high
        if closes[i] < opens[i]:  # bearish candle
            if closes[i + 1] > highs[i] or closes[i + 2] > highs[i]:  # price sweeps above
                obs.append({"type": "BULL", "top": highs[i], "bottom": lows[i],
                            "idx": i, "mid": (highs[i] + lows[i]) / 2})
        # Bearish OB: last bullish candle before price takes out a low
        if closes[i] > opens[i]:
            if closes[i + 1] < lows[i] or closes[i + 2] < lows[i]:
                obs.append({"type": "BEAR", "top": highs[i], "bottom": lows[i],
                            "idx": i, "mid": (highs[i] + lows[i]) / 2})
    return obs[-5:]


def _detect_sweep(highs: list, lows: list, closes: list, swing_highs: list, swing_lows: list) -> dict:
    """Liquidity sweep: wick beyond swing level + close back inside."""
    if len(closes) < 3 or not swing_highs or not swing_lows:
        return {"detected": False, "type": None, "quality": 0}

    last_high = swing_highs[-1]["price"] if swing_highs else None
    last_low = swing_lows[-1]["price"] if swing_lows else None
    c, h, l = closes[-1], highs[-1], lows[-1]
    prev_c = closes[-2]

    # SSL sweep: wick below swing low, close back above
    if last_low and l < last_low and c > last_low:
        # Quality: how decisive is the close-back
        quality = min(10, round((c - last_low) / (last_low * 0.001) * 2, 1))
        return {"detected": True, "type": "SSL_SWEEP", "swept_level": last_low,
                "quality": quality, "close": c}

    # BSL sweep: wick above swing high, close back below
    if last_high and h > last_high and c < last_high:
        quality = min(10, round((last_high - c) / (last_high * 0.001) * 2, 1))
        return {"detected": True, "type": "BSL_SWEEP", "swept_level": last_high,
                "quality": quality, "close": c}

    return {"detected": False, "type": None, "quality": 0}


def _detect_equal_levels(swing_points: list, tolerance_pct: float = 0.001) -> list[dict]:
    """Equal highs/lows = liquidity pools."""
    pools = []
    for i in range(len(swing_points)):
        for j in range(i + 1, len(swing_points)):
            a, b = swing_points[i]["price"], swing_points[j]["price"]
            if abs(a - b) / a < tolerance_pct:
                pools.append({"price": (a + b) / 2, "count": 2, "idx_first": i, "idx_last": j})
    return pools


def _ote_zone(swing_high: float, swing_low: float) -> dict:
    """OTE zone: 62%-79% Fibonacci retracement."""
    if swing_high <= swing_low:
        return {"top": 0.0, "bottom": 0.0, "mid": 0.0}
    rng = swing_high - swing_low
    ote_bottom = swing_high - rng * 0.79  # 79% retrace from high (for buys)
    ote_top = swing_high - rng * 0.62     # 62% retrace from high
    return {"top": round(ote_top, 5), "bottom": round(ote_bottom, 5),
            "mid": round((ote_top + ote_bottom) / 2, 5)}


def _pd_zone(dealing_range: dict) -> dict:
    """Premium/Discount zones from dealing range."""
    h = dealing_range.get("high", 0)
    l = dealing_range.get("low", 0)
    mid = dealing_range.get("mid", 0)
    return {"premium": h > 0 and mid > 0, "discount": l > 0 and mid > 0,
            "premium_level": dealing_range.get("premium", 0),
            "discount_level": dealing_range.get("discount", 0)}


class SmcIctAgent(BaseAgent):
    name = "smc_ict"

    async def analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ohlcv = ctx.get("ohlcv", {})
        opens = ohlcv.get("open", [])
        highs = ohlcv.get("high", [])
        lows = ohlcv.get("low", [])
        closes = ohlcv.get("close", [])
        ms = ctx.get("market_structure", {})
        swing_highs = ms.get("_swing_highs_raw", [])
        swing_lows = ms.get("_swing_lows_raw", [])
        dealing_range = ms.get("dealing_range", {})

        if len(closes) < 10:
            return self._empty()

        fvgs = _detect_fvg(opens, highs, lows, closes)
        obs = _detect_order_blocks(opens, highs, lows, closes)
        sweep = _detect_sweep(highs, lows, closes, swing_highs, swing_lows)
        sh_prices = [{"price": h, "idx": i} for i, h in enumerate(highs)]
        sl_prices = [{"price": l, "idx": i} for i, l in enumerate(lows)]
        bsl_pools = _detect_equal_levels(sh_prices)
        ssl_pools = _detect_equal_levels(sl_prices)

        last_sh = ms.get("last_swing_high")
        last_sl = ms.get("last_swing_low")
        ote = _ote_zone(last_sh, last_sl) if last_sh and last_sl else {}
        pd = _pd_zone(dealing_range)

        price = closes[-1]
        in_ote = ote and ote["bottom"] <= price <= ote["top"]
        in_discount = dealing_range and price <= dealing_range.get("discount", 0)
        in_premium = dealing_range and price >= dealing_range.get("premium", float("inf"))

        bull_fvgs = [f for f in fvgs if f["type"] == "BULL"]
        bear_fvgs = [f for f in fvgs if f["type"] == "BEAR"]
        bull_obs = [o for o in obs if o["type"] == "BULL"]
        bear_obs = [o for o in obs if o["type"] == "BEAR"]

        return {
            "fvg_zones": fvgs,
            "ob_zones": obs,
            "bull_fvg_count": len(bull_fvgs),
            "bear_fvg_count": len(bear_fvgs),
            "bull_ob_count": len(bull_obs),
            "bear_ob_count": len(bear_obs),
            "nearest_bull_fvg": bull_fvgs[-1] if bull_fvgs else None,
            "nearest_bear_fvg": bear_fvgs[-1] if bear_fvgs else None,
            "sweep_detected": sweep["detected"],
            "sweep_type": sweep["type"],
            "sweep_quality": sweep["quality"],
            "ssl_pools": ssl_pools[:3],
            "bsl_pools": bsl_pools[:3],
            "ote_zone": ote,
            "in_ote": in_ote,
            "in_discount": in_discount,
            "in_premium": in_premium,
            "pd_zone": pd,
        }

    def _empty(self) -> dict:
        return {
            "fvg_zones": [], "ob_zones": [], "bull_fvg_count": 0, "bear_fvg_count": 0,
            "bull_ob_count": 0, "bear_ob_count": 0, "nearest_bull_fvg": None, "nearest_bear_fvg": None,
            "sweep_detected": False, "sweep_type": None, "sweep_quality": 0,
            "ssl_pools": [], "bsl_pools": [], "ote_zone": {}, "in_ote": False,
            "in_discount": False, "in_premium": False, "pd_zone": {},
        }
