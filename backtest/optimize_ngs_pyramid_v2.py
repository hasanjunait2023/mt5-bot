"""
NGS_Pyramid v2 (Phase 4) — STRONGER trend filter.

Phase 3B near-misses (GBPUSD PF 1.01, EURUSD 0.96-0.98) showed Pyramid
has some momentum edge but MA-cross alone is too weak (WR 22-46%).
v2 adds:
  - ADX > AdxMin (default 25) — only trade in active trends
  - H1 EMA200 multi-TF alignment — M15 MA cross direction must agree
    with H1 EMA200 direction
  - All other Pyramid mechanics unchanged (ATR SL, trailing basket SL,
    DD kill-switch)

Target: GBPUSD, EURUSD, GBPJPY (the Phase 3B near-misses).
Gate: PF > 1.2, DD <= 15% post-cost.
"""
import sys
import pandas as pd
import MetaTrader5 as mt5

import backtest_runner as br
from backtest_runner import (
    Trade, INIT_BALANCE, pip_size, ema_series, atr_series, compute_stats,
)


def adx_series(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Classic ADX(n) on OHLC dataframe — returns ADX values (0-100)."""
    high, low, close = df["high"], df["low"], df["close"]
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm  = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat([(high - low),
                    (high - close.shift()).abs(),
                    (low  - close.shift()).abs()], axis=1).max(axis=1)
    atr      = tr.ewm(alpha=1.0 / n, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1.0 / n, adjust=False).mean()


def backtest_ngs_pyramid_v2(data, symbol="EURUSD",
                            grid_gap_pips=25.0, base_lot=0.01,
                            max_layers=6, sl_atr_mult=1.5,
                            sl_min_pips=25.0, sl_max_pips=150.0,
                            trail_activation_usd=5.0,
                            trail_drawdown_usd=3.0,
                            max_dd_pct=15.0,
                            ma_fast=20, ma_slow=50,
                            adx_min=25.0, adx_period=14,
                            h1_ema_period=200):
    print(f"  v2 {symbol}: gap={grid_gap_pips} ATRx{sl_atr_mult} "
          f"trail=${trail_activation_usd}/${trail_drawdown_usd} "
          f"ADX>{adx_min} +H1EMA{h1_ema_period}")
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

    def close_one(p, exit_price, exit_time, reason, out):
        fp = ((exit_price - p["entry"]) / pip
              if p["dir"] == 1 else (p["entry"] - exit_price) / pip)
        out.append(Trade(p["open_time"], exit_time,
                         "BUY" if p["dir"] == 1 else "SELL",
                         p["entry"], exit_price, p["lot"],
                         fp, usd(fp, p["lot"]), reason, "NGS_Pyramid_v2"))

    trades, positions = [], []
    balance         = INIT_BALANCE
    equity_peak     = balance
    halted          = False
    basket_peak_pnl = -1e18
    trail_active    = False

    mtf_idx = mtf.index
    h1_idx  = h1.index

    def sl_pips_now(ts):
        pos = mtf_idx.searchsorted(ts, side="right") - 2
        if pos < 14 + 1: return sl_min_pips
        a = mtf.iloc[pos]["atr"]
        if pd.isna(a) or a <= 0: return sl_min_pips
        v = (a / pip) * sl_atr_mult
        return max(sl_min_pips, min(sl_max_pips, v))

    for i in range(50, len(m5)):
        ts   = m5.index[i]
        bar  = m5.iloc[i]
        high, low, close = bar["high"], bar["low"], bar["close"]

        # DD kill-switch
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

        # per-position SL (intra-bar)
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

        # trailing basket exit
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

        # ── STRONGER trend filter (v2) ─────────────────────────────
        pos = mtf_idx.searchsorted(ts, side="right") - 2
        if pos < ma_slow + 2: continue
        mrow = mtf.iloc[pos]
        f, s, adx_v = mrow["ma_f"], mrow["ma_s"], mrow["adx"]
        if pd.isna(f) or pd.isna(s) or pd.isna(adx_v): continue
        if adx_v < adx_min: continue        # ADX gate — trend must be active
        m15_dir = 1 if f > s else -1

        # H1 EMA200 alignment
        h1p = h1_idx.searchsorted(ts, side="right") - 2
        if h1p < h1_ema_period + 1: continue
        h1r = h1.iloc[h1p]
        if pd.isna(h1r["ema200"]): continue
        h1_dir = 1 if h1r["close"] > h1r["ema200"] else -1
        if m15_dir != h1_dir: continue       # multi-TF must agree

        trend = m15_dir
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

    last_ts = m5.index[-1]; last_close = m5.iloc[-1]["close"]
    for p in positions:
        close_one(p, last_close, last_ts, "EndOfData", trades)
        balance += usd((last_close - p["entry"]) / pip if p["dir"] == 1
                       else (p["entry"] - last_close) / pip, p["lot"])
    return trades


CONFIGS = [
    # gap maxL ATRx tAct tDD adx
    (15, 6, 1.5,  5.0, 3.0, 20),
    (25, 6, 1.5,  5.0, 3.0, 20),
    (25, 6, 1.5,  5.0, 3.0, 25),
    (40, 6, 1.5, 10.0, 5.0, 25),
    (40, 6, 1.5, 10.0, 5.0, 30),
    (25, 6, 2.0,  5.0, 3.0, 25),
]

SYMBOLS = ["GBPUSD", "EURUSD", "GBPJPY", "EURJPY", "USDJPY", "XAUUSD"]


def main():
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    print("=== NGS_Pyramid v2 (ADX + multi-TF) — post-cost, DD<=15% ===")
    print(f"  {'Symbol':8} {'gap':>4} {'ATRx':>5} {'tAct':>5} {'tDD':>5} "
          f"{'ADX':>4} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Ret%':>8} {'DD%':>6}  ok?")
    print("  " + "-" * 84)

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
        if data["m5"].empty or data["m15"].empty or data["h1"].empty:
            print(f"  {sym} (no data)"); continue

        for gap, maxL, atrx, tAct, tDD, adx_min in CONFIGS:
            trades = backtest_ngs_pyramid_v2(
                data, symbol=sym,
                grid_gap_pips=gap, max_layers=maxL, sl_atr_mult=atrx,
                trail_activation_usd=tAct, trail_drawdown_usd=tDD,
                max_dd_pct=15.0, adx_min=adx_min)
            if not trades:
                print(f"  {sym:8} {gap:>4} {atrx:>5.1f} {tAct:>5.1f} "
                      f"{tDD:>5.1f} {adx_min:>4}  (no trades)")
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
            print(f"  {sym:8} {gap:>4} {atrx:>5.1f} {tAct:>5.1f} "
                  f"{tDD:>5.1f} {adx_min:>4} {st['total_trades']:>7} "
                  f"{st['win_rate']:>6.1f} {st['profit_factor']:>6.2f} "
                  f"{st['net_profit_pct']:>+8.1f} {st['max_drawdown']:>6.1f}  {tag}")
            if ok:
                winners.append(((sym, gap, atrx, tAct, tDD, adx_min), st))

    print("  " + "-" * 84)
    if winners:
        print(f"\n  PHASE 4 GATE: PASSED — {len(winners)} viable config(s)")
        for cfg, st in winners:
            sym, gap, atrx, tAct, tDD, adx = cfg
            print(f"   {sym}: gap={gap}p ATRx={atrx} tAct=${tAct} "
                  f"tDD=${tDD} ADX>{adx} -> "
                  f"Ret {st['net_profit_pct']:+.1f}% PF {st['profit_factor']:.2f} "
                  f"DD {st['max_drawdown']:.1f}% trades {st['total_trades']}")
    else:
        print("\n  PHASE 4 GATE: FAILED — ADX + multi-TF filter still not enough.")
        print("  Next NextGen iteration: try breakout-confirmed entry "
              "(price breaks recent swing high/low) instead of MA cross.")
    mt5.shutdown()


if __name__ == "__main__":
    main()
