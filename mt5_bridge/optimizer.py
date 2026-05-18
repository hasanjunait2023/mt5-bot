"""
Parameter optimizer — grid search over key strategy parameters.
Objective: maximize Profit Factor while keeping Max Drawdown < 20%.

Usage:
    python optimizer.py --symbol EURUSD --months 3
    python optimizer.py --symbol XAUUSD --months 6 --top 10
"""

import argparse
import itertools
import sys
from copy import deepcopy

import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from backtest import run_with_data
from config import DEFAULT_PARAMS, OPTIMIZER_GRID, SYMBOL_OPTIMIZER_GRID


def grid_search(symbol: str, months: int, top_n: int = 5):
    grid   = SYMBOL_OPTIMIZER_GRID.get(symbol, OPTIMIZER_GRID)
    keys   = list(grid.keys())
    values = list(grid.values())
    combos = list(itertools.product(*values))
    total  = len(combos)

    # Fetch data ONCE and reuse across all combinations
    bars = months * 30 * 24 * 60
    print(f"\nOptimizer: {symbol} | {months} months | {total} parameter combinations")
    print(f"Fetching {bars} M1 bars once...")
    if not check_symbol(symbol):
        print(f"Symbol {symbol} not available"); return []
    raw_df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
    if raw_df.empty:
        print("No data fetched"); return []
    pip = get_pip_size(symbol)
    print(f"Got {len(raw_df)} bars | Pip={pip} | Starting grid search...")
    print("=" * 60)

    results = []

    for idx, combo in enumerate(combos):
        params = deepcopy(DEFAULT_PARAMS)
        for k, v in zip(keys, combo):
            params[k] = v

        print(f"[{idx+1}/{total}] Testing: {dict(zip(keys, combo))}", end=" ... ", flush=True)

        try:
            result = run_with_data(raw_df, symbol, params, pip)
            m = result.get("metrics", {})
            if "error" in m or m.get("total_trades", 0) < 10:
                print("skip (< 10 trades)", flush=True)
                continue

            # Score: profit factor, but penalize if DD > 20%
            dd   = m["max_drawdown_pct"]
            pf   = m["profit_factor"]
            wr   = m["win_rate_pct"]
            score = pf if dd < 20.0 else 0.0

            print(f"PF={pf:.2f}  WR={wr:.1f}%  DD={dd:.1f}%  Trades={m['total_trades']}", flush=True)

            results.append({
                "params":         dict(zip(keys, combo)),
                "profit_factor":  pf,
                "win_rate":       wr,
                "max_drawdown":   dd,
                "net_pnl":        m["net_pnl"],
                "total_trades":   m["total_trades"],
                "sharpe":         m["sharpe_ratio"],
                "score":          score,
            })
        except Exception as e:
            print(f"ERROR: {e}")
            continue

    if not results:
        print("No valid results found.")
        return []

    # Sort by score (profit factor, DD-filtered)
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    print("\n" + "=" * 60)
    print(f"  TOP {top_n} PARAMETER SETS — {symbol}")
    print("=" * 60)

    for rank, r in enumerate(top, 1):
        print(f"\n  #{rank}  Score={r['score']:.2f}  PF={r['profit_factor']:.2f}"
              f"  WR={r['win_rate']:.1f}%  DD={r['max_drawdown']:.1f}%"
              f"  Trades={r['total_trades']}  NetPnL=${r['net_pnl']:.2f}")
        for k, v in r["params"].items():
            print(f"        {k}: {v}")

    print("\n  Best parameters to use in MT5 bot:")
    best = top[0]["params"]
    print(f"    EMA_Fast      = {best.get('EMA_Fast', DEFAULT_PARAMS['EMA_Fast'])}")
    print(f"    EMA_Slow      = {best.get('EMA_Slow', DEFAULT_PARAMS['EMA_Slow'])}")
    print(f"    RSI_Period    = {best.get('RSI_Period', DEFAULT_PARAMS['RSI_Period'])}")
    print(f"    ATR_SL_Multi  = {best.get('ATR_SL_Multi', DEFAULT_PARAMS['ATR_SL_Multi'])}")
    print(f"    RequiredScore = {best.get('RequiredScore', DEFAULT_PARAMS['RequiredScore'])}")

    return top


def main():
    parser = argparse.ArgumentParser(description="ScalpMaster HFT Parameter Optimizer")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to optimize")
    parser.add_argument("--months", type=int, default=3,  help="Months of M1 history")
    parser.add_argument("--top",    type=int, default=5,  help="Show top N results")
    args = parser.parse_args()

    if not connect():
        sys.exit(1)

    grid_search(args.symbol.upper(), args.months, args.top)

    disconnect()


if __name__ == "__main__":
    main()
