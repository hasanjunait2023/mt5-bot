"""Layer 1: Momentum indicators — ATR, RSI, EMA, HA, ADX, Stoch, MACD. Pure Python, zero tokens."""

import math
from typing import Any

import numpy as np

from .base_agent import BaseAgent


def _ema(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs[-period:]) / period


def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Simplified ADX calculation."""
    if len(highs) < period * 2:
        return 0.0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr14 = sum(trs[-period:]) / period
    if atr14 == 0:
        return 0.0
    pdi = (sum(plus_dm[-period:]) / period) / atr14 * 100
    mdi = (sum(minus_dm[-period:]) / period) / atr14 * 100
    dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
    return dx


def _stoch(highs: list[float], lows: list[float], closes: list[float],
           k_period: int = 14, d_period: int = 3) -> tuple[float, float]:
    if len(closes) < k_period:
        return 50.0, 50.0
    highest = max(highs[-k_period:])
    lowest = min(lows[-k_period:])
    if highest == lowest:
        return 50.0, 50.0
    k = (closes[-1] - lowest) / (highest - lowest) * 100
    # Simplified D as single-period (full D would need rolling K)
    d = k
    return round(k, 2), round(d, 2)


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema[slow - fast:], slow_ema)]
    signal_line = _ema(macd_line, signal)
    hist = macd_line[-1] - signal_line[-1]
    return round(macd_line[-1], 6), round(signal_line[-1], 6), round(hist, 6)


def _heikin_ashi(opens: list, highs: list, lows: list, closes: list, n: int = 3) -> dict:
    """Check last n candles for HA trend."""
    if len(closes) < n + 1:
        return {"bull": False, "bear": False, "streak": 0}
    ha_closes, ha_opens = [], []
    for i in range(len(closes)):
        ha_c = (opens[i] + highs[i] + lows[i] + closes[i]) / 4
        ha_o = ha_opens[i - 1] + ha_closes[i - 1] if i > 0 else (opens[i] + closes[i]) / 2
        ha_closes.append(ha_c)
        ha_opens.append(ha_o)
    # Check last n candles
    bull = all(ha_closes[-(n - j)] > ha_opens[-(n - j)] for j in range(n))
    bear = all(ha_closes[-(n - j)] < ha_opens[-(n - j)] for j in range(n))
    streak = 0
    last_bull = ha_closes[-1] > ha_opens[-1]
    for i in range(1, len(ha_closes) + 1):
        if (ha_closes[-i] > ha_opens[-i]) == last_bull:
            streak += 1
        else:
            break
    return {"bull": bull, "bear": bear, "streak": streak}


class MomentumAgent(BaseAgent):
    name = "momentum"

    async def analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ohlcv = ctx.get("ohlcv", {})
        opens = ohlcv.get("open", [])
        highs = ohlcv.get("high", [])
        lows = ohlcv.get("low", [])
        closes = ohlcv.get("close", [])

        if len(closes) < 26:
            return self._empty()

        ema_vals = _ema(closes, 20)
        ema50_vals = _ema(closes, 50)
        ema200_vals = _ema(closes, 200) if len(closes) >= 200 else _ema(closes, len(closes) // 2)

        ema20 = round(ema_vals[-1], 5)
        ema50 = round(ema50_vals[-1], 5) if len(closes) >= 50 else ema20
        ema200 = round(ema200_vals[-1], 5)

        atr = round(_atr(highs, lows, closes), 5)
        rsi = round(_rsi(closes), 2)
        adx = round(_adx(highs, lows, closes), 2)
        stoch_k, stoch_d = _stoch(highs, lows, closes)
        macd_val, macd_sig, macd_hist = _macd(closes)
        ha = _heikin_ashi(opens, highs, lows, closes)

        price = closes[-1]
        vol = "EXTREME" if atr > price * 0.015 else "HIGH" if atr > price * 0.008 else "NORMAL" if atr > price * 0.003 else "LOW"

        return {
            "atr": atr,
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "ema20_above_50": ema20 > ema50,
            "ema50_above_200": ema50 > ema200,
            "price_above_ema200": price > ema200,
            "adx": adx,
            "adx_trending": adx > 25,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
            "stoch_oversold": stoch_k < 25,
            "stoch_overbought": stoch_k > 75,
            "macd": macd_val,
            "macd_signal": macd_sig,
            "macd_hist": macd_hist,
            "macd_bullish": macd_hist > 0,
            "ha_bull": ha["bull"],
            "ha_bear": ha["bear"],
            "ha_streak": ha["streak"],
            "volatility": vol,
        }

    def _empty(self) -> dict:
        return {
            "atr": 0.0, "rsi": 50.0, "ema20": 0.0, "ema50": 0.0, "ema200": 0.0,
            "ema20_above_50": False, "ema50_above_200": False, "price_above_ema200": False,
            "adx": 0.0, "adx_trending": False,
            "stoch_k": 50.0, "stoch_d": 50.0, "stoch_oversold": False, "stoch_overbought": False,
            "macd": 0.0, "macd_signal": 0.0, "macd_hist": 0.0, "macd_bullish": False,
            "ha_bull": False, "ha_bear": False, "ha_streak": 0, "volatility": "NORMAL",
        }
