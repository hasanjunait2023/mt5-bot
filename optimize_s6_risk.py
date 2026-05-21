"""
S6v2 risk sweep — find the highest-return RiskPct that keeps post-cost
max drawdown within the project ceiling (20%). Pure leverage scaling:
the edge (entry/exit) is untouched, so this is honest tuning, not
curve-fitting. Costs ARE applied (compute_stats deducts spread).
"""
import sys
import backtest_runner as br
import MetaTrader5 as mt5

DD_CEILING = 20.0          # project risk rule: max drawdown %

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error()); sys.exit(1)

print("Loading XAUUSD data (M15 + H4)...")
data = {
    "m15": br.get_rates("XAUUSD", mt5.TIMEFRAME_M15),
    "h4":  br.get_rates("XAUUSD", mt5.TIMEFRAME_H4),
}
# NOTE: keep MT5 connected — backtest_s6_v2 calls mt5.symbol_info() for
# tick value/size internally; shutting down here yields 0 trades.

print(f"\n  S6v2 RISK SWEEP (post-cost, spread {br.SPREAD_PIPS}p) "
      f"| DD ceiling {DD_CEILING}%")
print("  " + "-" * 60)
print(f"  {'Risk%':>6} {'Trades':>7} {'WR%':>6} {'PF':>6} "
      f"{'Return%':>9} {'MaxDD%':>7}  ok?")
print("  " + "-" * 60)

rows = []
for risk in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
    br.S6_RISK_PCT = risk
    trades = br.backtest_s6_v2(data)
    st = br.compute_stats(trades, br.INIT_BALANCE)
    if "error" in st:
        print(f"  {risk:>6.2f}  no trades"); continue
    ok = st["max_drawdown"] <= DD_CEILING and st["net_profit_pct"] > 0
    rows.append((risk, st))
    print(f"  {risk:>6.2f} {st['total_trades']:>7} {st['win_rate']:>6.1f} "
          f"{st['profit_factor']:>6.2f} {st['net_profit_pct']:>+9.1f} "
          f"{st['max_drawdown']:>7.1f}  {'YES' if ok else 'no'}")

print("  " + "-" * 60)
viable = [(r, s) for r, s in rows
          if s["max_drawdown"] <= DD_CEILING and s["net_profit_pct"] > 0]
if viable:
    best = max(viable, key=lambda x: x[1]["net_profit_pct"])
    print(f"  BEST within DD<={DD_CEILING}%:  RiskPct={best[0]}  "
          f"-> Return {best[1]['net_profit_pct']:+.1f}%  "
          f"PF {best[1]['profit_factor']:.2f}  DD {best[1]['max_drawdown']:.1f}%")
else:
    print("  No risk level stays profitable within the DD ceiling.")

mt5.shutdown()
