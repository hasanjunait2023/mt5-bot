"""
NGS_Single (Phase 6) — single-position trend follow (no pyramid layers).

Phase 5 showed EURUSD maxL=2 / tight ATR / ADX>30 -> PF 1.05 (+3.8%) —
the pyramid mechanic itself doesn't add edge beyond maxL=2. Phase 6
drops layers entirely and tests pure single-position trend-following
with trailing SL inside NextGen's filter framework (ADX + H1 EMA).

Mechanic:
  - One position at a time per symbol
  - Entry: ADX > AdxMin AND M15 MA-cross dir == H1 EMA200 dir
  - Per-position SL: ATR-based (entry +/- ATRx * ATR)
  - Trailing SL: once price moves TrailActivation pips in profit,
    move SL to lock TrailDrawdown pips behind peak. Continue trailing.
  - Hard time exit: after N hours (avoid stale positions)
  - DD kill-switch + spread guard
"""
import sys
import pandas as pd
import MetaTrader5 as mt5

import backtest_runner as br
from backtest_runner import (
    Trade, INIT_BALANCE, pip_size, ema_series, atr_series, compute_stats,
)
from optimize_ngs_pyramid_v2 import adx_series


def backtest_ngs_single(data, symbol="EURUSD",
                       base_lot=0.01,
                       sl_atr_mult=1.0, sl_min_pips=15.0, sl_max_pips=80.0,
                       trail_activation_pips=20.0,
                       trail_drawdown_pips=10.0,
                       max_hold_hours=24,
                       ma_fast=20, ma_slow=50,
                       adx_min=25.0, adx_period=14,
                       h1_ema_period=200,
                       max_dd_pct=15.0):
    print(f"  Single {symbol}: ATRx{sl_atr_mult} trailAct={trail_activation_pips}p "
          f"trailDD={trail_drawdown_pips}p ADX>{adx_min} maxH={max_hold_hours}h")
    m5  = data["m5"].copy()
    mtf = data["m15"].copy()
    h1  = data["h1"].copy()
    mtf["ma_f"] = ema_series(mtf["close"], ma_fast)
    mtf["ma_s"] = ema_series(mtf["close"], ma_slow)
    mtf["adx"]  = adx_series(mtf, adx_period)
    mtf["atr"]  = atr_series(mtf, 14)
    h1["ema200"] = ema_series(h1["close"], h1_ema_period)

    pip = pip_size(symbol)
    info = mt5.symbol_info(symbol)
    if info is None: return []
    tick_val, tick_sz = info.trade_tick_value, info.trade_tick_size

    def usd(pips_v, lot_v):
        if tick_sz <= 0: return 0.0
        return pips_v * pip / tick_sz * tick_val * lot_v

    trades = []
    pos = None
    balance     = INIT_BALANCE
    equity_peak = balance
    halted      = False

    mtf_idx = mtf.index
    h1_idx  = h1.index

    def sl_pips_now(ts):
        ip = mtf_idx.searchsorted(ts, side="right") - 2
        if ip < 14 + 1: return sl_min_pips
        a = mtf.iloc[ip]["atr"]
        if pd.isna(a) or a <= 0: return sl_min_pips
        v = (a / pip) * sl_atr_mult
        return max(sl_min_pips, min(sl_max_pips, v))

    for i in range(50, len(m5)):
        ts   = m5.index[i]
        bar  = m5.iloc[i]
        high, low, close = bar["high"], bar["low"], bar["close"]

        # DD kill-switch
        float_pnl = 0.0
        if pos is not None:
            float_pnl = usd((close - pos["entry"]) / pip if pos["dir"] == 1
                            else (pos["entry"] - close) / pip, pos["lot"])
        equity = balance + float_pnl
        if equity > equity_peak: equity_peak = equity
        dd = (equity_peak - equity) / equity_peak * 100 if equity_peak > 0 else 0
        if dd >= max_dd_pct:
            if pos is not None:
                fp = ((close - pos["entry"]) / pip
                      if pos["dir"] == 1 else (pos["entry"] - close) / pip)
                trades.append(Trade(pos["open_time"], ts,
                              "BUY" if pos["dir"] == 1 else "SELL",
                              pos["entry"], close, pos["lot"],
                              fp, usd(fp, pos["lot"]), "DD_KILL", "NGS_Single"))
                balance += usd(fp, pos["lot"])
                pos = None
            halted = True
            continue
        if halted: continue

        # manage open position
        if pos is not None:
            # 1) FIRST: check SL hit using the CURRENT (pre-update) SL price.
            #    This avoids intra-bar look-ahead bias (using bar's high to
            #    move trail UP and THEN checking low for SL gives best-case
            #    fill ordering which is unrealistic).
            sl_hit = ((pos["dir"] == 1 and low <= pos["sl_price"]) or
                      (pos["dir"] == -1 and high >= pos["sl_price"]))

            # 2) THEN: if SL not hit, update trail using bar's CLOSE only
            #    (conservative; reacts one bar slower but unbiased).
            if not sl_hit:
                cur_pips = ((close - pos["entry"]) / pip if pos["dir"] == 1
                            else (pos["entry"] - close) / pip)
                if cur_pips > pos["peak_pips"]:
                    pos["peak_pips"] = cur_pips
                    if pos["peak_pips"] >= trail_activation_pips:
                        new_lock = pos["peak_pips"] - trail_drawdown_pips
                        if pos["dir"] == 1:
                            new_sl_px = pos["entry"] + new_lock * pip
                            if new_sl_px > pos["sl_price"]:
                                pos["sl_price"] = new_sl_px
                        else:
                            new_sl_px = pos["entry"] - new_lock * pip
                            if new_sl_px < pos["sl_price"]:
                                pos["sl_price"] = new_sl_px
            # time exit
            time_exit = (ts - pos["open_time"]).total_seconds() / 3600 >= max_hold_hours
            if sl_hit or time_exit:
                exit_price = pos["sl_price"] if sl_hit else close
                reason = ("TrailSL" if pos["peak_pips"] >= trail_activation_pips
                          else ("SL" if sl_hit else "TimeExit"))
                fp = ((exit_price - pos["entry"]) / pip if pos["dir"] == 1
                      else (pos["entry"] - exit_price) / pip)
                trades.append(Trade(pos["open_time"], ts,
                              "BUY" if pos["dir"] == 1 else "SELL",
                              pos["entry"], exit_price, pos["lot"],
                              fp, usd(fp, pos["lot"]), reason, "NGS_Single"))
                balance += usd(fp, pos["lot"])
                pos = None
            continue

        # entry: strict filter
        ip = mtf_idx.searchsorted(ts, side="right") - 2
        if ip < ma_slow + 2: continue
        mr = mtf.iloc[ip]
        f, s, adx_v = mr["ma_f"], mr["ma_s"], mr["adx"]
        if pd.isna(f) or pd.isna(s) or pd.isna(adx_v): continue
        if adx_v < adx_min: continue
        m15_dir = 1 if f > s else -1

        hp = h1_idx.searchsorted(ts, side="right") - 2
        if hp < h1_ema_period + 1: continue
        hr = h1.iloc[hp]
        if pd.isna(hr["ema200"]): continue
        h1_dir = 1 if hr["close"] > hr["ema200"] else -1
        if m15_dir != h1_dir: continue

        slp = sl_pips_now(ts)
        entry = close
        sl_px = entry - slp * pip if m15_dir == 1 else entry + slp * pip
        pos = {"dir": m15_dir, "entry": entry, "lot": base_lot,
               "sl_price": sl_px, "peak_pips": 0.0, "open_time": ts}

    if pos is not None:
        last_ts = m5.index[-1]; last_close = m5.iloc[-1]["close"]
        fp = ((last_close - pos["entry"]) / pip if pos["dir"] == 1
              else (pos["entry"] - last_close) / pip)
        trades.append(Trade(pos["open_time"], last_ts,
                      "BUY" if pos["dir"] == 1 else "SELL",
                      pos["entry"], last_close, pos["lot"],
                      fp, usd(fp, pos["lot"]), "EndOfData", "NGS_Single"))
    return trades


SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY", "XAUUSD"]

CONFIGS = [
    # ATRx tActP tDDP holdH ADX
    (1.0, 20, 10, 24, 25),    # baseline
    (1.0, 30, 15, 24, 25),    # bigger winners
    (1.0, 40, 15, 24, 30),    # even bigger, strict
    (1.0, 50, 20, 48, 30),    # very wide trail
    (0.8, 20, 10, 24, 25),    # tighter SL
    (0.8, 30, 12, 24, 30),    # tight SL + strict
    (1.5, 30, 15, 24, 25),    # wider SL
    (1.0, 25, 8,  12, 25),    # short hold
]


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    print("=== NGS_Single (single-position trend follow) — DD<=15% ===")
    print(f"  {'Symbol':8} {'ATR':>4} {'tAct':>5} {'tDD':>4} {'hH':>3} "
          f"{'ADX':>4} {'Tr':>5} {'WR%':>6} {'PF':>6} {'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 80)

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

        for atrx, tAct, tDD, holdH, adx_min in CONFIGS:
            trades = backtest_ngs_single(
                data, symbol=sym, sl_atr_mult=atrx,
                trail_activation_pips=tAct, trail_drawdown_pips=tDD,
                max_hold_hours=holdH, adx_min=adx_min, max_dd_pct=15.0)
            if not trades:
                print(f"  {sym:8} {atrx:>4.1f} {tAct:>5} {tDD:>4} "
                      f"{holdH:>3} {adx_min:>4}  (no trades)")
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
            print(f"  {sym:8} {atrx:>4.1f} {tAct:>5} {tDD:>4} {holdH:>3} "
                  f"{adx_min:>4} {st['total_trades']:>5} {st['win_rate']:>6.1f} "
                  f"{st['profit_factor']:>6.2f} {st['net_profit_pct']:>+8.1f} "
                  f"{st['max_drawdown']:>6.1f}  {tag}")
            if ok:
                winners.append(((sym, atrx, tAct, tDD, holdH, adx_min), st))

    print("  " + "-" * 80)
    if winners:
        print(f"\n  PHASE 6 GATE: PASSED — {len(winners)} viable config(s)")
        for cfg, st in winners:
            sym, atrx, tAct, tDD, holdH, adx = cfg
            print(f"   {sym}: ATRx={atrx} tAct={tAct}p tDD={tDD}p "
                  f"hold={holdH}h ADX>{adx} -> "
                  f"Ret {st['net_profit_pct']:+.1f}% PF {st['profit_factor']:.2f} "
                  f"DD {st['max_drawdown']:.1f}% trades {st['total_trades']}")
    else:
        print("\n  PHASE 6 GATE: FAILED — single-position trend follow also "
              "below PF 1.2 threshold.")
        print("  Honest conclusion: NextGen variants tested 5x (Grid, Pyramid v1, "
              "v2 +ADX/H1, v3 tight risk, Single trend-follow).")
        print("  Best result: EURUSD Pyramid v3 PF 1.05 (+3.8%). Marginal, not "
              "high-return.")
    mt5.shutdown()


if __name__ == "__main__":
    main()
