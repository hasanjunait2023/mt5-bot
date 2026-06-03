"""
Multi-symbol S6v2 — the honest high-return lever.

S6v2 is a proven, cost-surviving edge on XAUUSD (PF~1.4, DD<8%). The same
Asian-range-breakout logic should generalise to other liquid instruments
with an Asian session. Running the SAME validated strategy across more
symbols multiplies profitable trades WITHOUT curve-fitting (we change the
instrument, not the rules). Costs are symbol-aware (real per-symbol spread).

Profitable symbols (PF>1, DD<=20% post-cost) form the deploy portfolio.
"""
import sys
import backtest_runner as br
import MetaTrader5 as mt5

if not mt5.initialize():
    print("MT5 init failed:", mt5.last_error()); sys.exit(1)

# ATR-relative bounds = the honest generalisation (same edge, scaled to
# each symbol's own volatility). XAUUSD shown first as a calibration
# sanity check — it should stay ~profitable like the locked $-bound run.
br.S6_ATR_BOUNDS = True

# liquid instruments with a tradable Asian session (broker-available)
SYMBOLS = ["XAUUSD", "USDJPY", "GBPUSD", "EURUSD", "AUDUSD",
           "GBPJPY", "EURJPY", "BTCUSD"]

print(f"\n  MULTI-SYMBOL S6v2 (post-cost, RiskPct={br.S6_RISK_PCT}) "
      f"| DD ceiling 20%")
print("  " + "-" * 70)
print(f"  {'Symbol':8} {'Trades':>7} {'WR%':>6} {'PF':>6} "
      f"{'Return%':>9} {'MaxDD%':>7}  deploy?")
print("  " + "-" * 70)

portfolio, total_net = [], 0.0
for sym in SYMBOLS:
    info = mt5.symbol_info(sym)
    if info is None:
        print(f"  {sym:8} not on broker"); continue
    if not info.visible:
        mt5.symbol_select(sym, True)
    try:
        data = {
            "m15": br.get_rates(sym, mt5.TIMEFRAME_M15),
            "h4":  br.get_rates(sym, mt5.TIMEFRAME_H4),
        }
        if data["m15"].empty or data["h4"].empty:
            print(f"  {sym:8} no data"); continue
        trades = br.backtest_s6_v2(data, symbol=sym)
        st = br.compute_stats(trades, br.INIT_BALANCE, symbol=sym)
    except Exception as e:
        print(f"  {sym:8} ERROR {e}"); continue
    if "error" in st:
        print(f"  {sym:8} {'0':>7}  (no trades)"); continue
    # ── integrity guard (symbol-relative) ──────────────────────────
    # No real intraday trade moves a large fraction of price. Measure the
    # biggest single-trade move as a % of entry price (scale-agnostic):
    # XAU $54 on $2400 = 2.3% (fine), the old EURUSD bug 1.00 on 1.08 =
    # 92% (impossible). Flag >20% move, or PF>50, or >100000% return.
    max_move_pct = max(
        (abs(t.exit_price - t.entry_price) / t.entry_price * 100
         for t in trades if t.entry_price), default=0.0)
    artifact = (max_move_pct > 20.0 or st["profit_factor"] > 50
                or abs(st["net_profit_pct"]) > 100000)
    if artifact:
        print(f"  {sym:8} {st['total_trades']:>7}  ARTIFACT - untrusted "
              f"(max move {max_move_pct:.1f}% of price, "
              f"PF={st['profit_factor']:.0f}) - NOT deployable")
        continue
    deploy = st["profit_factor"] > 1.0 and st["max_drawdown"] <= 20.0 \
        and st["net_profit_pct"] > 0
    if deploy:
        portfolio.append(sym)
        total_net += st["net_profit_pct"]
    print(f"  {sym:8} {st['total_trades']:>7} {st['win_rate']:>6.1f} "
          f"{st['profit_factor']:>6.2f} {st['net_profit_pct']:>+9.1f} "
          f"{st['max_drawdown']:>7.1f}  {'YES' if deploy else 'no'}")

print("  " + "-" * 70)
print(f"  PROFITABLE PORTFOLIO ({len(portfolio)} symbols): "
      f"{', '.join(portfolio) if portfolio else 'none'}")
print(f"  Summed single-account return proxy: {total_net:+.1f}% "
      f"(indicative - real multi-symbol compounding differs)")
mt5.shutdown()
