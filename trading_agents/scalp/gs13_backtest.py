"""Fast vectorized backtest for GS13 (M3 Strength-Scalp), real-cost.

The generic harness in backtest.py recomputes EMA/RSI/ATR on a growing slice
every bar (O(n^2)) — fine for ~5k bars, hopeless for a 2-year, 28-pair gate.
This module precomputes each indicator as a rolling array ONCE per pair (O(n)),
so the full universe over years runs in minutes, on real spreads.

Entry logic mirrors trading_agents.strength.entry.m3_signal (EMA200 trend +
recent 9/15 cross + RSI band, bias from -7..+7 currency strength, ADR/ATR
momentum gate). Two documented simplifications vs the live agent:
  - ATR expansion = ATR14[i] >= 1.10 * SMA(ATR14, 50)[i]  (live uses ATR20 vs
    ATR60); same momentum intent, O(1) here.
  - ADR is derived causally from M3 day-groups (live uses real D1 bars).

Usage (run on the VPS where the bridge has history):
    python -m trading_agents.scalp.gs13_backtest --bars 120000
    python -m trading_agents.scalp.gs13_backtest --symbols EURUSD GBPUSD --bars 60000
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.scalp.indicators import _ema_arr, BD_TZ
from trading_agents.scalp.backtest import (
    _fetch_bars, _build_strength_history, _strength_at, TYPICAL_SPREADS, log,
)
from trading_agents.strength.strength import PAIRS28, MIN_DIFF
from trading_agents.strength.entry import (
    EMA_TREND, EMA_FAST, EMA_SLOW, RSI_BUY, RSI_SELL, SL_ATR, TP_RR,
    ADR_USED_MAX, ATR_EXPANSION, CROSS_WINDOW,
)
from trading_agents.iconic.correlation import split_pair

REPORT_FILE = BASE_DIR / "logs" / "scalp" / "_gs13_backtest.json"

ATR_SMA_N = 50


# ── Rolling indicator arrays (O(n)) ──────────────────────────────────────────

def _rsi_arr(closes: list[float], period: int = 14) -> list[float]:
    n = len(closes)
    out = [50.0] * n
    if n < period + 1:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    ag = sum(gains[1:period + 1]) / period
    al = sum(losses[1:period + 1]) / period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    for i in range(period):
        out[i] = out[period]
    return out


def _atr_arr(highs, lows, closes, period: int = 14) -> list[float]:
    n = len(closes)
    out = [0.0] * n
    if n < period + 1:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    a = sum(tr[1:period + 1]) / period
    out[period] = a
    for i in range(period + 1, n):
        a = (a * (period - 1) + tr[i]) / period
        out[i] = a
    for i in range(period):
        out[i] = out[period]
    return out


def _sma_arr(vals: list[float], n: int) -> list[float]:
    out = [0.0] * len(vals)
    run = 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= n:
            run -= vals[i - n]
        out[i] = run / min(i + 1, n)
    return out


def _adr_used_causal(times, highs, lows, period: int = 14) -> list[float]:
    """used[i] = today's range up to bar i / ADR(last `period` completed days).

    Strictly causal: ADR uses only days that closed before today; today's range
    accumulates as bars arrive. used >= 1 when ADR unknown (early bars).
    """
    n = len(times)
    used = [1.0] * n
    day_of = [None] * n
    # group day ranges as we sweep; track completed-day full ranges in order.
    completed = []          # list of (date, full_range)
    cur_date = None
    cur_hi = cur_lo = None
    adr_for_today = 0.0
    for i in range(n):
        d = datetime.fromtimestamp(int(times[i]), tz=BD_TZ).date()
        if d != cur_date:
            if cur_date is not None:
                completed.append(cur_hi - cur_lo)
            cur_date, cur_hi, cur_lo = d, highs[i], lows[i]
            if len(completed) >= period:
                adr_for_today = sum(completed[-period:]) / period
            else:
                adr_for_today = 0.0
        else:
            cur_hi = max(cur_hi, highs[i])
            cur_lo = min(cur_lo, lows[i])
        if adr_for_today > 0:
            used[i] = (cur_hi - cur_lo) / adr_for_today
    return used


# ── Per-pair fast backtest ───────────────────────────────────────────────────

def backtest_pair(symbol: str, bars: dict) -> dict:
    times = bars.get("time", [])
    closes = bars.get("close", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    n = len(times)
    if n < EMA_TREND + ATR_SMA_N + 5:
        return {"symbol": symbol, "trades": 0, "pf": 0.0, "wr": 0.0, "pnl": 0.0,
                "status": "insufficient_bars", "bars": n}

    base, quote = split_pair(symbol)
    spread = TYPICAL_SPREADS.get(symbol, 0.0002)

    e9 = _ema_arr(closes, EMA_FAST)
    e15 = _ema_arr(closes, EMA_SLOW)
    e200 = _ema_arr(closes, EMA_TREND)
    rsi = _rsi_arr(closes, 14)
    atr = _atr_arr(highs, lows, closes, 14)
    atr_sma = _sma_arr(atr, ATR_SMA_N)
    used = _adr_used_causal(times, highs, lows, 14)

    def crossed(i: int, direction: int) -> bool:
        for k in range(CROSS_WINDOW):
            j = i - k
            if j >= 1:
                prev = e9[j - 1] - e15[j - 1]
                cur = e9[j] - e15[j]
                if direction == 1 and prev < 0 and cur >= 0:
                    return True
                if direction == -1 and prev > 0 and cur <= 0:
                    return True
        return False

    trades = []
    pos = None
    start = EMA_TREND + ATR_SMA_N
    for i in range(start, n - 1):
        # manage open position on next bar
        if pos is not None:
            nh, nl = highs[i + 1], lows[i + 1]
            if pos["side"] == "BUY":
                if nl <= pos["sl"]:
                    trades.append(pos["sl"] - pos["entry"] - spread); pos = None
                elif nh >= pos["tp"]:
                    trades.append(pos["tp"] - pos["entry"] - spread); pos = None
            else:
                if nh >= pos["sl"]:
                    trades.append(pos["entry"] - pos["sl"] - spread); pos = None
                elif nl <= pos["tp"]:
                    trades.append(pos["entry"] - pos["tp"] - spread); pos = None
        if pos is not None:
            continue

        score = _strength_at(int(times[i]))
        diff = score.get(base, 0) - score.get(quote, 0)
        if abs(diff) < MIN_DIFF:
            continue
        bias = "BUY" if diff > 0 else "SELL"

        if used[i] > ADR_USED_MAX:
            continue
        if atr_sma[i] <= 0 or atr[i] < ATR_EXPANSION * atr_sma[i]:
            continue

        price = closes[i]
        a = atr[i]
        if a <= 0:
            continue
        if bias == "BUY":
            if not (price > e200[i] and crossed(i, 1) and RSI_BUY[0] <= rsi[i] <= RSI_BUY[1]):
                continue
            entry = closes[i + 1] + spread
            sl = entry - SL_ATR * a
            tp = entry + TP_RR * SL_ATR * a
            if sl >= entry or tp <= entry:
                continue
            pos = {"side": "BUY", "entry": entry, "sl": sl, "tp": tp}
        else:
            if not (price < e200[i] and crossed(i, -1) and RSI_SELL[0] <= rsi[i] <= RSI_SELL[1]):
                continue
            entry = closes[i + 1] - spread
            sl = entry + SL_ATR * a
            tp = entry - TP_RR * SL_ATR * a
            if sl <= entry or tp >= entry:
                continue
            pos = {"side": "SELL", "entry": entry, "sl": sl, "tp": tp}

    wins = [p for p in trades if p > 0]
    losses = [p for p in trades if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = round(gp / gl, 3) if gl > 0 else (99.0 if gp > 0 else 0.0)
    wr = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
    days = (times[-1] - times[0]) / 86400 if n > 1 else 0
    return {"symbol": symbol, "trades": len(trades), "pf": pf, "wr": wr,
            "pnl": round(sum(trades), 6), "bars": n, "days": round(days, 1)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Fast GS13 strength-scalp backtest")
    ap.add_argument("--bars", type=int, default=120000, help="M3 bars per pair")
    ap.add_argument("--symbols", nargs="+", default=None)
    args = ap.parse_args()

    symbols = args.symbols or list(PAIRS28)
    _build_strength_history()          # one-time 28-pair H1 strength sidecar

    results = []
    for sym in symbols:
        bars = _fetch_bars(sym, "M3", args.bars)
        if not bars or not bars.get("close"):
            log.error("no M3 bars for %s", sym)
            results.append({"symbol": sym, "trades": 0, "pf": 0.0, "status": "no_bars"})
            continue
        r = backtest_pair(sym, bars)
        results.append(r)
        log.info("  %-8s trades=%4d  PF=%.2f  WR=%.1f%%  pnl=%.5f  (%.0fd)",
                 sym, r.get("trades", 0), r.get("pf", 0), r.get("wr", 0),
                 r.get("pnl", 0), r.get("days", 0))

    # Portfolio aggregate (pool every trade's pnl is unit-inconsistent across
    # pairs, so aggregate PF is reported R-free as a rough cross-pair signal;
    # the per-pair PF table is the real gate).
    traded = [r for r in results if r.get("trades", 0) > 0]
    total_trades = sum(r["trades"] for r in traded)
    passing = [r for r in traded if r["pf"] >= 1.3]
    REPORT_FILE.write_text(json.dumps(results, indent=2))

    print("\n" + "=" * 64)
    print(f"{'Symbol':<10}{'Trades':>8}{'WR%':>7}{'PF':>7}{'Days':>7}")
    print("-" * 64)
    for r in sorted(traded, key=lambda x: x["pf"], reverse=True):
        mark = "  <<<" if r["pf"] >= 1.3 else ("  <" if r["pf"] >= 1.0 else "")
        print(f"{r['symbol']:<10}{r['trades']:>8}{r['wr']:>7.1f}{r['pf']:>7.2f}{r.get('days',0):>7.0f}{mark}")
    print("=" * 64)
    print(f"Pairs traded: {len(traded)} | total trades: {total_trades} | "
          f"pairs PF>=1.3: {len(passing)}/{len(traded)}")
    if passing:
        print("PASS:", ", ".join(f"{r['symbol']}({r['pf']})" for r in passing))
    print(f"Report: {REPORT_FILE}")


if __name__ == "__main__":
    main()
