"""
NGS_Range (Phase 7D) — regime-gated averaging grid.

Hypothesis from data: NGS_Grid has REAL mean-reversion edge in ranging
markets (live: 89 trades @ PF 2.63) and BLOWS UP in trending ones (live:
786 trades @ PF 0.85, -24% account). ADX-based regime filter should:
  - block new grid when ADX > AdxEntryMax (no range)
  - escape (close all) when ADX > AdxEscapeMin AND rising (trend onset)

If this passes the gate (PF > 1.2, DD <= 15% post-cost), it's the first
NextGen variant in 6 phases to genuinely capture the live edge under
backtest discipline.
"""
import sys
import pandas as pd
import MetaTrader5 as mt5

import backtest_runner as br
from backtest_runner import (
    Trade, INIT_BALANCE, pip_size, ema_series, compute_stats,
)
from optimize_ngs_pyramid_v2 import adx_series


def backtest_ngs_range(data, symbol="XAUUSD",
                       grid_gap_pips=15.0,
                       base_lot=0.01,
                       max_layers=4,
                       adx_tf_key="m15",
                       adx_period=14,
                       adx_entry_max=20.0,
                       adx_escape_min=25.0,
                       adx_rise_lookback=3,
                       cooldown_bars_m5=12,
                       ma_fast=20, ma_slow=50,
                       sl_per_pos_pips=150.0,
                       basket_tp_usd=3.0,
                       max_dd_pct=8.0):
    print(f"  Range {symbol}: gap={grid_gap_pips}p maxL={max_layers} "
          f"ADX entry<={adx_entry_max} escape>={adx_escape_min} "
          f"basket=${basket_tp_usd} maxDD={max_dd_pct}%")

    m5  = data["m5"].copy()
    mtf = data[adx_tf_key].copy()
    mtf["ma_f"] = ema_series(mtf["close"], ma_fast)
    mtf["ma_s"] = ema_series(mtf["close"], ma_slow)
    mtf["adx"]  = adx_series(mtf, adx_period)

    pip = pip_size(symbol)
    info = mt5.symbol_info(symbol)
    if info is None: return []
    tick_val, tick_sz = info.trade_tick_value, info.trade_tick_size

    def usd(pips_v, lot_v):
        if tick_sz <= 0: return 0.0
        return pips_v * pip / tick_sz * tick_val * lot_v

    def close_one(p, exit_price, exit_time, reason, out):
        fp = ((exit_price - p["entry"]) / pip
              if p["dir"] == 1 else (p["entry"] - exit_price) / pip)
        out.append(Trade(p["open_time"], exit_time,
                         "BUY" if p["dir"] == 1 else "SELL",
                         p["entry"], exit_price, p["lot"],
                         fp, usd(fp, p["lot"]), reason, "NGS_Range"))

    trades, positions = [], []
    balance = INIT_BALANCE
    equity_peak = balance
    halted = False
    cooldown_until_i = 0          # M5 bar index for cool-down
    mtf_idx = mtf.index

    def adx_at(ts):
        pos = mtf_idx.searchsorted(ts, side="right") - 2
        if pos < adx_period + 1: return None
        v = mtf.iloc[pos]["adx"]
        return None if pd.isna(v) else v

    def adx_rising(ts):
        pos = mtf_idx.searchsorted(ts, side="right") - 2
        if pos < adx_rise_lookback + 1: return False
        recent = mtf.iloc[pos]["adx"]
        old    = mtf.iloc[pos - adx_rise_lookback]["adx"]
        if pd.isna(recent) or pd.isna(old): return False
        return recent > old

    def trend_dir(ts):
        pos = mtf_idx.searchsorted(ts, side="right") - 2
        if pos < ma_slow + 2: return 0
        r = mtf.iloc[pos]
        if pd.isna(r["ma_f"]) or pd.isna(r["ma_s"]): return 0
        return 1 if r["ma_f"] > r["ma_s"] else -1

    for i in range(60, len(m5)):
        ts   = m5.index[i]
        bar  = m5.iloc[i]
        high, low, close = bar["high"], bar["low"], bar["close"]

        # 1) DD kill-switch
        floating = sum(usd((close - p["entry"]) / pip if p["dir"] == 1
                           else (p["entry"] - close) / pip, p["lot"])
                       for p in positions)
        equity = balance + floating
        if equity > equity_peak: equity_peak = equity
        dd = (equity_peak - equity) / equity_peak * 100 if equity_peak > 0 else 0
        if dd >= max_dd_pct:
            for p in positions:
                close_one(p, close, ts, "DD_KILL", trades)
                balance += usd((close - p["entry"]) / pip if p["dir"] == 1
                               else (p["entry"] - close) / pip, p["lot"])
            positions, halted = [], True
            continue
        if halted: continue

        # 2) per-position SL via bar high/low
        survivors = []
        for p in positions:
            hit = (p["dir"] == 1 and low <= p["sl_price"]) or \
                  (p["dir"] == -1 and high >= p["sl_price"])
            if hit:
                close_one(p, p["sl_price"], ts, "SL", trades)
                balance += usd((p["sl_price"] - p["entry"]) / pip if p["dir"] == 1
                               else (p["entry"] - p["sl_price"]) / pip, p["lot"])
            else:
                survivors.append(p)
        positions = survivors

        # 3) basket TP via bar close
        if positions:
            floating = sum(usd((close - p["entry"]) / pip if p["dir"] == 1
                               else (p["entry"] - close) / pip, p["lot"])
                           for p in positions)
            if floating >= basket_tp_usd:
                for p in positions:
                    close_one(p, close, ts, "BasketTP", trades)
                    balance += usd((close - p["entry"]) / pip if p["dir"] == 1
                                   else (p["entry"] - close) / pip, p["lot"])
                positions = []
                continue

        # 4) ADX ESCAPE — close all if regime turned to trend
        if positions:
            adxv = adx_at(ts)
            if adxv is not None and adxv >= adx_escape_min and adx_rising(ts):
                for p in positions:
                    close_one(p, close, ts, "ADX_Escape", trades)
                    balance += usd((close - p["entry"]) / pip if p["dir"] == 1
                                   else (p["entry"] - close) / pip, p["lot"])
                positions = []
                cooldown_until_i = i + cooldown_bars_m5
                continue

        if len(positions) >= max_layers: continue
        if i < cooldown_until_i: continue

        # 5) ENTRY — ADX gate + trend direction
        if not positions:
            adxv = adx_at(ts)
            if adxv is None or adxv > adx_entry_max:
                continue        # not ranging — skip new grid
            trend = trend_dir(ts)
            if trend == 0: continue
            entry = close
            sl_px = entry - sl_per_pos_pips * pip if trend == 1 \
                    else entry + sl_per_pos_pips * pip
            positions.append({"dir": trend, "entry": entry, "lot": base_lot,
                              "sl_price": sl_px, "open_time": ts})
        else:
            d = positions[0]["dir"]
            if d == 1:
                worst = min(p["entry"] for p in positions)
                fire  = close <= worst - grid_gap_pips * pip
            else:
                worst = max(p["entry"] for p in positions)
                fire  = close >= worst + grid_gap_pips * pip
            if fire:
                entry = close
                sl_px = entry - sl_per_pos_pips * pip if d == 1 \
                        else entry + sl_per_pos_pips * pip
                positions.append({"dir": d, "entry": entry, "lot": base_lot,
                                  "sl_price": sl_px, "open_time": ts})

    last_ts = m5.index[-1]; last_close = m5.iloc[-1]["close"]
    for p in positions:
        close_one(p, last_close, last_ts, "EndOfData", trades)
        balance += usd((last_close - p["entry"]) / pip if p["dir"] == 1
                       else (p["entry"] - last_close) / pip, p["lot"])
    return trades


SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]

CONFIGS = [
    # gap maxL adxIn adxEsc basket maxDD
    (10, 4, 20, 25,  3.0, 8.0),
    (15, 4, 20, 25,  3.0, 8.0),
    (15, 4, 18, 23,  3.0, 8.0),    # stricter range
    (15, 3, 20, 25,  5.0, 8.0),
    (20, 4, 20, 25,  3.0, 8.0),
    (15, 5, 22, 28,  5.0, 10.0),   # looser range, higher TP target
    (10, 3, 18, 22,  3.0, 6.0),    # tightest discipline
    (15, 4, 20, 25,  5.0, 10.0),
]


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    print("=== NGS_Range (Phase 7D) — DD<=15% gate ===")
    print(f"  {'Symbol':8} {'gap':>4} {'mxL':>4} {'adxI':>5} {'adxE':>5} "
          f"{'bsk$':>5} {'mDD%':>5} {'Tr':>6} {'WR%':>6} {'PF':>6} "
          f"{'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 90)
    winners = []
    for sym in SYMBOLS:
        info = mt5.symbol_info(sym)
        if info is None: print(f"  {sym} (not on broker)"); continue
        if not info.visible: mt5.symbol_select(sym, True)
        data = {
            "m5":  br.get_rates(sym, mt5.TIMEFRAME_M5),
            "m15": br.get_rates(sym, mt5.TIMEFRAME_M15),
        }
        if data["m5"].empty: print(f"  {sym} (no data)"); continue
        for gap, mxL, adxIn, adxE, bsk, mDD in CONFIGS:
            trades = backtest_ngs_range(
                data, symbol=sym,
                grid_gap_pips=gap, max_layers=mxL,
                adx_entry_max=adxIn, adx_escape_min=adxE,
                basket_tp_usd=bsk, max_dd_pct=mDD)
            if not trades:
                print(f"  {sym:8} {gap:>4} {mxL:>4} {adxIn:>5} {adxE:>5} "
                      f"{bsk:>5.1f} {mDD:>5.1f}  (no trades)")
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
            print(f"  {sym:8} {gap:>4} {mxL:>4} {adxIn:>5} {adxE:>5} "
                  f"{bsk:>5.1f} {mDD:>5.1f} {st['total_trades']:>6} "
                  f"{st['win_rate']:>6.1f} {st['profit_factor']:>6.2f} "
                  f"{st['net_profit_pct']:>+8.1f} {st['max_drawdown']:>6.1f}  {tag}")
            if ok:
                winners.append(((sym, gap, mxL, adxIn, adxE, bsk, mDD), st))
    print("  " + "-" * 90)
    if winners:
        print(f"\n  PHASE 7D GATE: PASSED — {len(winners)} viable config(s)")
        for cfg, st in winners:
            sym, gap, mxL, adxIn, adxE, bsk, mDD = cfg
            print(f"   {sym}: gap={gap}p maxL={mxL} adxEntry<={adxIn} "
                  f"adxEsc>={adxE} basket=${bsk} maxDD={mDD}% -> "
                  f"Ret {st['net_profit_pct']:+.1f}% PF {st['profit_factor']:.2f} "
                  f"DD {st['max_drawdown']:.1f}% trades {st['total_trades']}")
    else:
        print("\n  PHASE 7D GATE: FAILED — NGS_Range also below PF 1.2.")
        print("  This was the last reasonable NextGen iteration. NextGen Grid")
        print("  family is structurally unable to clear real-cost gate on these")
        print("  instruments/spreads. Honest call: declare NextGen tested.")
    mt5.shutdown()


if __name__ == "__main__":
    main()
