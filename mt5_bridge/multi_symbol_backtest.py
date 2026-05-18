# encoding: utf-8
"""
Multi-symbol compound backtest: XAUUSD + BTCUSD + EURUSD
Single shared balance, compound sizing, global daily DD 5% hard stop.
Each symbol uses its optimized params from previous backtests.
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, '.')
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size
from backtest import add_indicators, compute_score_arrays, signals_from_scores
from config import SYMBOL_CONFIG

# ── Per-symbol optimized configs ─────────────────────────────────────────────
SYMBOLS = {
    "XAUUSD": {
        "sessions":    [(8, 12), (19, 23)],
        "req_score":   5,
        "atr_sl":      0.8,
        "rr":          2.0,
        "spread":      0.30,
        "atr_min":     2.0,
    },
    "BTCUSD": {
        "sessions":    [(9, 13), (20, 23)],
        "req_score":   5,
        "atr_sl":      0.8,
        "rr":          2.5,
        "spread":      0.25,
        "atr_min":     5.0,
    },
}

BASE_PARAMS = {
    "EMA_Fast": 9, "EMA_Slow": 21, "RSI_Period": 7,
    "RSI_OB": 70, "RSI_OS": 30, "ATR_Period": 14,
    "BB_Period": 20, "BB_Deviation": 2.0,
    "MACD_Fast": 8, "MACD_Slow": 17, "MACD_Signal": 9,
    "MomCandles": 2, "MinCandleBody": 0.25,
    "EMASlopePeriod": 5,
    "InitialBalance": 100.0,
    "MaxDrawdownPct": 35.0,
    "UseTrailingTP": False, "TrailTrigger": 1.0, "TrailStep": 0.5,
    "MaxTradeBars": 0,
}

RISK_PCT       = 2.0   # % of current balance per trade
DAILY_DD_LIMIT = 4.5   # % — stop ALL symbols for the day if hit
MAX_DAILY_TRADES = 15  # across all symbols
BARS           = 6 * 30 * 24 * 60


def fetch_and_prepare(symbol, cfg):
    SYMBOL_CONFIG["_atr_min"] = cfg["atr_min"]
    p = BASE_PARAMS.copy()
    p["RequiredScore"] = cfg["req_score"]
    p["ATR_SL_Multi"]  = cfg["atr_sl"]
    p["RiskPct"]       = RISK_PCT
    p["RiskPerTrade"]  = RISK_PCT
    p["RewardPerTrade"] = RISK_PCT * cfg["rr"]

    raw = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, BARS)
    pip = get_pip_size(symbol)
    df  = add_indicators(raw, p).dropna()

    a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
        df, p, pip, session_hours=cfg["sessions"])
    sigs = signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid,
                                cfg["req_score"], df.index)
    return df, sigs, pip, p


def run_multi_symbol():
    connect()

    # ── Fetch all data ──────────────────────────────────────────────────────
    data = {}
    for sym, cfg in SYMBOLS.items():
        print(f"Fetching {sym}...")
        SYMBOL_CONFIG["_atr_min"] = cfg["atr_min"]
        df, sigs, pip, p = fetch_and_prepare(sym, cfg)
        nsig = int((sigs != 0).sum())
        days = (df.index[-1] - df.index[0]).days
        print(f"  {sym}: {len(df)} bars | {days} days | {nsig} signals ({nsig/max(days,1):.1f}/day)")
        data[sym] = {"df": df, "sigs": sigs, "pip": pip, "p": p, "cfg": cfg}

    # ── Find common date range ───────────────────────────────────────────────
    start = max(d["df"].index[0] for d in data.values())
    end   = min(d["df"].index[-1] for d in data.values())
    days  = (end - start).days
    print(f"\nCommon period: {start.date()} to {end.date()} = {days} days\n")

    for sym in data:
        df  = data[sym]["df"]
        sig = data[sym]["sigs"]
        mask = (df.index >= start) & (df.index <= end)
        data[sym]["df"]   = df[mask]
        data[sym]["sigs"] = sig[mask]

    # ── Build unified signal timeline ─────────────────────────────────────
    # merge all signals into one list sorted by timestamp
    events = []
    for sym, d in data.items():
        df   = d["df"]
        sigs = d["sigs"]
        for i in range(1, len(df) - 1):
            if int(sigs.values[i]) != 0:
                events.append({
                    "ts":    df.index[i],
                    "sym":   sym,
                    "i":     i,
                    "sig":   int(sigs.values[i]),
                    "atr":   df["atr"].values[i],
                    "open_next": df["Open"].values[i + 1],
                })
    events.sort(key=lambda x: x["ts"])

    # ── Simulate ─────────────────────────────────────────────────────────────
    bal     = 100.0
    peak    = 100.0
    trades  = []
    open_trades = {}   # sym -> open trade dict
    daily   = {}       # date -> trade count
    dpnl    = {}       # date -> pnl
    daily_start = {}   # date -> bal at start of day

    # We simulate bar-by-bar on minute timeline using XAUUSD as the clock
    # but update all open trades each minute
    all_dfs = {sym: data[sym]["df"] for sym in data}
    all_sigs = {sym: data[sym]["sigs"] for sym in data}

    # collect all timestamps
    all_times = sorted(set.union(*[set(df.index) for df in all_dfs.values()]))
    print(f"Total minute bars to process: {len(all_times)}")

    # index lookup for each symbol
    sym_idx = {sym: {t: i for i, t in enumerate(df.index)} for sym, df in all_dfs.items()}

    for ts in all_times:
        day = ts.date()
        if day not in daily_start:
            daily_start[day] = bal

        day_dd_pct = (daily_start[day] - bal) / daily_start[day] * 100 if daily_start[day] > 0 else 0
        day_blocked = day_dd_pct >= DAILY_DD_LIMIT

        # ── manage open trades ──────────────────────────────────────────────
        for sym in list(open_trades.keys()):
            ot  = open_trades[sym]
            idx = sym_idx[sym].get(ts)
            if idx is None:
                continue
            df  = all_dfs[sym]
            h   = float(df["High"].values[idx])
            l   = float(df["Low"].values[idx])
            res = None
            pnl = 0.0
            cfg = SYMBOLS[sym]

            if ot["d"] == 1:
                if l <= ot["sl"]:
                    pnl = -ot["r"] - cfg["spread"]
                    res = "SL"
                elif h >= ot["tp"]:
                    pnl = ot["rw"] - cfg["spread"]
                    res = "TP"
            else:
                if h >= ot["sl"]:
                    pnl = -ot["r"] - cfg["spread"]
                    res = "SL"
                elif l <= ot["tp"]:
                    pnl = ot["rw"] - cfg["spread"]
                    res = "TP"

            if res:
                bal  += pnl
                peak  = max(peak, bal)
                dpnl[day] = dpnl.get(day, 0.0) + pnl
                trades.append({
                    "sym":  sym,
                    "pnl":  round(pnl, 4),
                    "res":  res,
                    "bal":  round(bal, 4),
                    "date": day,
                    "hr":   ot["hr"],
                    "dir":  ot["d"],
                })
                del open_trades[sym]

        # ── new entries ─────────────────────────────────────────────────────
        if not day_blocked:
            for sym in data:
                if sym in open_trades:
                    continue
                idx = sym_idx[sym].get(ts)
                if idx is None or idx >= len(all_dfs[sym]) - 1:
                    continue

                sig_val = int(all_sigs[sym].values[idx])
                if sig_val == 0:
                    continue

                daily[day] = daily.get(day, 0) + 1
                if daily[day] > MAX_DAILY_TRADES:
                    continue

                df   = all_dfs[sym]
                cfg  = SYMBOLS[sym]
                av   = float(df["atr"].values[idx])
                if np.isnan(av) or av <= 0:
                    continue

                entry = float(df["Open"].values[idx + 1])
                asl   = cfg["atr_sl"]
                rr    = cfg["rr"]
                sd    = av * asl
                r     = bal * RISK_PCT / 100.0
                rw    = r * rr
                sl    = entry - sd if sig_val == 1 else entry + sd
                tp    = entry + sd * rr if sig_val == 1 else entry - sd * rr

                open_trades[sym] = {
                    "d": sig_val, "e": entry, "sl": sl, "tp": tp,
                    "sd": sd, "r": r, "rw": rw, "hr": ts.hour,
                }

    # ── Results ──────────────────────────────────────────────────────────────
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print("No trades.")
        disconnect()
        return

    wins  = tdf[tdf["pnl"] > 0]
    loss  = tdf[tdf["pnl"] <= 0]
    net   = tdf["pnl"].sum()
    tl    = loss["pnl"].abs().sum()
    pf    = wins["pnl"].sum() / tl if tl > 0 else 99.0
    wr    = len(wins) / len(tdf) * 100
    cum   = tdf["pnl"].cumsum() + 100
    pk    = cum.cummax()
    mdd   = ((pk - cum) / pk * 100).max()
    dv    = sorted(dpnl.values())
    pos   = sum(1 for v in dv if v > 0)

    print(f"\n{'='*65}")
    print(f"  MULTI-SYMBOL COMPOUND RESULT (XAUUSD + BTCUSD + EURUSD)")
    print(f"{'='*65}")
    print(f"  Period        : {days} days")
    print(f"  Total Trades  : {len(tdf)}  ({len(tdf)/days:.1f}/day)")
    print(f"  Win Rate      : {wr:.1f}%")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  Net PnL       : ${net:.2f}")
    print(f"  Final Balance : ${100+net:.2f}")
    print(f"  Max Drawdown  : {mdd:.1f}%")
    print(f"  Best day      : ${max(dv):.2f}")
    print(f"  Worst day     : ${min(dv):.2f}")
    print(f"  Avg/day       : ${sum(dv)/len(dv):.2f}")
    print(f"  Green days    : {pos}/{len(dv)} ({pos/max(len(dv),1)*100:.0f}%)")

    # Per-symbol breakdown
    print(f"\n  Per-symbol breakdown:")
    for sym in SYMBOLS:
        sub = tdf[tdf["sym"] == sym]
        if sub.empty:
            print(f"    {sym}: no trades")
            continue
        sw  = sub[sub["pnl"] > 0]
        stl = sub[sub["pnl"] <= 0]["pnl"].abs().sum()
        spf = sw["pnl"].sum() / stl if stl > 0 else 99.0
        swr = len(sw) / len(sub) * 100
        print(f"    {sym}: {len(sub)} trades | WR {swr:.1f}% | PF {spf:.2f} | Net ${sub['pnl'].sum():.2f}")

    # Daily DD check
    day_losses = {d: v for d, v in dpnl.items() if v < 0}
    days_over  = sum(1 for v in day_losses.values() if abs(v/daily_start.get(list(dpnl.keys())[0], 100)*100) >= 5)
    print(f"\n  Daily DD analysis:")
    print(f"  Loss days     : {len(day_losses)}/{len(dpnl)}")
    print(f"  Worst day     : ${min(dv):.2f}")
    print(f"  Days > 5% DD  : {days_over}")

    print(f"\n  Daily P&L (all trading days):")
    for d, v in sorted(dpnl.items()):
        tag  = "WIN " if v >= 0 else "LOSS"
        bar  = "#" * min(int(abs(v) / 1.0), 40)
        sign = "+" if v >= 0 else ""
        print(f"    {d}  {sign}${v:>7.2f}  {tag}  {bar}")

    # Compound projection
    print(f"\n  COMPOUND GROWTH PROJECTION:")
    dt  = len(tdf) / days
    wr2 = wr / 100
    risk = RISK_PCT / 100
    avg_rr = sum(SYMBOLS[s]["rr"] for s in SYMBOLS) / len(SYMBOLS)
    for d in [7, 14, 30, 60, 90, 180]:
        b2 = 100.0
        for _ in range(d):
            w  = dt * wr2
            lo = dt * (1 - wr2)
            b2 *= (1 + w * risk * avg_rr - lo * risk)
        print(f"    Day {d:3d}: ${b2:>10.2f}  ({(b2-100):.1f}% gain)")

    disconnect()
    print("\nDone.")


if __name__ == "__main__":
    run_multi_symbol()
