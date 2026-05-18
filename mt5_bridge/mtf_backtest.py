# encoding: utf-8
"""
mtf_backtest.py — Multi-symbol MTF EMA Alignment Scalper backtest.

Usage:
  python mtf_backtest.py                          # all 30 symbols, 3 months
  python mtf_backtest.py --symbols EURUSD GBPUSD  # specific symbols
  python mtf_backtest.py --months 1 --no-news     # faster run
  python mtf_backtest.py --strength               # enable currency strength filter
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import argparse
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional

import MetaTrader5 as mt5

sys.path.insert(0, ".")
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import (MTF_SYMBOLS, MTF_SYMBOL_CONFIG, MTF_DEFAULT_PARAMS,
                    MTF_DEFAULT_FILTERS, MAJOR_CURRENCIES,
                    MTF_SYMBOL_PARAMS, MTF_SYMBOL_FILTERS)
from mtf_strategy import (
    fetch_mtf_data, align_mtf_to_m1, compute_mtf_signals,
    compute_currency_strength, compute_sl_tp_arrays,
    _swing_low_series, _swing_high_series,
)


# ── Trade simulator ───────────────────────────────────────────────────────────

def simulate_mtf_trades(
    df: pd.DataFrame,
    signals: pd.Series,
    p: dict,
    pip_size: float,
    spread_cost: float = 0.0,
) -> pd.DataFrame:
    """
    Simulate MTF strategy trades with swing-based SL/TP.
    Next-bar open entry (no look-ahead).
    Compound risk sizing: risk_usd = balance × RiskPct / 100.
    """
    bal      = p["InitialBalance"]
    peak     = bal
    rr       = p["RR_Ratio"]
    risk_pct = p["RiskPct"] / 100.0
    max_dd   = p["MaxDDPct"] / 100.0
    lk       = p["SL_Lookback"]
    buf      = p["SL_Buffer_ATR"]
    max_td   = p["MaxTradesDay"]

    ha    = df["High"].values
    la    = df["Low"].values
    oa    = df["Open"].values
    ca    = df["Close"].values
    atr   = df["atr14"].values
    sa    = signals.values
    times = df.index

    sw_lo = _swing_low_series(df["Low"],   lk).values
    sw_hi = _swing_high_series(df["High"], lk).values

    trades  = []
    ot      = None
    daily   = {}
    dpnl    = {}
    day_bal = {}

    for i in range(1, len(ha) - 1):
        if peak > 0 and (peak - bal) / peak > max_dd:
            break

        h   = float(ha[i])
        l   = float(la[i])
        day = times[i].date()

        if day not in day_bal:
            day_bal[day] = bal

        # ── Manage open trade ──────────────────────────────────────────────
        if ot is not None:
            res = None
            pnl = 0.0
            if ot["d"] == 1:
                if l <= ot["sl"]:
                    pnl = -ot["r"] - spread_cost
                    res = "SL"
                elif h >= ot["tp"]:
                    pnl = ot["rw"] - spread_cost
                    res = "TP"
            else:
                if h >= ot["sl"]:
                    pnl = -ot["r"] - spread_cost
                    res = "SL"
                elif l <= ot["tp"]:
                    pnl = ot["rw"] - spread_cost
                    res = "TP"
            if res:
                bal  += pnl
                peak  = max(peak, bal)
                dpnl[day] = dpnl.get(day, 0.0) + pnl
                trades.append({
                    "date":  day,
                    "hr":    ot["hr"],
                    "dir":   ot["d"],
                    "entry": round(ot["e"], 5),
                    "sl":    round(ot["sl"], 5),
                    "tp":    round(ot["tp"], 5),
                    "sl_dist": round(ot["sd"], 5),
                    "pnl":   round(pnl, 4),
                    "res":   res,
                    "bal":   round(bal, 4),
                })
                ot = None

        # ── New entry (next-bar open) ───────────────────────────────────────
        if ot is None and int(sa[i]) != 0:
            daily[day] = daily.get(day, 0) + 1
            if daily[day] > max_td:
                continue

            sig_v  = int(sa[i])
            entry  = float(oa[i + 1])
            av     = float(atr[i])
            if np.isnan(av) or av <= 0:
                continue

            if sig_v == 1:
                sl = float(sw_lo[i]) - av * buf
                sl_dist = entry - sl
            else:
                sl = float(sw_hi[i]) + av * buf
                sl_dist = sl - entry

            if sl_dist <= 0:
                continue

            r  = bal * risk_pct
            rw = r * rr
            tp = entry + sl_dist * rr if sig_v == 1 else entry - sl_dist * rr

            ot = {"d": sig_v, "e": entry, "sl": sl, "tp": tp,
                  "sd": sl_dist, "r": r, "rw": rw,
                  "i": i, "hr": int(times[i].hour)}

    return pd.DataFrame(trades), dpnl


# ── Per-symbol runner ─────────────────────────────────────────────────────────

def run_symbol(
    symbol: str,
    p: dict,
    months: int = 3,
    strength_ts: Optional[Dict] = None,
    enable: Optional[Dict] = None,
    news_events: Optional[list] = None,
    verbose: bool = True,
) -> dict:
    """Run MTF backtest for a single symbol. Returns result dict."""
    if enable is None:
        enable = MTF_DEFAULT_FILTERS.copy()

    pip = get_pip_size(symbol)
    sym_cfg = MTF_SYMBOL_CONFIG.get(symbol, {"spread_max_pts": 30, "atr_min_pts": 50})
    spread_cost = sym_cfg["spread_max_pts"] * 0.0001  # approx spread in price

    bars_m1  = months * 30 * 24 * 60
    bars_m3  = months * 30 * 8  * 60
    bars_m15 = months * 30 * 24 * 12

    if verbose:
        print(f"  [{symbol}] Fetching M1/M3/M15...", flush=True)

    df_m1, df_m3, df_m15 = fetch_mtf_data(symbol, bars_m1, bars_m3, bars_m15, p)

    if df_m1.empty:
        return {"symbol": symbol, "error": "Data fetch failed or M3/M15 unavailable"}

    df = align_mtf_to_m1(df_m1, df_m3, df_m15).dropna()

    if len(df) < 200:
        return {"symbol": symbol, "error": "Insufficient data after alignment"}

    days = (df.index[-1] - df.index[0]).days

    sigs = compute_mtf_signals(
        df, p, pip,
        symbol=symbol,
        strength_ts=strength_ts,
        news_events=news_events,
        enable=enable,
    )

    nsig = int((sigs != 0).sum())
    if verbose:
        print(f"  [{symbol}] {len(df)} bars | {days}d | {nsig} signals ({nsig/max(days,1):.1f}/day)")

    trades_df, dpnl = simulate_mtf_trades(df, sigs, p, pip, spread_cost)

    if trades_df.empty:
        return {"symbol": symbol, "trades": 0, "wr": 0, "pf": 0,
                "net": 0, "mdd": 0, "days": days, "spd": 0}

    wins = trades_df[trades_df["pnl"] > 0]
    loss = trades_df[trades_df["pnl"] <= 0]
    net  = trades_df["pnl"].sum()
    tl   = loss["pnl"].abs().sum()
    pf   = wins["pnl"].sum() / tl if tl > 0 else 99.0
    wr   = len(wins) / len(trades_df) * 100
    cum  = trades_df["pnl"].cumsum() + p["InitialBalance"]
    pk   = cum.cummax()
    mdd  = ((pk - cum) / pk * 100).max()
    dv   = list(dpnl.values())
    spd  = len(trades_df) / max(days, 1)

    return {
        "symbol":  symbol,
        "days":    days,
        "trades":  len(trades_df),
        "spd":     round(spd, 2),
        "wr":      round(wr, 1),
        "pf":      round(pf, 2),
        "net":     round(net, 2),
        "mdd":     round(mdd, 1),
        "final":   round(p["InitialBalance"] + net, 2),
        "best_day":  round(max(dv), 2) if dv else 0,
        "worst_day": round(min(dv), 2) if dv else 0,
        "dpnl":    dpnl,
        "trades_df": trades_df,
    }


# ── Multi-symbol orchestrator ─────────────────────────────────────────────────

def run_all(
    symbols: List[str],
    p: dict,
    months: int = 3,
    enable: Optional[Dict] = None,
    compute_strength: bool = False,
    use_news: bool = False,
) -> List[dict]:
    """Fetch data and run MTF backtest for all symbols."""
    if enable is None:
        enable = MTF_DEFAULT_FILTERS.copy()
    enable["currency_strength"] = compute_strength
    enable["news"] = use_news

    # Pre-fetch news events once
    news_events = None
    if use_news:
        from news_filter import fetch_ff_calendar
        news_events = fetch_ff_calendar()
        print(f"News filter ON — {len(news_events)} events loaded")

    # Pre-fetch all 28 forex pairs' M1 data for currency strength
    strength_ts = None
    if compute_strength:
        print("Computing currency strength (fetching all 28 forex pairs)...")
        forex_pairs = [s for s in symbols if s not in ("XAUUSD", "BTCUSD")]
        all_m1 = {}
        for sym in forex_pairs:
            df = fetch_ohlcv(sym, mt5.TIMEFRAME_M1, months * 30 * 24 * 60)
            if not df.empty:
                all_m1[sym] = df
        if all_m1:
            strength_ts = compute_currency_strength(all_m1)
            print(f"Strength computed for {len(strength_ts)} currencies")

    results = []
    for sym in symbols:
        if not check_symbol(sym):
            print(f"  [{sym}] Not available on this broker — skipping")
            continue
        # Apply per-symbol param + filter overrides
        sym_p = p.copy()
        sym_p.update(MTF_SYMBOL_PARAMS.get(sym, {}))
        sym_en = enable.copy()
        sym_en.update(MTF_SYMBOL_FILTERS.get(sym, {}))
        result = run_symbol(sym, sym_p, months, strength_ts, sym_en, news_events)
        results.append(result)

    return results


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(results: List[dict], months: int):
    valid = [r for r in results if "error" not in r and r.get("trades", 0) > 0]
    fails = [r for r in results if "error" in r or r.get("trades", 0) == 0]

    # Sort by profit factor
    valid.sort(key=lambda x: x["pf"], reverse=True)

    print(f"\n{'='*75}")
    print(f"  MTF EMA ALIGNMENT SCALPER — {months}-MONTH BACKTEST RESULTS")
    print(f"  Strategy: 200/9/15 EMA | M15+M3+M1 | Swing SL | RR 1:2 | 2% risk")
    print(f"{'='*75}")
    print(f"  {'Symbol':<10} {'Trades':>6} {'T/day':>5} {'WR%':>6} {'PF':>5} "
          f"{'Net$':>8} {'Final$':>8} {'DD%':>6}")
    print(f"  {'-'*68}")

    for r in valid:
        flag = " *" if r["pf"] >= 1.5 and r["wr"] >= 48 else ""
        print(f"  {r['symbol']:<10} {r['trades']:>6} {r['spd']:>5.1f} "
              f"{r['wr']:>5.1f}% {r['pf']:>5.2f} "
              f"{r['net']:>+8.2f} {r['final']:>8.2f} {r['mdd']:>5.1f}%{flag}")

    if fails:
        print(f"\n  No trades / unavailable: {', '.join(r['symbol'] for r in fails)}")

    # Aggregate
    if valid:
        total_trades = sum(r["trades"] for r in valid)
        avg_wr = sum(r["wr"] for r in valid) / len(valid)
        avg_pf = sum(r["pf"] for r in valid) / len(valid)
        total_net = sum(r["net"] for r in valid)
        profitable = sum(1 for r in valid if r["net"] > 0)

        print(f"\n  {'─'*68}")
        print(f"  Symbols tested : {len(results)}  |  With trades: {len(valid)}")
        print(f"  Total trades   : {total_trades}")
        print(f"  Profitable syms: {profitable}/{len(valid)}")
        print(f"  Avg Win Rate   : {avg_wr:.1f}%")
        print(f"  Avg Prof Factor: {avg_pf:.2f}")
        print(f"  Total Net PnL  : ${total_net:.2f}")
        print(f"\n  * = strong edge (PF >= 1.5, WR >= 48%)")

    # Top 5 detail
    top5 = valid[:5]
    if top5:
        print(f"\n{'='*75}")
        print(f"  TOP 5 SYMBOLS — DAILY P&L DETAIL")
        print(f"{'='*75}")
        for r in top5:
            dpnl = r.get("dpnl", {})
            dv   = sorted(dpnl.values())
            pos  = sum(1 for v in dv if v > 0)
            print(f"\n  {r['symbol']} | WR {r['wr']:.1f}% | PF {r['pf']:.2f} | "
                  f"Net ${r['net']:.2f} | {pos}/{len(dv)} green days")
            for d, v in sorted(dpnl.items()):
                tag  = "WIN " if v >= 0 else "LOSS"
                bar  = "#" * min(int(abs(v) / 1.0), 30)
                sign = "+" if v >= 0 else ""
                print(f"    {d}  {sign}${v:>7.2f}  {tag}  {bar}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MTF EMA Alignment Scalper Backtest")
    parser.add_argument("--symbols",  nargs="+", default=None,
                        help="Symbols to test (default: all 30)")
    parser.add_argument("--months",   type=int,  default=3,
                        help="Months of history (default: 3)")
    parser.add_argument("--strength", action="store_true",
                        help="Enable currency strength filter")
    parser.add_argument("--news",     action="store_true",
                        help="Enable news blackout filter (requires internet)")
    parser.add_argument("--no-rsi",   action="store_true",
                        help="Disable RSI filter")
    parser.add_argument("--no-atr",   action="store_true",
                        help="Disable ATR volatility filter")
    parser.add_argument("--output",   default=None,
                        help="Save results to JSON file")
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else MTF_SYMBOLS

    p = MTF_DEFAULT_PARAMS.copy()

    enable = MTF_DEFAULT_FILTERS.copy()
    if args.no_rsi:    enable["rsi"]     = False
    if args.no_atr:    enable["atr_vol"] = False
    if args.strength:  enable["currency_strength"] = True
    if args.news:      enable["news"]    = True

    print(f"\nMTF EMA Alignment Scalper Backtest")
    print(f"Symbols  : {len(symbols)}")
    print(f"Period   : {args.months} months")
    print(f"Filters  : {[k for k,v in enable.items() if v]}")
    print(f"Risk     : {p['RiskPct']}% | RR 1:{p['RR_Ratio']} | "
          f"Daily DD {p['DailyDDPct']}%\n")

    connect()
    results = run_all(symbols, p, args.months, enable,
                      compute_strength=args.strength,
                      use_news=args.news)
    disconnect()

    print_summary(results, args.months)

    if args.output:
        exportable = []
        for r in results:
            r2 = {k: v for k, v in r.items() if k not in ("trades_df", "dpnl")}
            exportable.append(r2)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(exportable, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")

    print("\nDone.")


if __name__ == "__main__":
    main()
