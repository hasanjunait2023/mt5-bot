"""
Report generator — runs backtest on all 3 symbols and shows comparison.

Usage:
    python report.py --months 3
    python report.py --months 1 --chart   (requires matplotlib)
"""

import argparse
import sys

import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect
from backtest import run, print_results
from config import DEFAULT_PARAMS


SYMBOLS = ["EURUSD", "XAUUSD", "BTCUSD"]


def compare_symbols(months: int, show_chart: bool = False):
    summary = []

    for symbol in SYMBOLS:
        print(f"\n{'='*55}")
        print(f"  Running backtest: {symbol}")
        print(f"{'='*55}")
        result = run(symbol, months)
        print_results(result)
        m = result.get("metrics", {})
        if "error" not in m:
            summary.append({
                "Symbol":        symbol,
                "Trades":        m["total_trades"],
                "WinRate%":      m["win_rate_pct"],
                "ProfitFactor":  m["profit_factor"],
                "NetPnL$":       m["net_pnl"],
                "MaxDD%":        m["max_drawdown_pct"],
                "Sharpe":        m["sharpe_ratio"],
                "FinalBalance$": m["final_balance"],
            })

    print("\n" + "=" * 70)
    print("  SUMMARY COMPARISON")
    print("=" * 70)
    print(f"  {'Symbol':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'PnL$':>8} {'DD%':>6} {'Sharpe':>7}")
    print("-" * 70)
    for r in summary:
        print(f"  {r['Symbol']:<10} {r['Trades']:>7} {r['WinRate%']:>6.1f} "
              f"{r['ProfitFactor']:>6.2f} {r['NetPnL$']:>8.2f} "
              f"{r['MaxDD%']:>6.2f} {r['Sharpe']:>7.2f}")
    print("=" * 70)

    if summary:
        best = max(summary, key=lambda x: x["ProfitFactor"] if x["MaxDD%"] < 20 else 0)
        print(f"\n  Best symbol: {best['Symbol']}"
              f"  (PF={best['ProfitFactor']:.2f}, DD={best['MaxDD%']:.1f}%)")

    if show_chart:
        try:
            plot_equity_curves(months)
        except ImportError:
            print("\n(Install matplotlib to see equity charts: pip install matplotlib)")


def plot_equity_curves(months: int):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(SYMBOLS), figsize=(16, 5))
    fig.suptitle(f"ScalpMaster HFT — Equity Curves ({months} months)", fontsize=13)

    for ax, symbol in zip(axes, SYMBOLS):
        result = run(symbol, months)
        trades = result.get("trades")
        m      = result.get("metrics", {})
        if trades is None or trades.empty or "error" in m:
            ax.set_title(f"{symbol}\nNo data")
            continue

        equity = trades["pnl"].cumsum() + DEFAULT_PARAMS["InitialBalance"]
        ax.plot(equity.values, color="green" if equity.iloc[-1] > DEFAULT_PARAMS["InitialBalance"] else "red")
        ax.axhline(DEFAULT_PARAMS["InitialBalance"], color="gray", linestyle="--", linewidth=0.8)
        ax.set_title(f"{symbol}\nPF={m['profit_factor']:.2f}  WR={m['win_rate_pct']}%  DD={m['max_drawdown_pct']}%")
        ax.set_xlabel("Trade #")
        ax.set_ylabel("Balance ($)")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("equity_report.png", dpi=150)
    print("\nChart saved: equity_report.png")
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="ScalpMaster HFT — Full Symbol Report")
    parser.add_argument("--months", type=int, default=3,   help="Months of history")
    parser.add_argument("--chart",  action="store_true",   help="Show equity curve chart")
    args = parser.parse_args()

    if not connect():
        sys.exit(1)

    compare_symbols(args.months, args.chart)

    disconnect()


if __name__ == "__main__":
    main()
