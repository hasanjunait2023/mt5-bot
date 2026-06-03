"""
NextGenSync_Grid real-cost backtest gate.

Same averaging-down grid + MA trend filter + basket TP + DD kill-switch
as the .mq5 EA. Run on XAUUSD M5 (2yr) with realistic spread (21 pip per
round-trip via backtest_runner.trade_cost). Validates whether the grid
has a real edge BEFORE any demo deployment — per the project discipline.
"""
import sys
from datetime import datetime
import MetaTrader5 as mt5
import pandas as pd

import backtest_runner as br
from backtest_runner import (
    Trade, INIT_BALANCE, pip_size, ema_series, compute_stats,
)


def backtest_ngs_grid(data: dict, symbol: str = "XAUUSD",
                     grid_gap_pips: float = 15.0,
                     base_lot:     float = 0.01,
                     max_layers:   int   = 10,
                     ma_fast:      int   = 20,
                     ma_slow:      int   = 50,
                     ma_tf_key:    str   = "m15",
                     sl_per_pos_pips: float = 200.0,
                     basket_tp_usd:   float = 5.0,
                     max_dd_pct:      float = 20.0):
    print(f"  NGS_Grid: gap={grid_gap_pips}p baseLot={base_lot} "
          f"maxL={max_layers} basketTP=${basket_tp_usd} maxDD={max_dd_pct}%")

    m5  = data["m5"].copy()
    mtf = data[ma_tf_key].copy()
    mtf["ma_f"] = ema_series(mtf["close"], ma_fast)
    mtf["ma_s"] = ema_series(mtf["close"], ma_slow)

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
                         fp, usd(fp, p["lot"]), reason, "NGS_Grid"))

    trades, positions = [], []
    balance      = INIT_BALANCE
    equity_peak  = balance
    halted       = False

    mtf_idx = mtf.index
    for i in range(50, len(m5)):
        ts   = m5.index[i]
        bar  = m5.iloc[i]
        high, low, close = bar["high"], bar["low"], bar["close"]

        # ── 1) DD kill-switch ──────────────────────────────────────
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

        # ── 2) per-position SL via bar high/low ────────────────────
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

        # ── 3) basket TP using bar close ───────────────────────────
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

        if len(positions) >= max_layers: continue

        # ── 4) entry / next-layer ──────────────────────────────────
        # trend from last CLOSED M15 bar
        pos = mtf_idx.searchsorted(ts, side="right") - 2  # last closed mtf bar
        if pos < ma_slow + 2: continue
        mrow = mtf.iloc[pos]
        f, s = mrow["ma_f"], mrow["ma_s"]
        if pd.isna(f) or pd.isna(s): continue
        trend = 1 if f > s else -1

        if not positions:
            entry = close
            sl_p  = entry - sl_per_pos_pips * pip if trend == 1 \
                    else entry + sl_per_pos_pips * pip
            positions.append({"dir": trend, "entry": entry, "lot": base_lot,
                              "sl_price": sl_p, "open_time": ts})
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
                sl_p  = entry - sl_per_pos_pips * pip if d == 1 \
                        else entry + sl_per_pos_pips * pip
                positions.append({"dir": d, "entry": entry, "lot": base_lot,
                                  "sl_price": sl_p, "open_time": ts})

    # mark-to-market any remaining at last bar
    last_ts = m5.index[-1]; last_close = m5.iloc[-1]["close"]
    for p in positions:
        close_one(p, last_close, last_ts, "EndOfData", trades)
        balance += usd((last_close - p["entry"]) / pip if p["dir"] == 1
                       else (p["entry"] - last_close) / pip, p["lot"])
    return trades


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    print("Loading XAUUSD m5 + m15 ...")
    data = {
        "m5":  br.get_rates("XAUUSD", mt5.TIMEFRAME_M5),
        "m15": br.get_rates("XAUUSD", mt5.TIMEFRAME_M15),
    }
    print("\n=== NGS_Grid sweep (XAUUSD M5, post-cost, DD-ceiling 20%) ===")
    print(f"  {'gap':>4} {'maxL':>4} {'TP$':>5} "
          f"{'Trades':>7} {'WR%':>6} {'PF':>6} {'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 64)
    rows = []
    for gap in (10, 15, 25, 40):
        for maxL in (5, 10, 15):
            for tp in (3.0, 5.0, 10.0):
                trades = backtest_ngs_grid(
                    data, grid_gap_pips=gap, max_layers=maxL,
                    basket_tp_usd=tp, max_dd_pct=20.0)
                if not trades:
                    print(f"  {gap:>4} {maxL:>4} {tp:>5.1f}  (no trades)")
                    continue
                st = compute_stats(trades, INIT_BALANCE, "XAUUSD")
                if "error" in st: continue
                ok = (st["profit_factor"] > 1.0 and st["max_drawdown"] <= 20.0
                      and st["net_profit_pct"] > 0)
                if ok: rows.append((gap, maxL, tp, st))
                print(f"  {gap:>4} {maxL:>4} {tp:>5.1f} {st['total_trades']:>7} "
                      f"{st['win_rate']:>6.1f} {st['profit_factor']:>6.2f} "
                      f"{st['net_profit_pct']:>+8.1f} {st['max_drawdown']:>6.1f}  "
                      f"{'YES' if ok else 'no'}")
    print("  " + "-" * 64)
    if rows:
        best = max(rows, key=lambda r: r[3]["net_profit_pct"])
        s = best[3]
        print(f"  BEST: gap={best[0]}p maxL={best[1]} TP=${best[2]}  "
              f"-> Ret {s['net_profit_pct']:+.1f}%  PF {s['profit_factor']:.2f}  "
              f"DD {s['max_drawdown']:.1f}%  trades {s['total_trades']}")
    else:
        print("  NO configuration passed the real-cost gate.")
    mt5.shutdown()


if __name__ == "__main__":
    main()
