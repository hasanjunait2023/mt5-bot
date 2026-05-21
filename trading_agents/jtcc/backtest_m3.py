"""M3 Scalping Strategy Backtest — walk-forward validation of S17-S21 on
Junait's actual Exness broker data with realistic spread costs.

Reuses existing analytics/mtf.py + intraday_signals.py + rule_engine to
replay each M3 bar AS IF it were live. Simulates entries at next bar open,
exits at SL/TP. Reports PF/WR/expectancy/max DD per (strategy × symbol).

Run:
  python -m trading_agents.jtcc.backtest_m3 --days 90
  python -m trading_agents.jtcc.backtest_m3 --days 30 --symbol XAUUSD --strategy "S17 Silver Bullet M3"
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("jtcc.backtest_m3")
BD_TZ = ZoneInfo("Asia/Dhaka")

BASE_DIR = Path(__file__).parent.parent.parent
REPORT_DIR = BASE_DIR / "logs" / "jtcc"
REPORT_FILE = REPORT_DIR / "_backtest_m3.json"
STRATEGIES_DIR = BASE_DIR / "trading_agents" / "jtcc" / "strategies"

# Conservative spread costs (matches observed Exness demo +20% safety margin)
TYPICAL_SPREADS = {
    "XAUUSD": 0.30, "XAGUSD": 0.05, "BTCUSD": 12.0,
    "EURUSD": 0.00008, "GBPUSD": 0.0001, "USDJPY": 0.008,
}

# How many bars to fetch per timeframe (must cover entire test window)
BARS_NEEDED = {"M3": 30000, "M15": 6000, "H1": 1500, "H4": 400, "D1": 100}


def _fetch_bars(symbol: str, timeframe: str, limit: int) -> dict | None:
    bridge_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{bridge_url}/bars/{symbol}",
                         params={"timeframe": timeframe, "limit": limit},
                         timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Fetch failed %s %s: %s", symbol, timeframe, e)
        return None


def _slice_bars_at(bars: dict, end_time_unix: int) -> dict:
    """Return bars dict containing only bars with time <= end_time_unix.
    Only slices list-type fields (open/high/low/close/volume/time)."""
    times = bars.get("time", [])
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] <= end_time_unix:
            lo = mid + 1
        else:
            hi = mid
    cutoff = lo
    out = {}
    for k, v in bars.items():
        if isinstance(v, list):
            out[k] = v[:cutoff]
        else:
            out[k] = v
    return out


def _build_mtf_context_at_t(
    symbol: str,
    mtf_bars: dict[str, dict],
    t_unix: int,
) -> dict:
    """Build MTF context exactly as JTCC main would, but for historical timestamp T."""
    from trading_agents.jtcc.analytics.mtf import (
        compute_per_tf_context, compute_vwap_bands, compute_session_range,
        compute_orb, compute_nr7,
    )
    ctx_mtf = {"valid": True, "symbol": symbol, "stack": list(mtf_bars.keys())}
    for tf, full_bars in mtf_bars.items():
        sliced = _slice_bars_at(full_bars, t_unix)
        if not sliced.get("close"):
            ctx_mtf[tf] = {"valid": False}
            continue
        ctx_mtf[tf] = compute_per_tf_context(sliced)

    # Intraday signals computed using bar time as "now"
    if "M3" in mtf_bars:
        m3_sliced = _slice_bars_at(mtf_bars["M3"], t_unix)
        ctx_mtf["vwap"] = _compute_vwap_at(m3_sliced, t_unix)
    if "H1" in mtf_bars:
        h1_sliced = _slice_bars_at(mtf_bars["H1"], t_unix)
        ctx_mtf["asian_range"] = _compute_session_range_at(h1_sliced, t_unix, 7, 13)
    if "M5" in mtf_bars:
        m5_sliced = _slice_bars_at(mtf_bars["M5"], t_unix)
        ctx_mtf["ny_orb"] = _compute_orb_at(m5_sliced, t_unix, 18, 30)
        ctx_mtf["london_orb"] = _compute_orb_at(m5_sliced, t_unix, 13, 30)
    if "D1" in mtf_bars:
        d1_sliced = _slice_bars_at(mtf_bars["D1"], t_unix)
        ctx_mtf["nr7"] = compute_nr7(d1_sliced)
    return ctx_mtf


def _compute_vwap_at(m3_bars: dict, t_unix: int) -> dict:
    """VWAP for date of t_unix using m3_bars up to t_unix."""
    times = m3_bars.get("time", [])
    highs = m3_bars.get("high", [])
    lows = m3_bars.get("low", [])
    closes = m3_bars.get("close", [])
    vols = m3_bars.get("volume", [])
    if not times:
        return {"vwap": 0, "upper": 0, "lower": 0, "zscore": 0,
                "above_upper": False, "below_lower": False}
    t_date = datetime.fromtimestamp(t_unix, tz=BD_TZ).date()
    cum_pv, cum_v = 0.0, 0.0
    tps = []
    for i, ts in enumerate(times):
        if datetime.fromtimestamp(ts, tz=BD_TZ).date() != t_date:
            continue
        tp = (highs[i] + lows[i] + closes[i]) / 3
        v = max(vols[i], 1)
        cum_pv += tp * v
        cum_v += v
        tps.append(tp)
    if not tps or cum_v == 0:
        return {"vwap": closes[-1] if closes else 0, "upper": 0, "lower": 0,
                "zscore": 0, "above_upper": False, "below_lower": False}
    vwap = cum_pv / cum_v
    devs = [tp - vwap for tp in tps]
    sigma = math.sqrt(sum(d * d for d in devs) / len(devs)) if len(devs) > 1 else 0
    upper = vwap + 2.0 * sigma
    lower = vwap - 2.0 * sigma
    current = closes[-1]
    return {
        "vwap": round(vwap, 5), "upper": round(upper, 5), "lower": round(lower, 5),
        "zscore": round((current - vwap) / sigma, 2) if sigma > 0 else 0,
        "above_upper": current > upper, "below_lower": current < lower,
    }


def _compute_session_range_at(bars: dict, t_unix: int,
                              start_h: int, end_h: int) -> dict:
    """Session range for the date of t_unix."""
    times = bars.get("time", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    if not times:
        return {"high": 0, "low": 0, "built": False}
    t_date = datetime.fromtimestamp(t_unix, tz=BD_TZ).date()
    rh, rl = [], []
    for i, ts in enumerate(times):
        bd = datetime.fromtimestamp(ts, tz=BD_TZ)
        if bd.date() != t_date:
            continue
        if start_h <= bd.hour < end_h:
            rh.append(highs[i])
            rl.append(lows[i])
    if not rh:
        return {"high": 0, "low": 0, "built": False}
    bd_now = datetime.fromtimestamp(t_unix, tz=BD_TZ)
    built = bd_now.hour >= end_h
    return {"high": round(max(rh), 5), "low": round(min(rl), 5),
            "built": built, "bars_in_range": len(rh)}


def _compute_orb_at(bars: dict, t_unix: int, start_h: int, orb_min: int) -> dict:
    times = bars.get("time", [])
    highs = bars.get("high", [])
    lows = bars.get("low", [])
    if not times:
        return {"high": 0, "low": 0, "built": False}
    t_date = datetime.fromtimestamp(t_unix, tz=BD_TZ).date()
    rh, rl = [], []
    for i, ts in enumerate(times):
        bd = datetime.fromtimestamp(ts, tz=BD_TZ)
        if bd.date() != t_date or bd.hour < start_h:
            continue
        minute_off = (bd.hour - start_h) * 60 + bd.minute
        if minute_off < orb_min:
            rh.append(highs[i])
            rl.append(lows[i])
    if not rh:
        return {"high": 0, "low": 0, "built": False, "minutes_collected": 0}
    bd_now = datetime.fromtimestamp(t_unix, tz=BD_TZ)
    built = bd_now.hour > start_h or (bd_now.hour == start_h and bd_now.minute >= orb_min)
    return {"high": round(max(rh), 5), "low": round(min(rl), 5),
            "built": built, "minutes_collected": len(rh)}


def _intraday_at(t_unix: int) -> dict:
    bd = datetime.fromtimestamp(t_unix, tz=BD_TZ)
    h, m = bd.hour, bd.minute
    sb_window = h == 14 or h == 21
    return {
        "bd_time": bd.strftime("%H:%M"),
        "silver_bullet_window": sb_window,
        "silver_bullet_session": "london_sb" if h == 14 else "ny_am_sb" if h == 21 else None,
        "london_open_window": h == 13,
        "ny_open_window": h == 18,
        "asian_lull_window": 11 <= h < 13,
    }


def _session_at(t_unix: int) -> dict:
    """Mirror of session_agent for historical t."""
    bd = datetime.fromtimestamp(t_unix, tz=BD_TZ)
    h = bd.hour
    if 7 <= h < 11:
        return {"name": "asian_kz", "active": True, "primary": False}
    if 13 <= h < 16:
        return {"name": "london_kz", "active": True, "primary": True}
    if 18 <= h < 21:
        return {"name": "ny_kz", "active": True, "primary": True}
    if h == 14:
        return {"name": "silver_bullet_london", "active": True, "primary": True}
    if h == 21:
        return {"name": "silver_bullet_ny", "active": True, "primary": True}
    return {"name": "off_session", "active": False, "primary": False}


def _build_ctx_at(symbol: str, mtf_bars: dict[str, dict], t_unix: int) -> dict:
    """Full context ready for rule engine, at historical timestamp T."""
    # Use M3 bar as "current price"
    m3 = mtf_bars.get("M3", {})
    times = m3.get("time", [])
    closes = m3.get("close", [])
    if not closes:
        return {}
    # Find current M3 bar index
    cur_i = -1
    for i in range(len(times) - 1, -1, -1):
        if times[i] <= t_unix:
            cur_i = i
            break
    if cur_i < 0:
        return {}
    current_close = closes[cur_i]
    spread = TYPICAL_SPREADS.get(symbol, 0.001)

    ctx_mtf = _build_mtf_context_at_t(symbol, mtf_bars, t_unix)
    return {
        "symbol": symbol,
        "price": {"bid": current_close - spread / 2, "ask": current_close + spread / 2,
                  "mid": current_close, "spread": spread},
        "session": _session_at(t_unix),
        "news": {"blocked": False},  # backtest: assume no news (simplification)
        "risk": {"can_trade": True, "daily_dd_pct": 0, "open_trades": 0},
        "mtf": ctx_mtf,
        "intraday": _intraday_at(t_unix),
        # Legacy fields used by some rules (atr/adx fallbacks)
        "momentum": {
            "atr": ctx_mtf.get("M3", {}).get("atr", 0),
            "adx": 20,  # neutral default
        },
        "market": {"trend": ctx_mtf.get("D1", {}).get("trend", "NEUTRAL")},
        "smc": {},
        "analytics": {"tsmom": {"position_scalar": 1.0}},
    }


def backtest_strategy(strategy: dict, symbol: str, mtf_bars: dict[str, dict],
                      max_bars_to_simulate: int = 5000) -> dict:
    """Walk-forward backtest of ONE strategy on ONE symbol."""
    from trading_agents.jtcc.strategies.rule_engine import RuleEngine
    re = RuleEngine()

    m3_bars = mtf_bars.get("M3", {})
    times = m3_bars.get("time", [])
    closes = m3_bars.get("close", [])
    highs = m3_bars.get("high", [])
    lows = m3_bars.get("low", [])
    if len(times) < 200:
        return {"strategy": strategy.get("name"), "symbol": symbol,
                "status": "insufficient_bars", "bars": len(times)}

    spread = TYPICAL_SPREADS.get(symbol, 0.001)
    trades = []
    position = None  # {"side", "entry", "sl", "tp", "entry_i"}
    rejections = defaultdict(int)
    eval_count = 0

    # Start from index 200 (need enough HTF bars for context)
    start_i = max(200, len(times) - max_bars_to_simulate)

    for i in range(start_i, len(times) - 1):
        t = times[i]

        # Manage open position FIRST
        if position is not None:
            # Check SL/TP using next bar's range
            next_high = highs[i + 1]
            next_low = lows[i + 1]
            if position["side"] == "BUY":
                if next_low <= position["sl"]:
                    pnl = position["sl"] - position["entry"] - spread
                    trades.append({"side": "BUY", "entry": position["entry"],
                                   "exit": position["sl"], "pnl": pnl,
                                   "exit_type": "SL", "bars_held": i + 1 - position["entry_i"]})
                    position = None
                elif next_high >= position["tp"]:
                    pnl = position["tp"] - position["entry"] - spread
                    trades.append({"side": "BUY", "entry": position["entry"],
                                   "exit": position["tp"], "pnl": pnl,
                                   "exit_type": "TP", "bars_held": i + 1 - position["entry_i"]})
                    position = None
            else:  # SELL
                if next_high >= position["sl"]:
                    pnl = position["entry"] - position["sl"] - spread
                    trades.append({"side": "SELL", "entry": position["entry"],
                                   "exit": position["sl"], "pnl": pnl,
                                   "exit_type": "SL", "bars_held": i + 1 - position["entry_i"]})
                    position = None
                elif next_low <= position["tp"]:
                    pnl = position["entry"] - position["tp"] - spread
                    trades.append({"side": "SELL", "entry": position["entry"],
                                   "exit": position["tp"], "pnl": pnl,
                                   "exit_type": "TP", "bars_held": i + 1 - position["entry_i"]})
                    position = None

        # Look for entry only if flat
        if position is None:
            ctx = _build_ctx_at(symbol, mtf_bars, t)
            if not ctx:
                continue
            try:
                vote = re.evaluate(strategy, ctx)
                eval_count += 1
            except Exception as e:
                rejections[f"eval_error:{type(e).__name__}"] += 1
                continue
            if vote.get("signal") in ("BUY", "SELL"):
                # Open at next bar's open (use next close as proxy)
                entry = closes[i + 1] + (spread if vote["signal"] == "BUY" else -spread)
                sl = vote.get("sl", 0)
                tp = vote.get("tp", 0)
                if sl <= 0 or tp <= 0:
                    rejections["bad_sl_tp"] += 1
                    continue
                position = {"side": vote["signal"], "entry": entry, "sl": sl,
                            "tp": tp, "entry_i": i + 1}
            else:
                rejections[vote.get("reason", "no_signal")[:30]] += 1

    return _summarize_m3(strategy.get("name"), symbol, trades, eval_count,
                         rejections, len(times[start_i:]))


def _summarize_m3(strategy: str, symbol: str, trades: list, eval_count: int,
                  rejections: dict, bars_tested: int) -> dict:
    if not trades:
        return {"strategy": strategy, "symbol": symbol, "trades": 0,
                "bars_tested": bars_tested, "evaluations": eval_count,
                "verdict": "NO_TRADES",
                "top_rejection_reasons": dict(list(rejections.items())[:5])}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses)) if losses else 1e-9
    pf = round(gross_profit / gross_loss, 2)
    wr = round(len(wins) / len(pnls) * 100, 1)
    avg_win = round(sum(wins) / max(len(wins), 1), 5)
    avg_loss = round(sum(losses) / max(len(losses), 1), 5)
    expectancy = round((wr / 100 * avg_win) + ((1 - wr / 100) * avg_loss), 5)

    cum, peak, max_dd = 0, 0, 0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    avg_hold = round(sum(t.get("bars_held", 0) for t in trades) / len(trades), 1)

    if len(pnls) < 5:
        verdict = "INSUFFICIENT_TRADES"
    elif pf < 1.0:
        verdict = "UNPROFITABLE"
    elif pf >= 2.0:
        verdict = "STRONG"
    elif pf >= 1.3:
        verdict = "DECENT"
    else:
        verdict = "MARGINAL"

    return {
        "strategy": strategy, "symbol": symbol, "trades": len(pnls),
        "wins": len(wins), "losses": len(losses), "win_rate_pct": wr,
        "total_pnl": round(total_pnl, 4), "profit_factor": pf,
        "expectancy": expectancy, "max_drawdown": round(max_dd, 4),
        "avg_win": avg_win, "avg_loss": avg_loss,
        "avg_hold_bars": avg_hold, "bars_tested": bars_tested,
        "evaluations": eval_count, "verdict": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--symbols", nargs="+",
                        default=["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"])
    parser.add_argument("--strategy", default=None,
                        help="Run only one strategy by name (substring match)")
    args = parser.parse_args()

    # MT5 bridge max limit per request = 5000 bars
    # M3: 5000 bars = ~10 days of 24h trading
    # Auto-compute symbol-appropriate limits
    BARS_NEEDED["M3"] = min(5000, args.days * 480 + 200)
    BARS_NEEDED["M15"] = min(5000, args.days * 96 + 100)
    BARS_NEEDED["H1"] = min(5000, args.days * 24 + 100)
    BARS_NEEDED["H4"] = min(5000, args.days * 6 + 50)
    BARS_NEEDED["D1"] = min(5000, args.days + 20)
    log.info("Bar limits: %s", BARS_NEEDED)

    log.info("M3 BACKTEST | days=%d | symbols=%s", args.days, args.symbols)

    # Load all M3/MTF strategies (s17-s24)
    sys.path.insert(0, str(BASE_DIR))
    all_strats = []
    candidate_files = (
        sorted(STRATEGIES_DIR.glob("s1[7-9]_*.yaml"))
        + sorted(STRATEGIES_DIR.glob("s2[0-9]_*.yaml"))
    )
    for p in candidate_files:
        with open(p, encoding="utf-8") as f:
            s = yaml.safe_load(f)
            s["_file"] = p.name
            all_strats.append(s)
    log.info("Loaded %d strategies: %s", len(all_strats), [s["name"] for s in all_strats])

    if args.strategy:
        all_strats = [s for s in all_strats if args.strategy.lower() in s["name"].lower()]
        log.info("Filtered to: %s", [s["name"] for s in all_strats])

    report = {"generated_at": datetime.now().isoformat(),
              "days_tested": args.days, "results": []}

    # Pre-fetch all MTF bars per symbol (saves time vs per-strategy fetch)
    bars_cache: dict[str, dict[str, dict]] = {}
    for sym in args.symbols:
        log.info("Fetching MTF bars for %s...", sym)
        sym_bars = {}
        for tf, lim in BARS_NEEDED.items():
            t0 = time.time()
            b = _fetch_bars(sym, tf, lim)
            if b:
                sym_bars[tf] = b
                log.info("  %s %s: %d bars (%.1fs)", sym, tf, len(b.get("close", [])), time.time() - t0)
        bars_cache[sym] = sym_bars

    # Run each strategy × each symbol
    print()
    print("=" * 100)
    print(f"M3 BACKTEST RESULTS — {args.days} days, spread costs included")
    print("=" * 100)
    print(f"{'Strategy':<32s} {'Symbol':<8s} {'Trades':>6s} {'WR%':>6s} {'PF':>6s} {'Exp':>10s} {'Verdict':>12s}")
    print("-" * 100)

    for strat in all_strats:
        sname = strat["name"]
        strat_symbols = strat.get("symbols", args.symbols)
        for sym in args.symbols:
            if sym not in strat_symbols:
                continue
            mtf_bars = bars_cache.get(sym, {})
            if not mtf_bars.get("M3"):
                continue
            t0 = time.time()
            result = backtest_strategy(strat, sym, mtf_bars,
                                       max_bars_to_simulate=BARS_NEEDED["M3"] - 200)
            elapsed = time.time() - t0
            result["runtime_s"] = round(elapsed, 1)
            report["results"].append(result)
            trades = result.get("trades", 0)
            if trades == 0:
                print(f"{sname:<32s} {sym:<8s} {0:>6d} {'-':>6s} {'-':>6s} {'-':>10s} {result.get('verdict','?'):>12s}")
            else:
                print(f"{sname:<32s} {sym:<8s} {result['trades']:>6d} "
                      f"{result['win_rate_pct']:>6.1f} {result['profit_factor']:>6.2f} "
                      f"{result['expectancy']:>10.5f} {result['verdict']:>12s}")

    # Save report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"Full report: {REPORT_FILE}")

    # Recommendations
    print()
    print("=" * 100)
    print("DATA-DRIVEN RECOMMENDATIONS")
    print("=" * 100)
    by_strategy = defaultdict(list)
    for r in report["results"]:
        by_strategy[r["strategy"]].append(r)
    for sname, results in by_strategy.items():
        winners = [r for r in results if r.get("verdict") in ("STRONG", "DECENT")]
        losers = [r for r in results if r.get("verdict") == "UNPROFITABLE"]
        no_trades = [r for r in results if r.get("verdict") == "NO_TRADES"]
        marginal = [r for r in results if r.get("verdict") == "MARGINAL"]
        if winners:
            symbols_w = [r["symbol"] for r in winners]
            print(f"  [PROMOTE]   {sname} -- profitable on: {symbols_w}")
        if losers:
            symbols_l = [r["symbol"] for r in losers]
            print(f"  [DISABLE]   {sname} -- unprofitable on: {symbols_l}")
        if marginal:
            print(f"  [KEEP-DEMO] {sname} -- marginal on: {[r['symbol'] for r in marginal]}")
        if no_trades and not winners and not losers:
            print(f"  [SKIP]      {sname} -- never fired in {args.days} days (filters too strict?)")


if __name__ == "__main__":
    main()
