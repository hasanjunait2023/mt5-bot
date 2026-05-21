"""Generic JTCC Strategy Backtest — walk-forward on ANY timeframe.

Reads strategy YAML's `timeframe` field, fetches the right bars + MTF context,
walks forward, evaluates rule engine, simulates trades with spread costs.

Tests every strategy in strategies/ (excluding _quarantine) and reports PF/WR/DD.

Run:
  python -m trading_agents.jtcc.backtest_jtcc                  # all strategies, all symbols
  python -m trading_agents.jtcc.backtest_jtcc --strategy "Elite J"
  python -m trading_agents.jtcc.backtest_jtcc --skip-validated  # skip already-validated ones
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("jtcc.backtest_generic")

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
STRATEGIES_DIR = BASE_DIR / "trading_agents" / "jtcc" / "strategies"
REPORT_FILE = BASE_DIR / "logs" / "jtcc" / "_backtest_jtcc_full.json"

TYPICAL_SPREADS = {
    "XAUUSD": 0.30, "XAGUSD": 0.05, "BTCUSD": 12.0,
    "EURUSD": 0.00008, "GBPUSD": 0.0001, "USDJPY": 0.008,
    "EURJPY": 0.012, "GBPJPY": 0.015, "GBPAUD": 0.00015,
    "AUDNZD": 0.00010, "USDCAD": 0.00012, "AUDCHF": 0.00010,
    "NZDUSD": 0.00010, "AUDUSD": 0.00010,
}

# All MTF timeframes to fetch alongside the execution TF
MTF_STACK = ["D1", "H4", "H1", "M15", "M5", "M3"]


def _fetch_bars(symbol: str, timeframe: str, limit: int = 5000) -> dict | None:
    bridge_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{bridge_url}/bars/{symbol}",
                         params={"timeframe": timeframe, "limit": limit}, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("Fetch %s %s FAILED: %s", symbol, timeframe, e)
        return None


def _slice_at(bars: dict, t_unix: int) -> dict:
    """Return only bars with time <= t_unix."""
    times = bars.get("time", [])
    lo, hi = 0, len(times)
    while lo < hi:
        m = (lo + hi) // 2
        if times[m] <= t_unix:
            lo = m + 1
        else:
            hi = m
    out = {}
    for k, v in bars.items():
        if isinstance(v, list):
            out[k] = v[:lo]
        else:
            out[k] = v
    return out


def _session_at(t_unix: int) -> dict:
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    bd = dt.fromtimestamp(t_unix, tz=ZoneInfo("Asia/Dhaka"))
    h = bd.hour
    if 7 <= h < 11:
        return {"name": "asian_kz", "active": True, "primary": False}
    if 13 <= h < 16 or h == 14:
        return {"name": "london_kz", "active": True, "primary": True}
    if 18 <= h < 21 or h == 21:
        return {"name": "ny_kz", "active": True, "primary": True}
    return {"name": "off_session", "active": False, "primary": False}


def _compute_real_momentum(sliced_exec_bars: dict) -> dict:
    """Compute real HA/Stoch/MACD/RSI/ADX SYNCHRONOUSLY on a 250-bar window.
    Reuses momentum_agent module functions directly (no asyncio, no full-array
    recompute) — fixes the O(n^2) + event-loop-per-bar performance crash."""
    from trading_agents.jtcc.agents import momentum_agent as ma
    # Window to last 250 bars — all indicators need <=200 bars
    o = sliced_exec_bars.get("open", [])[-250:]
    h = sliced_exec_bars.get("high", [])[-250:]
    l = sliced_exec_bars.get("low", [])[-250:]
    c = sliced_exec_bars.get("close", [])[-250:]
    if len(c) < 26:
        return {"atr": 0.001, "rsi": 50.0, "adx": 0.0, "adx_trending": False,
                "ha_bull": False, "ha_bear": False, "ha_streak": 0,
                "macd_bullish": False, "stoch_oversold": False, "stoch_overbought": False,
                "ema20_above_50": False, "ema50_above_200": False, "price_above_ema200": False,
                "volatility": "NORMAL"}
    try:
        ema20 = ma._ema(c, 20)[-1]
        ema50 = ma._ema(c, 50)[-1] if len(c) >= 50 else ema20
        ema200 = ma._ema(c, 200)[-1] if len(c) >= 200 else ma._ema(c, len(c) // 2)[-1]
        atr = ma._atr(h, l, c)
        rsi = ma._rsi(c)
        adx = ma._adx(h, l, c)
        stoch_k, stoch_d = ma._stoch(h, l, c)
        macd_val, macd_sig, macd_hist = ma._macd(c)
        ha = ma._heikin_ashi(o, h, l, c)
        price = c[-1]
        return {
            "atr": atr, "rsi": rsi, "adx": adx, "adx_trending": adx > 25,
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "ema20_above_50": ema20 > ema50,
            "ema50_above_200": ema50 > ema200,
            "price_above_ema200": price > ema200,
            "stoch_k": stoch_k, "stoch_d": stoch_d,
            "stoch_oversold": stoch_k < 25, "stoch_overbought": stoch_k > 75,
            "macd": macd_val, "macd_signal": macd_sig, "macd_hist": macd_hist,
            "macd_bullish": macd_hist > 0,
            "ha_bull": ha["bull"], "ha_bear": ha["bear"], "ha_streak": ha["streak"],
            "volatility": "NORMAL",
        }
    except Exception:
        return {"atr": 0.001, "rsi": 50.0, "adx": 0.0, "adx_trending": False,
                "ha_bull": False, "ha_bear": False, "ha_streak": 0,
                "macd_bullish": False, "stoch_oversold": False, "stoch_overbought": False,
                "ema20_above_50": False, "ema50_above_200": False, "price_above_ema200": False,
                "volatility": "NORMAL"}


def _build_ctx(symbol: str, mtf_bars: dict, t_unix: int, exec_tf: str) -> dict:
    """Generic context builder. Works for any execution timeframe."""
    from trading_agents.jtcc.analytics.mtf import compute_per_tf_context

    exec_bars = mtf_bars.get(exec_tf, {})
    times = exec_bars.get("time", [])
    closes = exec_bars.get("close", [])
    if not closes:
        return {}
    # Find current bar index
    cur_i = -1
    for i in range(len(times) - 1, -1, -1):
        if times[i] <= t_unix:
            cur_i = i
            break
    if cur_i < 0:
        return {}
    current = closes[cur_i]
    spread = TYPICAL_SPREADS.get(symbol, 0.001)

    # Build mtf context using sliced bars per TF (capped to last 300 for speed)
    ctx_mtf: dict = {"valid": True, "symbol": symbol}
    sliced_exec = None
    for tf in MTF_STACK:
        if tf in mtf_bars:
            sliced = _slice_at(mtf_bars[tf], t_unix)
            if sliced.get("close"):
                # Cap to last 300 bars — indicators need <=200
                capped = {k: (v[-300:] if isinstance(v, list) else v)
                          for k, v in sliced.items()}
                ctx_mtf[tf] = compute_per_tf_context(capped)
                if tf == exec_tf:
                    sliced_exec = capped

    # Compute REAL momentum on execution-TF bars (fix for hardcoded bug)
    if sliced_exec and len(sliced_exec.get("close", [])) >= 26:
        momentum = _compute_real_momentum(sliced_exec)
    else:
        exec_tf_data = ctx_mtf.get(exec_tf, {})
        momentum = {
            "atr": exec_tf_data.get("atr", 0.001),
            "rsi": 50.0, "adx": 0.0, "adx_trending": False,
            "ema20_above_50": False, "ema50_above_200": False, "price_above_ema200": False,
            "ha_bull": False, "ha_bear": False, "ha_streak": 0,
            "macd_bullish": False, "stoch_oversold": False, "stoch_overbought": False,
            "volatility": "NORMAL",
        }
    exec_tf_data = ctx_mtf.get(exec_tf, {})
    market = {
        "trend": exec_tf_data.get("trend", "NEUTRAL"),
        "bos": exec_tf_data.get("bos", False),
        "mss": exec_tf_data.get("mss", False),
        "choch": False,
        "structure": "UNDEFINED",
    }
    smc = {
        "sweep_detected": exec_tf_data.get("sweep_detected", False),
        "sweep_type": exec_tf_data.get("sweep_type"),
        "in_ote": exec_tf_data.get("in_ote", False),
        "in_discount": exec_tf_data.get("in_discount", False),
        "in_premium": exec_tf_data.get("in_premium", False),
        "bull_fvg_count": exec_tf_data.get("bull_fvg_count", 0),
        "bear_fvg_count": exec_tf_data.get("bear_fvg_count", 0),
    }
    return {
        "symbol": symbol,
        "price": {"bid": current - spread / 2, "ask": current + spread / 2,
                  "mid": current, "spread": spread},
        "session": _session_at(t_unix),
        "news": {"blocked": False},
        "risk": {"can_trade": True, "daily_dd_pct": 0, "open_trades": 0},
        "momentum": momentum,
        "market": market,
        "smc": smc,
        "mtf": ctx_mtf,
        "intraday": {"silver_bullet_window": False, "london_open_window": False,
                     "ny_open_window": False, "asian_lull_window": False,
                     "bd_time": ""},
        "analytics": {"tsmom": {"position_scalar": 1.0, "bullish": False,
                                 "bearish": False, "lookback_return": 0.0}},
    }


def backtest_one(strategy: dict, symbol: str, mtf_bars: dict, max_bars: int = 3000) -> dict:
    from trading_agents.jtcc.strategies.rule_engine import RuleEngine
    re = RuleEngine()

    exec_tf = strategy.get("timeframe", "D1")
    exec_bars = mtf_bars.get(exec_tf, {})
    times = exec_bars.get("time", [])
    closes = exec_bars.get("close", [])
    highs = exec_bars.get("high", [])
    lows = exec_bars.get("low", [])
    if len(times) < 200:
        return {"strategy": strategy.get("name"), "symbol": symbol, "timeframe": exec_tf,
                "status": "insufficient_bars", "bars": len(times)}

    spread = TYPICAL_SPREADS.get(symbol, 0.001)
    trades = []
    position = None
    start_i = max(200, len(times) - max_bars)

    for i in range(start_i, len(times) - 1):
        t = times[i]
        # Manage open position with NEXT bar's range
        if position:
            nh, nl = highs[i + 1], lows[i + 1]
            if position["side"] == "BUY":
                if nl <= position["sl"]:
                    pnl = position["sl"] - position["entry"] - spread
                    trades.append({"pnl": pnl, "exit": "SL", "bars_held": i + 1 - position["i"]})
                    position = None
                elif nh >= position["tp"]:
                    pnl = position["tp"] - position["entry"] - spread
                    trades.append({"pnl": pnl, "exit": "TP", "bars_held": i + 1 - position["i"]})
                    position = None
            else:
                if nh >= position["sl"]:
                    pnl = position["entry"] - position["sl"] - spread
                    trades.append({"pnl": pnl, "exit": "SL", "bars_held": i + 1 - position["i"]})
                    position = None
                elif nl <= position["tp"]:
                    pnl = position["entry"] - position["tp"] - spread
                    trades.append({"pnl": pnl, "exit": "TP", "bars_held": i + 1 - position["i"]})
                    position = None

        # Look for new entry only if flat
        if position is None:
            ctx = _build_ctx(symbol, mtf_bars, t, exec_tf)
            if not ctx:
                continue
            try:
                vote = re.evaluate(strategy, ctx)
            except Exception:
                continue
            if vote.get("signal") in ("BUY", "SELL"):
                entry = closes[i + 1] + (spread if vote["signal"] == "BUY" else -spread)
                sl = vote.get("sl", 0)
                tp = vote.get("tp", 0)
                if sl > 0 and tp > 0:
                    position = {"side": vote["signal"], "entry": entry, "sl": sl,
                                "tp": tp, "i": i + 1}

    return _summarize(strategy.get("name"), symbol, exec_tf, trades, len(times[start_i:]))


def _summarize(strategy: str, symbol: str, tf: str, trades: list, bars_tested: int) -> dict:
    if not trades:
        return {"strategy": strategy, "symbol": symbol, "timeframe": tf,
                "trades": 0, "bars_tested": bars_tested, "verdict": "NO_TRADES"}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses)) if losses else 1e-9
    pf = round(gp / gl, 2)
    wr = round(len(wins) / len(pnls) * 100, 1)
    cum, peak, mdd = 0, 0, 0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    if len(pnls) < 5:
        verdict = "INSUFFICIENT"
    elif pf < 1.0:
        verdict = "UNPROFITABLE"
    elif pf >= 2.0:
        verdict = "STRONG"
    elif pf >= 1.3:
        verdict = "DECENT"
    else:
        verdict = "MARGINAL"
    return {
        "strategy": strategy, "symbol": symbol, "timeframe": tf,
        "trades": len(pnls), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": wr, "profit_factor": pf,
        "total_pnl": round(sum(pnls), 4), "max_drawdown": round(mdd, 4),
        "avg_hold_bars": round(sum(t.get("bars_held", 0) for t in trades) / len(trades), 1),
        "bars_tested": bars_tested, "verdict": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default=None, help="Filter by name substring")
    parser.add_argument("--skip-validated", action="store_true",
                        help="Skip strategies that already have a 'backtest' field in YAML")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Override symbols (else use strategy's declared symbols)")
    args = parser.parse_args()

    # Load all non-quarantined strategies
    strats = []
    for p in sorted(STRATEGIES_DIR.glob("s*.yaml")):
        if "STRATEGY_TEMPLATE" in p.name:
            continue
        with open(p, encoding="utf-8") as f:
            s = yaml.safe_load(f)
            s["_file"] = p.name
            if args.strategy and args.strategy.lower() not in s["name"].lower():
                continue
            if args.skip_validated and "backtest" in s:
                continue
            strats.append(s)
    log.info("Strategies to test: %d", len(strats))
    for s in strats:
        log.info("  - %s (%s, %s)", s["name"], s.get("timeframe", "?"), s.get("symbols", []))

    # Collect all unique symbols
    all_symbols = set()
    for s in strats:
        all_symbols.update(args.symbols or s.get("symbols", []))
    all_symbols = sorted(all_symbols)

    # Pre-fetch MTF bars per symbol (~10s per symbol)
    bars_cache = {}
    for sym in all_symbols:
        log.info("Fetching MTF bars for %s...", sym)
        bars_cache[sym] = {}
        for tf in MTF_STACK:
            limit = 5000
            b = _fetch_bars(sym, tf, limit)
            if b:
                bars_cache[sym][tf] = b
                log.info("  %s %s: %d bars", sym, tf, len(b.get("close", [])))

    # Run backtest per (strategy × symbol)
    report = {"generated_at": datetime.now().isoformat(),
              "strategies_tested": len(strats), "results": []}
    print()
    print("=" * 110)
    print(f"{'Strategy':<35s} {'Symbol':<8s} {'TF':<4s} {'Trades':>7s} {'WR%':>6s} {'PF':>6s} {'MaxDD':>10s} {'Verdict':>14s}")
    print("-" * 110)
    for strat in strats:
        sname = strat["name"]
        syms = args.symbols or strat.get("symbols", [])
        for sym in syms:
            if sym not in bars_cache or not bars_cache[sym].get(strat.get("timeframe", "D1")):
                continue
            t0 = time.time()
            result = backtest_one(strat, sym, bars_cache[sym])
            result["runtime_s"] = round(time.time() - t0, 1)
            report["results"].append(result)
            tr = result.get("trades", 0)
            if tr == 0:
                print(f"{sname:<35s} {sym:<8s} {result.get('timeframe','?'):<4s} "
                      f"{0:>7d} {'-':>6s} {'-':>6s} {'-':>10s} {result.get('verdict','?'):>14s}")
            else:
                print(f"{sname:<35s} {sym:<8s} {result['timeframe']:<4s} "
                      f"{result['trades']:>7d} {result['win_rate_pct']:>6.1f} "
                      f"{result['profit_factor']:>6.2f} {result['max_drawdown']:>10.4f} "
                      f"{result['verdict']:>14s}")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"Full report: {REPORT_FILE}")

    # Recommendations
    print()
    print("=" * 110)
    print("DATA-DRIVEN RECOMMENDATIONS")
    print("=" * 110)
    by_strategy = defaultdict(list)
    for r in report["results"]:
        by_strategy[r["strategy"]].append(r)
    for sname, results in by_strategy.items():
        winners = [r for r in results if r.get("verdict") in ("STRONG", "DECENT")]
        marginal = [r for r in results if r.get("verdict") == "MARGINAL"]
        losers = [r for r in results if r.get("verdict") == "UNPROFITABLE"]
        no_trades = [r for r in results if r.get("verdict") == "NO_TRADES"]
        if winners:
            print(f"  [PROMOTE]   {sname:<35s} -- profitable on: {[r['symbol'] for r in winners]}")
        if marginal:
            print(f"  [KEEP-DEMO] {sname:<35s} -- marginal on: {[r['symbol'] for r in marginal]}")
        if losers:
            print(f"  [DISABLE]   {sname:<35s} -- unprofitable on: {[r['symbol'] for r in losers]}")
        if no_trades and not winners and not marginal and not losers:
            print(f"  [SKIP]      {sname:<35s} -- never fired (filters too strict)")


if __name__ == "__main__":
    main()
