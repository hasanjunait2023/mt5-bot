"""
Fast optimizer: groups combos by indicator params, reuses pre-computed score arrays.
36 indicator sets × 12 (ATR_SL_Multi × RequiredScore) = 432 combos total.
Score arrays computed once per indicator set (vectorized), then threshold applied cheaply.
"""
import sys
import itertools
import time
from copy import deepcopy
import numpy as np
import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from backtest import add_indicators, compute_score_arrays, signals_from_scores, simulate_trades, compute_metrics
from config import DEFAULT_PARAMS, SYMBOL_OPTIMIZER_GRID, OPTIMIZER_GRID, SYMBOL_CONFIG


def run_fast_optimizer(symbol, months=1, top_n=5):
    grid = SYMBOL_OPTIMIZER_GRID.get(symbol, OPTIMIZER_GRID)

    # Split into indicator params (affect indicators) vs threshold params (don't)
    INDICATOR_KEYS = ["EMA_Fast", "EMA_Slow", "RSI_Period"]
    THRESHOLD_KEYS = ["ATR_SL_Multi", "RequiredScore"]

    indic_vals  = [grid[k] for k in INDICATOR_KEYS]
    thresh_vals = [grid[k] for k in THRESHOLD_KEYS]
    indic_combos  = list(itertools.product(*indic_vals))
    thresh_combos = list(itertools.product(*thresh_vals))
    total = len(indic_combos) * len(thresh_combos)

    bars = months * 30 * 24 * 60
    print(f"\n{'='*65}", flush=True)
    print(f"  FAST OPTIMIZER: {symbol} | {months}mo | "
          f"{len(indic_combos)} indicator sets × {len(thresh_combos)} thresholds = {total} combos", flush=True)
    print(f"{'='*65}", flush=True)

    if not check_symbol(symbol):
        print(f"  {symbol} not available, skipping.", flush=True)
        return []

    print(f"  Fetching {bars} M1 bars...", flush=True)
    raw_df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
    if raw_df.empty:
        print(f"  No data for {symbol}.", flush=True)
        return []

    pip = get_pip_size(symbol)
    sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
    SYMBOL_CONFIG["_atr_min"] = sym_cfg["atr_min_pips"]
    session_hours = sym_cfg.get("session_hours")

    print(f"  Got {len(raw_df)} bars | Pip={pip}", flush=True)

    results = []
    combo_idx = 0
    t_start = time.time()

    for ic in indic_combos:
        # Build params with this indicator set
        params = deepcopy(DEFAULT_PARAMS)
        for k, v in zip(INDICATOR_KEYS, ic):
            params[k] = v

        # Compute indicators once for this set
        df = add_indicators(raw_df, params)
        df = df.dropna()

        # Compute score arrays once (vectorized, O(n) numpy)
        a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
            df, params, pip, session_hours)

        ic_label = dict(zip(INDICATOR_KEYS, ic))
        print(f"\n  Indicator set {ic_label}", flush=True)

        for tc in thresh_combos:
            combo_idx += 1
            for k, v in zip(THRESHOLD_KEYS, tc):
                params[k] = v

            req = params["RequiredScore"]

            # Signals from pre-computed arrays — O(n) numpy, microseconds
            signals = signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid, req, df.index)

            # Simulate trades (Python loop, but much less data than full bars)
            trades = simulate_trades(df, signals, params, pip)
            metrics = compute_metrics(trades, params["InitialBalance"])

            if "error" in metrics or metrics.get("total_trades", 0) < 10:
                print(f"    [{combo_idx}/{total}] SL={params['ATR_SL_Multi']} Req={req} >> skip", flush=True)
                continue

            dd  = metrics["max_drawdown_pct"]
            pf  = metrics["profit_factor"]
            wr  = metrics["win_rate_pct"]
            net = metrics["net_pnl"]
            score = pf if dd < 20.0 else 0.0

            print(f"    [{combo_idx}/{total}] SL={params['ATR_SL_Multi']} Req={req}"
                  f" >> PF={pf:.2f} WR={wr:.1f}% DD={dd:.1f}% Net=${net:.0f}", flush=True)

            results.append({
                "params":         {**dict(zip(INDICATOR_KEYS, ic)), **dict(zip(THRESHOLD_KEYS, tc))},
                "profit_factor":  pf,
                "win_rate":       wr,
                "max_drawdown":   dd,
                "net_pnl":        net,
                "total_trades":   metrics["total_trades"],
                "sharpe":         metrics["sharpe_ratio"],
                "final_balance":  metrics["final_balance"],
                "score":          score,
            })

    elapsed = time.time() - t_start
    print(f"\n  Completed {total} combos in {elapsed:.0f}s ({elapsed/total:.1f}s/combo)", flush=True)

    if not results:
        print(f"  No valid results for {symbol}.", flush=True)
        return []

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    print(f"\n  {'='*55}", flush=True)
    print(f"  TOP {top_n} RESULTS — {symbol}", flush=True)
    print(f"  {'='*55}", flush=True)
    for rank, r in enumerate(top, 1):
        print(f"  #{rank}  PF={r['profit_factor']:.2f}  WR={r['win_rate']:.1f}%"
              f"  DD={r['max_drawdown']:.1f}%  Net=${r['net_pnl']:.0f}"
              f"  FinalBal=${r['final_balance']:.0f}  Trades={r['total_trades']}", flush=True)
        for k, v in r["params"].items():
            print(f"       {k}: {v}", flush=True)

    best = top[0]["params"]
    print(f"\n  *** BEST PARAMS FOR {symbol} MT5 BOT ***", flush=True)
    print(f"    EMA_Fast     = {best.get('EMA_Fast')}", flush=True)
    print(f"    EMA_Slow     = {best.get('EMA_Slow')}", flush=True)
    print(f"    RSI_Period   = {best.get('RSI_Period')}", flush=True)
    print(f"    ATR_SL_Multi = {best.get('ATR_SL_Multi')}", flush=True)
    print(f"    RequiredScore= {best.get('RequiredScore')}", flush=True)
    return top


if __name__ == "__main__":
    if not connect():
        sys.exit(1)

    all_results = {}
    for sym in ["XAUUSD", "EURUSD", "BTCUSD"]:
        top = run_fast_optimizer(sym, months=1, top_n=5)
        if top:
            all_results[sym] = top

    disconnect()

    print("\n\n" + "="*65, flush=True)
    print("  FINAL SUMMARY — BEST PARAMS PER SYMBOL", flush=True)
    print("="*65, flush=True)
    for sym, top in all_results.items():
        b = top[0]
        print(f"\n  {sym}: PF={b['profit_factor']:.2f}  WR={b['win_rate']:.1f}%"
              f"  Net=${b['net_pnl']:.0f}  FinalBal=${b['final_balance']:.0f}", flush=True)
        print(f"    Params: {b['params']}", flush=True)

    print("\nAll optimizers complete.", flush=True)
