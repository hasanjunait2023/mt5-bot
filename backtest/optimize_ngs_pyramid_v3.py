"""
NGS_Pyramid v3 (Phase 5) — TIGHTER risk + bigger winners.

Phase 4 v2 (ADX+H1) hit PF 0.97-0.98 on EURUSD/GBPUSD — close to break
but WR 30-42% means we need R/R > 1.5-1.9 for PF > 1.2. Current trailing
(tAct $5 / tDD $3 = 60% giveback) caps winners too early.

v3 changes:
  - Reduced maxLayers (2-3) so per-cycle loss is bounded
  - Tighter per-pos SL (ATRx 0.8-1.2) — smaller losers
  - Bigger TrailActivation + smaller giveback ratio — let winners extend
    further before activating trail, then give back less
  - Same v2 filter (ADX + H1 EMA)

Tested on Phase 4's near-misses: EURUSD, GBPUSD, USDJPY.
"""
import sys
import MetaTrader5 as mt5

import backtest_runner as br
from backtest_runner import INIT_BALANCE, compute_stats
from optimize_ngs_pyramid_v2 import backtest_ngs_pyramid_v2


SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY"]

# v3 configs — tight risk, big-winner trailing
CONFIGS = [
    # gap maxL ATRx tAct tDD adx — rationale
    (25, 2, 1.0, 15.0,  5.0, 25),   # 2-layer max, big winners (15→10 keep)
    (25, 3, 1.0, 15.0,  5.0, 25),   # 3-layer
    (40, 2, 1.0, 20.0,  7.0, 25),   # wider gap, bigger trail
    (40, 3, 1.0, 20.0,  7.0, 25),
    (25, 2, 0.8, 12.0,  4.0, 30),   # tighter SL + tighter trail
    (40, 2, 1.2, 25.0, 10.0, 30),   # max-extension trail
    (15, 2, 1.0, 10.0,  3.0, 25),   # fast cycles
    (25, 3, 1.0, 30.0, 10.0, 25),   # let very big runs develop
]


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    print("=== NGS_Pyramid v3 (tight risk + big winners) — DD<=15% ===")
    print(f"  {'Symbol':8} {'gap':>4} {'mxL':>4} {'ATR':>4} {'tAct':>5} "
          f"{'tDD':>5} {'ADX':>4} {'Tr':>6} {'WR%':>6} {'PF':>6} "
          f"{'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 88)

    winners = []
    for sym in SYMBOLS:
        info = mt5.symbol_info(sym)
        if info is None: print(f"  {sym} (not on broker)"); continue
        if not info.visible: mt5.symbol_select(sym, True)
        data = {
            "m5":  br.get_rates(sym, mt5.TIMEFRAME_M5),
            "m15": br.get_rates(sym, mt5.TIMEFRAME_M15),
            "h1":  br.get_rates(sym, mt5.TIMEFRAME_H1),
        }
        if data["m5"].empty: print(f"  {sym} (no data)"); continue

        for gap, maxL, atrx, tAct, tDD, adx_min in CONFIGS:
            trades = backtest_ngs_pyramid_v2(
                data, symbol=sym,
                grid_gap_pips=gap, max_layers=maxL, sl_atr_mult=atrx,
                trail_activation_usd=tAct, trail_drawdown_usd=tDD,
                max_dd_pct=15.0, adx_min=adx_min)
            if not trades:
                print(f"  {sym:8} {gap:>4} {maxL:>4} {atrx:>4.1f} "
                      f"{tAct:>5.1f} {tDD:>5.1f} {adx_min:>4}  (no trades)")
                continue
            st = compute_stats(trades, INIT_BALANCE, sym)
            if "error" in st: continue
            max_move = max(abs(t.exit_price - t.entry_price) / t.entry_price * 100
                           for t in trades if t.entry_price)
            artifact = max_move > 20.0 or st["profit_factor"] > 50
            ok = (not artifact and st["profit_factor"] > 1.2
                  and st["max_drawdown"] <= 15.0
                  and st["net_profit_pct"] > 0)
            tag = "ART" if artifact else ("YES" if ok else "no")
            print(f"  {sym:8} {gap:>4} {maxL:>4} {atrx:>4.1f} {tAct:>5.1f} "
                  f"{tDD:>5.1f} {adx_min:>4} {st['total_trades']:>6} "
                  f"{st['win_rate']:>6.1f} {st['profit_factor']:>6.2f} "
                  f"{st['net_profit_pct']:>+8.1f} {st['max_drawdown']:>6.1f}  {tag}")
            if ok:
                winners.append(((sym, gap, maxL, atrx, tAct, tDD, adx_min), st))

    print("  " + "-" * 88)
    if winners:
        print(f"\n  PHASE 5 GATE: PASSED — {len(winners)} viable config(s)")
        for cfg, st in winners:
            sym, gap, maxL, atrx, tAct, tDD, adx = cfg
            print(f"   {sym}: gap={gap}p maxL={maxL} ATRx={atrx} "
                  f"tAct=${tAct} tDD=${tDD} ADX>{adx} -> "
                  f"Ret {st['net_profit_pct']:+.1f}% PF {st['profit_factor']:.2f} "
                  f"DD {st['max_drawdown']:.1f}% trades {st['total_trades']}")
    else:
        print("\n  PHASE 5 GATE: FAILED — tight-risk variant still not enough.")
        print("  Next NextGen: drop pyramid mechanic entirely; single-position")
        print("  trend-follow with trailing SL (Phase 6 contingency).")
    mt5.shutdown()


if __name__ == "__main__":
    main()
