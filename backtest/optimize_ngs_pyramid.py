"""
NextGenSync_Pyramid real-cost backtest gate (Phase 2).

Mirrors NextGenSync_Pyramid.mq5: trend-direction layers + ATR-based per-
position SL + trailing basket SL + DD kill-switch. Run on XAUUSD M5
(2yr) with realistic spread via backtest_runner.trade_cost.

Pass criteria: PF > 1.2, DD <= 15%, no integrity artifacts.
"""
import sys
import MetaTrader5 as mt5
import pandas as pd

import backtest_runner as br
from backtest_runner import (
    Trade, INIT_BALANCE, pip_size, ema_series, atr_series, compute_stats,
)


def backtest_ngs_pyramid(data: dict, symbol: str = "XAUUSD",
                        grid_gap_pips: float = 20.0,
                        base_lot:      float = 0.01,
                        max_layers:    int   = 6,
                        ma_fast:       int   = 20,
                        ma_slow:       int   = 50,
                        ma_tf_key:     str   = "m15",
                        atr_tf_key:    str   = "m15",
                        atr_period:    int   = 14,
                        sl_atr_mult:   float = 1.5,
                        sl_min_pips:   float = 25.0,
                        sl_max_pips:   float = 150.0,
                        trail_activation_usd: float = 5.0,
                        trail_drawdown_usd:   float = 3.0,
                        max_dd_pct:    float = 15.0):
    print(f"  Pyramid: gap={grid_gap_pips}p maxL={max_layers} "
          f"ATR×{sl_atr_mult} trailAct=${trail_activation_usd} "
          f"trailDD=${trail_drawdown_usd} maxDD={max_dd_pct}%")

    m5  = data["m5"].copy()
    mtf = data[ma_tf_key].copy()
    atr_tf = data[atr_tf_key].copy()
    mtf["ma_f"] = ema_series(mtf["close"], ma_fast)
    mtf["ma_s"] = ema_series(mtf["close"], ma_slow)
    atr_tf["atr"] = atr_series(atr_tf, atr_period)

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
                         fp, usd(fp, p["lot"]), reason, "NGS_Pyramid"))

    trades, positions = [], []
    balance         = INIT_BALANCE
    equity_peak     = balance
    halted          = False
    basket_peak_pnl = -1e18
    trail_active    = False

    mtf_idx = mtf.index
    atr_idx = atr_tf.index

    def sl_pips_now(ts):
        pos = atr_idx.searchsorted(ts, side="right") - 2
        if pos < atr_period + 1: return sl_min_pips
        a = atr_tf.iloc[pos]["atr"]
        if pd.isna(a) or a <= 0: return sl_min_pips
        v = (a / pip) * sl_atr_mult
        return max(sl_min_pips, min(sl_max_pips, v))

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
            basket_peak_pnl, trail_active = -1e18, False
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

        # ── 3) trailing basket exit ─────────────────────────────────
        if positions:
            floating = sum(usd((close - p["entry"]) / pip if p["dir"] == 1
                               else (p["entry"] - close) / pip, p["lot"])
                           for p in positions)
            if floating > basket_peak_pnl: basket_peak_pnl = floating
            if not trail_active and basket_peak_pnl >= trail_activation_usd:
                trail_active = True
            if trail_active and (basket_peak_pnl - floating) >= trail_drawdown_usd:
                for p in positions:
                    close_one(p, close, ts, "TrailSL", trades)
                    balance += usd((close - p["entry"]) / pip if p["dir"] == 1
                                   else (p["entry"] - close) / pip, p["lot"])
                positions = []
                basket_peak_pnl, trail_active = -1e18, False
                continue
        else:
            basket_peak_pnl, trail_active = -1e18, False

        if len(positions) >= max_layers: continue

        # ── 4) entry / next-layer ──────────────────────────────────
        pos = mtf_idx.searchsorted(ts, side="right") - 2
        if pos < ma_slow + 2: continue
        mrow = mtf.iloc[pos]
        f, s = mrow["ma_f"], mrow["ma_s"]
        if pd.isna(f) or pd.isna(s): continue
        trend = 1 if f > s else -1

        sl_p = sl_pips_now(ts)

        if not positions:
            entry = close
            sl_px = entry - sl_p * pip if trend == 1 else entry + sl_p * pip
            positions.append({"dir": trend, "entry": entry, "lot": base_lot,
                              "sl_price": sl_px, "open_time": ts})
        else:
            d = positions[0]["dir"]
            if d == 1:
                best = max(p["entry"] for p in positions)
                fire = close >= best + grid_gap_pips * pip
            else:
                best = min(p["entry"] for p in positions)
                fire = close <= best - grid_gap_pips * pip
            if fire:
                entry = close
                sl_px = entry - sl_p * pip if d == 1 else entry + sl_p * pip
                positions.append({"dir": d, "entry": entry, "lot": base_lot,
                                  "sl_price": sl_px, "open_time": ts})

    # mark-to-market remaining
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
    print("\n=== NGS_Pyramid sweep (XAUUSD M5, post-cost, DD-ceiling 15%) ===")
    print(f"  {'gap':>4} {'maxL':>4} {'ATRx':>5} {'tAct':>5} {'tDD':>5} "
          f"{'Trades':>7} {'WR%':>6} {'PF':>6} {'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 80)
    rows = []
    for gap in (15, 25, 40):
        for maxL in (4, 6, 8):
            for atrx in (1.0, 1.5, 2.0):
                for tAct, tDD in ((3.0, 2.0), (5.0, 3.0), (10.0, 5.0)):
                    trades = backtest_ngs_pyramid(
                        data, grid_gap_pips=gap, max_layers=maxL,
                        sl_atr_mult=atrx,
                        trail_activation_usd=tAct,
                        trail_drawdown_usd=tDD,
                        max_dd_pct=15.0)
                    if not trades:
                        print(f"  {gap:>4} {maxL:>4} {atrx:>5.1f} "
                              f"{tAct:>5.1f} {tDD:>5.1f}  (no trades)")
                        continue
                    st = compute_stats(trades, INIT_BALANCE, "XAUUSD")
                    if "error" in st: continue
                    max_move = max(abs(t.exit_price - t.entry_price) / t.entry_price * 100
                                   for t in trades if t.entry_price)
                    artifact = max_move > 20.0 or st["profit_factor"] > 50
                    ok = (not artifact and st["profit_factor"] > 1.2
                          and st["max_drawdown"] <= 15.0
                          and st["net_profit_pct"] > 0)
                    if ok: rows.append((gap, maxL, atrx, tAct, tDD, st))
                    tag = "ART" if artifact else ("YES" if ok else "no")
                    print(f"  {gap:>4} {maxL:>4} {atrx:>5.1f} "
                          f"{tAct:>5.1f} {tDD:>5.1f} {st['total_trades']:>7} "
                          f"{st['win_rate']:>6.1f} {st['profit_factor']:>6.2f} "
                          f"{st['net_profit_pct']:>+8.1f} {st['max_drawdown']:>6.1f}  {tag}")
    print("  " + "-" * 80)
    if rows:
        best = max(rows, key=lambda r: r[5]["net_profit_pct"])
        s = best[5]
        print(f"  BEST: gap={best[0]}p maxL={best[1]} ATRx={best[2]} "
              f"tAct=${best[3]} tDD=${best[4]} -> "
              f"Ret {s['net_profit_pct']:+.1f}% PF {s['profit_factor']:.2f} "
              f"DD {s['max_drawdown']:.1f}% trades {s['total_trades']}")
        print(f"  PHASE 2 GATE: PASSED ({len(rows)} configs viable)")
    else:
        print("  PHASE 2 GATE: FAILED (no config meets PF>1.2 & DD<=15%)")
    mt5.shutdown()


if __name__ == "__main__":
    main()
