"""
NGS_Pyramid multi-symbol test (Phase 3B).

XAUUSD M5 failed the gate (0/81 configs). Hypothesis: XAUUSD M5 is too
choppy for pyramid momentum capture. Test the SAME engine on FX majors
that S6 found momentum-friendly: EURUSD, USDJPY, GBPUSD, EURJPY, GBPJPY.

Pass criteria: PF > 1.2, DD <= 15% post-cost (symbol-aware spread).
If even one symbol passes -> momentum capture path validated; deploy
on winners. If all fail -> NGS family is dead, pivot to S6 multi-symbol.
"""
import sys
import MetaTrader5 as mt5

import backtest_runner as br
from backtest_runner import INIT_BALANCE, compute_stats
from optimize_ngs_pyramid import backtest_ngs_pyramid

SYMBOLS = ["EURUSD", "USDJPY", "GBPUSD", "EURJPY", "GBPJPY", "XAUUSD"]

# focused config set — gap & trailing variants only (ATRx/maxL had
# little effect on XAUUSD per Phase 2; keep them at sane mid values)
CONFIGS = [
    # (gap_pips, max_layers, atr_mult, trail_act, trail_dd)
    (15, 6, 1.5,  3.0, 2.0),
    (15, 6, 1.5,  5.0, 3.0),
    (25, 6, 1.5,  5.0, 3.0),
    (25, 6, 1.5, 10.0, 5.0),
    (40, 6, 1.5, 10.0, 5.0),
]


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)

    print(f"\n=== NGS_Pyramid multi-symbol (post-cost, DD-ceiling 15%) ===")
    print(f"  {'Symbol':8} {'gap':>4} {'maxL':>4} {'tAct':>5} {'tDD':>5} "
          f"{'Trades':>7} {'WR%':>6} {'PF':>6} {'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 76)

    winners = []
    for sym in SYMBOLS:
        info = mt5.symbol_info(sym)
        if info is None:
            print(f"  {sym:8} (not on broker)"); continue
        if not info.visible: mt5.symbol_select(sym, True)
        data = {
            "m5":  br.get_rates(sym, mt5.TIMEFRAME_M5),
            "m15": br.get_rates(sym, mt5.TIMEFRAME_M15),
        }
        if data["m5"].empty or data["m15"].empty:
            print(f"  {sym:8} (no data)"); continue

        sym_best = None
        for gap, maxL, atrx, tAct, tDD in CONFIGS:
            trades = backtest_ngs_pyramid(
                data, symbol=sym,
                grid_gap_pips=gap, max_layers=maxL,
                sl_atr_mult=atrx,
                trail_activation_usd=tAct, trail_drawdown_usd=tDD,
                max_dd_pct=15.0)
            if not trades:
                print(f"  {sym:8} {gap:>4} {maxL:>4} {tAct:>5.1f} {tDD:>5.1f}  (no trades)")
                continue
            st = compute_stats(trades, INIT_BALANCE, sym)
            if "error" in st: continue
            # symbol-relative artifact guard (price-%-move)
            max_move = max(abs(t.exit_price - t.entry_price) / t.entry_price * 100
                           for t in trades if t.entry_price)
            artifact = max_move > 20.0 or st["profit_factor"] > 50
            ok = (not artifact and st["profit_factor"] > 1.2
                  and st["max_drawdown"] <= 15.0
                  and st["net_profit_pct"] > 0)
            tag = "ART" if artifact else ("YES" if ok else "no")
            print(f"  {sym:8} {gap:>4} {maxL:>4} {tAct:>5.1f} {tDD:>5.1f} "
                  f"{st['total_trades']:>7} {st['win_rate']:>6.1f} "
                  f"{st['profit_factor']:>6.2f} {st['net_profit_pct']:>+8.1f} "
                  f"{st['max_drawdown']:>6.1f}  {tag}")
            if ok:
                if sym_best is None or st["net_profit_pct"] > sym_best[1]["net_profit_pct"]:
                    sym_best = ((sym, gap, maxL, atrx, tAct, tDD), st)
        if sym_best:
            winners.append(sym_best)

    print("  " + "-" * 76)
    if winners:
        print(f"\n  PHASE 3B GATE: PASSED — {len(winners)} symbol(s) viable:")
        for cfg, st in winners:
            sym, gap, maxL, atrx, tAct, tDD = cfg
            print(f"   {sym}: gap={gap}p maxL={maxL} ATRx={atrx} "
                  f"tAct=${tAct} tDD=${tDD} -> "
                  f"Ret {st['net_profit_pct']:+.1f}% PF {st['profit_factor']:.2f} "
                  f"DD {st['max_drawdown']:.1f}% trades {st['total_trades']}")
    else:
        print("\n  PHASE 3B GATE: FAILED — NGS_Pyramid has no edge on any "
              "tested symbol. NGS family officially blocked by real-cost gate.")
        print("  Recommended pivot: deploy validated S6 multi-symbol (PF 1.38-1.89, 7 symbols).")
    mt5.shutdown()


if __name__ == "__main__":
    main()
