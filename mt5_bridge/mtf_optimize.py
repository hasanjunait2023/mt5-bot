# encoding: utf-8
"""
mtf_optimize.py — Targeted optimization for underperforming MTF pairs.

Tests:
  1. Gold (XAUUSD) with Gold-specific parameter sets
  2. Failing pairs (PF < 1.0) with filter/param variations
  3. 14 unclassified pairs with standard params + 2 variations

Usage:
  python mtf_optimize.py --target gold
  python mtf_optimize.py --target failing
  python mtf_optimize.py --target unclassified
  python mtf_optimize.py --target all          (default, runs everything)
  python mtf_optimize.py --months 2
  python mtf_optimize.py --output results.json
"""
import sys, os
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import argparse
import copy
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import (
    MTF_SYMBOLS, MTF_SYMBOL_CONFIG, MTF_DEFAULT_PARAMS,
    MTF_DEFAULT_FILTERS, MAJOR_CURRENCIES,
)
from mtf_strategy import (
    fetch_mtf_data, align_mtf_to_m1, compute_mtf_signals,
    compute_sl_tp_arrays, _swing_low_series, _swing_high_series,
)
from mtf_backtest import simulate_mtf_trades, run_symbol


# ─────────────────────────────────────────────────────────────────────────────
# Parameter profiles (overrides on top of MTF_DEFAULT_PARAMS)
# ─────────────────────────────────────────────────────────────────────────────

# ── Gold (XAUUSD) ─────────────────────────────────────────────────────────────
# Gold dynamics: macro-driven, large impulsive moves, SNB-free, driven by
# USD strength & risk sentiment. M1 EMA crossovers on Gold are very noisy
# unless combined with session timing and wider trend confirmation.

GOLD_PARAM_OVERRIDES = {
    "default_params": {
        # Baseline — exactly what the current strategy uses for all pairs
    },
    "gold_sessions": {
        # Gold's peak volatility: London Fix (10:30) + NY open + Asian close
        "London_Start": 8,  "London_End": 12,
        "NY_Start": 13,     "NY_End": 17,
        # Filter: only when ATR is strongly above median (Gold has spikes)
        # (no param change needed — same atr_vol filter)
    },
    "gold_wide_rsi": {
        # Gold can sustain overbought/oversold longer than forex pairs
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  75,
        "RSI_Sell_Lo": 25, "RSI_Sell_Hi": 60,
    },
    "gold_v1_sessions_rsi": {
        # Custom sessions + wide RSI — most likely improvement
        "London_Start": 8,  "London_End": 12,
        "NY_Start": 13,     "NY_End": 17,
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  75,
        "RSI_Sell_Lo": 25, "RSI_Sell_Hi": 60,
    },
    "gold_v2_ema21": {
        # EMA 9/21 instead of 9/15 — requires stronger separation = fewer, better signals
        "EMA_Slow": 21,
        "London_Start": 8,  "London_End": 12,
        "NY_Start": 13,     "NY_End": 17,
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  75,
        "RSI_Sell_Lo": 25, "RSI_Sell_Hi": 60,
        "SL_Lookback": 8,   # Gold wicks are deep — look further for swing
    },
    "gold_v3_no_rsi": {
        # Remove RSI entirely — let 3-TF alignment + ATR do the filtering
        "EMA_Slow": 21,
        "London_Start": 8,  "London_End": 12,
        "NY_Start": 13,     "NY_End": 17,
        "SL_Lookback": 8,
    },
    "gold_v4_rr15": {
        # Easier TP: RR 1:1.5 — Gold often partially fills TP at 2× then reverses
        "EMA_Slow": 21,
        "London_Start": 8,  "London_End": 12,
        "NY_Start": 13,     "NY_End": 17,
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  75,
        "RSI_Sell_Lo": 25, "RSI_Sell_Hi": 60,
        "SL_Lookback": 8,
        "RR_Ratio": 1.5,
    },
    "gold_v5_tight_sl": {
        # Tighter SL lookback = smaller SL = higher RR distance = more aggressive TP
        "EMA_Slow": 21,
        "London_Start": 8,  "London_End": 12,
        "NY_Start": 13,     "NY_End": 17,
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  75,
        "RSI_Sell_Lo": 25, "RSI_Sell_Hi": 60,
        "SL_Lookback": 3,
        "SL_Buffer_ATR": 0.05,
    },
}

GOLD_FILTER_OVERRIDES = {
    "default_params":          {},
    "gold_sessions":           {},
    "gold_wide_rsi":           {},
    "gold_v1_sessions_rsi":    {},
    "gold_v2_ema21":           {},
    "gold_v3_no_rsi":          {"rsi": False},
    "gold_v4_rr15":            {},
    "gold_v5_tight_sl":        {},
}


# ── Failing pairs (PF < 1.0) ──────────────────────────────────────────────────
# GBPUSD(0.97), USDCHF(0.65), EURAUD(0.55), CADCHF(0.56), EURCHF(0.20)

FAIL_PARAM_OVERRIDES = {
    "default": {},
    "wide_rsi": {
        "RSI_Buy_Lo": 40, "RSI_Buy_Hi": 72,
        "RSI_Sell_Lo": 28, "RSI_Sell_Hi": 60,
    },
    "london_only": {
        # Remove NY session — London is cleaner for EUR/CHF/CAD pairs
        "NY_Start": 23, "NY_End": 23,  # effectively no NY
    },
    "wider_sl": {
        # Look further back for swing — reduces false SL hits
        "SL_Lookback": 8, "SL_Buffer_ATR": 0.15,
    },
    "rr_1_5": {
        # Easier TP: 1:1.5 — for choppy pairs where 1:2 is too ambitious
        "RR_Ratio": 1.5,
    },
    "combined_fix": {
        # Most likely combination to improve choppy/slow pairs
        "RSI_Buy_Lo": 40, "RSI_Buy_Hi": 72,
        "RSI_Sell_Lo": 28, "RSI_Sell_Hi": 60,
        "SL_Lookback": 7,
        "RR_Ratio": 1.5,
        "NY_Start": 23, "NY_End": 23,
    },
    "strict_candle": {
        # Demand higher-quality candles (fewer, better signals)
        "MinBodyRatio": 0.45,
        "SL_Lookback": 5,
    },
}

FAIL_FILTER_OVERRIDES = {
    "default":       {},
    "wide_rsi":      {},
    "london_only":   {},
    "wider_sl":      {},
    "rr_1_5":        {},
    "combined_fix":  {"candle_quality": False},
    "strict_candle": {},
}


# ── Unclassified pairs (never tested before) ──────────────────────────────────
UNCLASSIFIED_PAIRS = [
    "AUDUSD", "EURGBP", "EURJPY", "GBPJPY", "GBPCHF",
    "GBPNZD", "GBPCAD", "EURCAD", "EURNZD",
    "AUDJPY", "AUDCAD", "NZDJPY", "NZDCHF", "NZDCAD", "CHFJPY",
]

# Remove pairs already in best/avoid lists
_KNOWN = {
    "CADJPY", "EURJPY", "USDJPY", "GBPAUD", "BTCUSD", "AUDNZD",
    "USDCAD", "EURUSD", "AUDCHF", "NZDUSD",  # best
    "GBPUSD", "USDCHF", "EURAUD", "CADCHF", "XAUUSD", "EURCHF",  # avoid
}
UNCLASSIFIED_PAIRS = [p for p in UNCLASSIFIED_PAIRS if p not in _KNOWN]

UNCLASSIFIED_PARAM_OVERRIDES = {
    "default": {},
    "wide_rsi": {
        "RSI_Buy_Lo": 42, "RSI_Buy_Hi": 68,
        "RSI_Sell_Lo": 32, "RSI_Sell_Hi": 58,
    },
    "london_only": {
        "NY_Start": 23, "NY_End": 23,
    },
}
UNCLASSIFIED_FILTER_OVERRIDES = {
    "default":     {},
    "wide_rsi":    {},
    "london_only": {},
}


# ─────────────────────────────────────────────────────────────────────────────
# Core runner
# ─────────────────────────────────────────────────────────────────────────────

def run_profile(
    symbol: str,
    profile_name: str,
    param_overrides: dict,
    filter_overrides: dict,
    months: int = 3,
    verbose: bool = False,
) -> dict:
    """Run backtest for one symbol with one parameter profile."""
    p = MTF_DEFAULT_PARAMS.copy()
    p.update(param_overrides)

    enable = MTF_DEFAULT_FILTERS.copy()
    enable.update(filter_overrides)

    result = run_symbol(
        symbol, p, months,
        strength_ts=None,
        enable=enable,
        news_events=None,
        verbose=verbose,
    )
    result["profile"] = profile_name
    return result


def run_optimization(
    symbols: List[str],
    param_set: Dict[str, dict],
    filter_set: Dict[str, dict],
    months: int = 3,
    label: str = "",
) -> List[dict]:
    """
    For each symbol, run all profiles and return best result per symbol.
    Also returns all individual results for full reporting.
    """
    all_results = []  # flat: one entry per (symbol, profile)
    best_per_symbol = {}  # symbol → best result

    for sym in symbols:
        if not check_symbol(sym):
            print(f"  [{sym}] Not available — skipping")
            continue

        print(f"\n  {label}[{sym}] Testing {len(param_set)} profiles...")

        sym_results = []
        for pname, p_override in param_set.items():
            f_override = filter_set.get(pname, {})
            r = run_profile(sym, pname, p_override, f_override, months, verbose=False)
            r["symbol"] = sym

            trades = r.get("trades", 0)
            pf     = r.get("pf", 0.0)
            wr     = r.get("wr", 0.0)
            net    = r.get("net", 0.0)
            err    = r.get("error", None)

            status = f"PF={pf:.2f}  WR={wr:.1f}%  T={trades}" if not err else f"ERROR: {err}"
            print(f"    [{pname:25s}]  {status}")

            sym_results.append(r)
            all_results.append(r)

        # Pick best by PF (min 3 trades, no error)
        valid = [r for r in sym_results if not r.get("error") and r.get("trades", 0) >= 3]
        if valid:
            best = max(valid, key=lambda x: x["pf"])
            best_per_symbol[sym] = best

    return all_results, best_per_symbol


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

ORIGINAL_PF = {
    # Known results from first full backtest
    "CADJPY": 8.13, "EURJPY": 6.37, "USDJPY": 4.43, "GBPAUD": 3.42,
    "BTCUSD": 3.24, "AUDNZD": 3.05, "USDCAD": 2.80, "EURUSD": 2.56,
    "AUDCHF": 2.24, "NZDUSD": 1.96,
    "GBPUSD": 0.97, "USDCHF": 0.65, "EURAUD": 0.55, "CADCHF": 0.56,
    "XAUUSD": 0.49, "EURCHF": 0.20,
}


def print_optimization_report(
    best_per_symbol: Dict[str, dict],
    all_results: List[dict],
    section_title: str,
    months: int,
):
    print(f"\n{'='*80}")
    print(f"  {section_title} — {months}-MONTH OPTIMIZATION RESULTS")
    print(f"{'='*80}")
    print(f"  {'Symbol':<10} {'Old PF':>7} {'New PF':>7} {'Delta':>7} "
          f"{'WR%':>6} {'Trades':>7} {'Net$':>8}  Profile")
    print(f"  {'-'*75}")

    rows = sorted(best_per_symbol.items(), key=lambda x: x[1].get("pf", 0), reverse=True)
    for sym, r in rows:
        old_pf = ORIGINAL_PF.get(sym, None)
        new_pf = r.get("pf", 0.0)
        wr     = r.get("wr", 0.0)
        trades = r.get("trades", 0)
        net    = r.get("net", 0.0)
        prof   = r.get("profile", "?")
        old_s  = f"{old_pf:.2f}" if old_pf is not None else "  NEW"
        delta_s = ""
        if old_pf is not None:
            d = new_pf - old_pf
            delta_s = f"{d:+.2f}"
        flag = " ***" if new_pf >= 1.5 and wr >= 45 else (" ++" if new_pf >= 1.0 else "")
        print(f"  {sym:<10} {old_s:>7} {new_pf:>7.2f} {delta_s:>7} "
              f"{wr:>5.1f}% {trades:>7} {net:>+8.2f}  {prof}{flag}")

    # All profiles detail (condensed)
    print(f"\n  --- All profiles tested ---")
    by_sym: Dict[str, List] = {}
    for r in all_results:
        s = r.get("symbol", "?")
        by_sym.setdefault(s, []).append(r)

    for sym in sorted(by_sym.keys()):
        items = sorted(by_sym[sym], key=lambda x: x.get("pf", 0), reverse=True)
        print(f"\n  {sym}:")
        for r in items:
            if r.get("error"):
                print(f"    {r['profile']:25s}  ERROR: {r['error']}")
            else:
                print(f"    {r['profile']:25s}  PF={r['pf']:5.2f}  WR={r['wr']:4.1f}%  "
                      f"T={r['trades']:3d}  Net${r['net']:+8.2f}")

    # Recommendations
    print(f"\n{'='*80}")
    print(f"  RECOMMENDATIONS")
    print(f"{'='*80}")
    winners = [(s, r) for s, r in rows if r.get("pf", 0) >= 1.5]
    marginal = [(s, r) for s, r in rows if 1.0 <= r.get("pf", 0) < 1.5]
    losers   = [(s, r) for s, r in rows if r.get("pf", 0) < 1.0]

    if winners:
        print(f"\n  TRADEABLE (PF >= 1.5) — Add to live trader:")
        for s, r in winners:
            print(f"    {s:<10}  PF {r['pf']:.2f}  WR {r['wr']:.1f}%  "
                  f"Profile: {r['profile']}")

    if marginal:
        print(f"\n  MARGINAL (1.0 <= PF < 1.5) — Optional with caution:")
        for s, r in marginal:
            print(f"    {s:<10}  PF {r['pf']:.2f}  WR {r['wr']:.1f}%  "
                  f"Profile: {r['profile']}")

    if losers:
        print(f"\n  AVOID (PF < 1.0) — Do not trade:")
        for s, r in losers:
            print(f"    {s:<10}  PF {r['pf']:.2f}  "
                  f"(original: {ORIGINAL_PF.get(s, 'N/A')})")


# ─────────────────────────────────────────────────────────────────────────────
# Recommended params printer
# ─────────────────────────────────────────────────────────────────────────────

def print_param_recommendations(best_per_symbol: Dict[str, dict]):
    print(f"\n{'='*80}")
    print(f"  PARAM OVERRIDES TO ADD TO config.py  (copy-paste ready)")
    print(f"{'='*80}")
    print(f"\n# Add this dict to config.py as MTF_SYMBOL_PARAMS:")
    print(f"MTF_SYMBOL_PARAMS = {{")
    for sym, r in sorted(best_per_symbol.items()):
        pf = r.get("pf", 0.0)
        if pf < 1.0:
            continue
        prof = r.get("profile", "default")
        # Determine which overrides were used
        overrides = None
        for ps in [GOLD_PARAM_OVERRIDES, FAIL_PARAM_OVERRIDES, UNCLASSIFIED_PARAM_OVERRIDES]:
            if prof in ps:
                overrides = ps[prof]
                break
        if overrides is None or not overrides:
            continue
        print(f'    "{sym}": {json.dumps(overrides)},  # PF={pf:.2f} [{prof}]')
    print(f"}}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MTF EMA Scalper Pair Optimizer")
    parser.add_argument("--target",  default="all",
                        choices=["gold", "failing", "unclassified", "all"],
                        help="Which group to optimize")
    parser.add_argument("--months",  type=int, default=3,
                        help="Months of history (default: 3)")
    parser.add_argument("--output",  default=None,
                        help="Save best results to JSON")
    args = parser.parse_args()

    print(f"\nMTF EMA Scalper - Pair Optimizer")
    print(f"Target  : {args.target}")
    print(f"Period  : {args.months} months")
    print(f"Date    : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    connect()

    all_best = {}

    # ── Gold ────────────────────────────────────────────────────────────────
    if args.target in ("gold", "all"):
        print(f"\n{'─'*60}")
        print(f"  GOLD (XAUUSD) — {len(GOLD_PARAM_OVERRIDES)} parameter profiles")
        print(f"{'─'*60}")
        all_r, best = run_optimization(
            ["XAUUSD"],
            GOLD_PARAM_OVERRIDES,
            GOLD_FILTER_OVERRIDES,
            months=args.months,
            label="GOLD ",
        )
        all_best.update(best)
        print_optimization_report(best, all_r, "GOLD OPTIMIZATION", args.months)

    # ── Failing pairs ────────────────────────────────────────────────────────
    if args.target in ("failing", "all"):
        failing_pairs = ["GBPUSD", "USDCHF", "EURAUD", "CADCHF", "EURCHF"]
        print(f"\n{'─'*60}")
        print(f"  FAILING PAIRS — {len(failing_pairs)} pairs x {len(FAIL_PARAM_OVERRIDES)} profiles")
        print(f"{'─'*60}")
        all_r, best = run_optimization(
            failing_pairs,
            FAIL_PARAM_OVERRIDES,
            FAIL_FILTER_OVERRIDES,
            months=args.months,
            label="FAIL  ",
        )
        all_best.update(best)
        print_optimization_report(best, all_r, "FAILING PAIRS OPTIMIZATION", args.months)

    # ── Unclassified pairs ───────────────────────────────────────────────────
    if args.target in ("unclassified", "all"):
        print(f"\n{'─'*60}")
        print(f"  UNCLASSIFIED — {len(UNCLASSIFIED_PAIRS)} pairs x {len(UNCLASSIFIED_PARAM_OVERRIDES)} profiles")
        print(f"  Pairs: {', '.join(UNCLASSIFIED_PAIRS)}")
        print(f"{'─'*60}")
        all_r, best = run_optimization(
            UNCLASSIFIED_PAIRS,
            UNCLASSIFIED_PARAM_OVERRIDES,
            UNCLASSIFIED_FILTER_OVERRIDES,
            months=args.months,
            label="UNCLS ",
        )
        all_best.update(best)
        print_optimization_report(best, all_r, "UNCLASSIFIED PAIRS", args.months)

    disconnect()

    # ── Final combined summary ───────────────────────────────────────────────
    if args.target == "all" and all_best:
        print(f"\n{'='*80}")
        print(f"  COMBINED FINAL SUMMARY — All Tested Pairs")
        print(f"{'='*80}")
        rows = sorted(all_best.items(), key=lambda x: x[1].get("pf", 0), reverse=True)
        print(f"  {'Symbol':<10} {'PF':>6}  {'WR%':>6}  {'Trades':>7}  {'Net$':>8}  Profile")
        print(f"  {'-'*65}")
        for s, r in rows:
            tag = " ***" if r.get("pf", 0) >= 1.5 else (" +" if r.get("pf", 0) >= 1.0 else "")
            print(f"  {s:<10} {r.get('pf',0):>6.2f}  {r.get('wr',0):>5.1f}%  "
                  f"{r.get('trades',0):>7}  {r.get('net',0):>+8.2f}  {r.get('profile','?')}{tag}")

        print_param_recommendations(all_best)

    if args.output and all_best:
        export = {}
        for sym, r in all_best.items():
            export[sym] = {k: v for k, v in r.items() if k not in ("trades_df", "dpnl")}
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")

    print("\nOptimization complete.")


if __name__ == "__main__":
    main()
