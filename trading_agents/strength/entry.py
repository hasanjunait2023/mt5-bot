"""M3 EMA 200/9/15 + RSI entry logic + momentum filters (pure, shared).

Lives in its own module so the live agent
(:mod:`trading_agents.scalp.m3strength_agent`) and the backtest strategy
(``GS13`` in :mod:`trading_agents.scalp.backtest`) call the IDENTICAL entry math
without a circular import (the agent imports the backtest, so the shared core
cannot live there).

All functions take COMPLETE-bar series — the caller must drop the still-forming
last bar before calling.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from trading_agents.scalp.indicators import ema, ema_cross, rsi, atr, BD_TZ

# Entry / risk defaults (overridable by the agent).
EMA_TREND = 200
EMA_FAST = 9
EMA_SLOW = 15
RSI_BUY = (50.0, 70.0)    # momentum, not overbought
RSI_SELL = (30.0, 50.0)
SL_ATR = 1.5              # stop distance = SL_ATR * ATR(14)
TP_RR = 1.5               # take profit = TP_RR * stop distance
ATR_FAST_N = 20
ATR_SLOW_N = 60
ATR_EXPANSION = 1.10      # recent ATR must exceed baseline by this ratio
ADR_USED_MAX = 0.70       # skip if today's range already covered > 70% of ADR


def atr_expansion_ok(highs: list[float], lows: list[float], closes: list[float],
                     fast_n: int = ATR_FAST_N, slow_n: int = ATR_SLOW_N,
                     ratio: float = ATR_EXPANSION) -> bool:
    """True when recent ATR is expanding vs its longer baseline (momentum)."""
    if len(closes) < slow_n:
        return False
    atr_fast = atr(highs[-fast_n:], lows[-fast_n:], closes[-fast_n:], 14)
    atr_slow = atr(highs[-slow_n:], lows[-slow_n:], closes[-slow_n:], 14)
    if atr_slow <= 0:
        return False
    return atr_fast >= ratio * atr_slow


def adr_from_m3(times: list, highs: list[float], lows: list[float],
                period: int = 14) -> tuple[float, float]:
    """Derive (ADR, today_used_fraction) from M3 bars grouped by BD calendar day.

    Used by the backtest where real D1 bars aren't threaded through the
    single-symbol harness. Live trading uses real D1 bars via indicators.adr.
    """
    days: dict = {}
    order: list = []
    for t, h, l in zip(times, highs, lows):
        d = datetime.fromtimestamp(int(t), tz=BD_TZ).date()
        if d not in days:
            days[d] = [h, l]
            order.append(d)
        else:
            days[d][0] = max(days[d][0], h)
            days[d][1] = min(days[d][1], l)
    if len(order) < period + 1:
        return 0.0, 1.0
    completed = order[:-1]                      # exclude the forming day
    last = completed[-period:]
    rngs = [days[d][0] - days[d][1] for d in last]
    adr_val = sum(rngs) / len(rngs) if rngs else 0.0
    today = order[-1]
    today_rng = days[today][0] - days[today][1]
    used = today_rng / adr_val if adr_val > 0 else 1.0
    return adr_val, used


CROSS_WINDOW = 2   # accept a fresh 9/15 cross within the last N completed bars


def _crossed(closes: list[float], direction: int, window: int = CROSS_WINDOW) -> bool:
    """True if a 9/15 EMA cross in `direction` (+1/-1) occurred in the last
    `window` completed bars — looser than an exact same-bar cross so the scalper
    isn't starved, while still requiring a recent momentum flip."""
    for k in range(window):
        sl = closes if k == 0 else closes[:-k]
        if len(sl) >= EMA_SLOW + 2 and ema_cross(sl, EMA_FAST, EMA_SLOW) == direction:
            return True
    return False


def m3_signal(highs: list[float], lows: list[float], closes: list[float],
              bias: str, *, sl_atr: float = SL_ATR, tp_rr: float = TP_RR
              ) -> Optional[dict]:
    """EMA200 trend + recent EMA9/15 cross + RSI band, bias-aligned. ATR SL/TP.

    `bias` is "BUY" or "SELL" from the strength layer; the setup must agree with
    it. Returns {signal, entry, sl, tp, atr} or None.
    """
    if len(closes) < EMA_TREND + 2:
        return None
    price = closes[-1]
    e200 = ema(closes, EMA_TREND)
    r = rsi(closes, 14)
    a = atr(highs, lows, closes, 14)
    if a <= 0:
        return None

    if bias == "BUY":
        if not (price > e200 and _crossed(closes, 1) and RSI_BUY[0] <= r <= RSI_BUY[1]):
            return None
        sl = price - sl_atr * a
        tp = price + tp_rr * (sl_atr * a)
    elif bias == "SELL":
        if not (price < e200 and _crossed(closes, -1) and RSI_SELL[0] <= r <= RSI_SELL[1]):
            return None
        sl = price + sl_atr * a
        tp = price - tp_rr * (sl_atr * a)
    else:
        return None

    return {"signal": bias, "entry": price, "sl": sl, "tp": tp, "atr": a}
