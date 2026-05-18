# encoding: utf-8
"""
Same ScalpMaster HFT strategy applied to XAUUSD (Gold) — 6 months M1 data.
Next-bar open entry, spread-adjusted, daily trade limit, max drawdown guard.
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size
from backtest import add_indicators, compute_score_arrays, signals_from_scores
from config import SYMBOL_CONFIG

# ── Strategy parameters (same logic as EA, gold-adjusted) ───────────────────
PARAMS = {
    "EMA_Fast":       9,
    "EMA_Slow":       21,
    "RSI_Period":     7,
    "RSI_OB":         70,
    "RSI_OS":         30,
    "ATR_Period":     14,
    "ATR_SL_Multi":   0.8,
    "BB_Period":      20,
    "BB_Deviation":   2.0,
    "MACD_Fast":      8,
    "MACD_Slow":      17,
    "MACD_Signal":    9,
    "MomCandles":     2,
    "MinCandleBody":  0.25,
    "RequiredScore":  5,
    "EMASlopePeriod": 5,
    "InitialBalance": 100.0,
    "RiskPct":        5.0,
    "RiskPerTrade":   5.0,
    "RewardPerTrade": 12.5,   # RR 1:2.5
    "MaxDrawdownPct": 30.0,
    "UseTrailingTP":  False,
    "TrailTrigger":   1.0,
    "TrailStep":      0.5,
    "MaxTradeBars":   0,
}

SYMBOL        = "XAUUSD"
SESSIONS      = [(10, 13), (20, 23)]   # Gold peak hours from config
MAX_TRADES_DAY = 12
SPREAD_COST   = 0.30   # $ per trade (Gold spread ~$0.30 simulation)
ATR_MIN_PIPS  = 3.0    # Gold needs higher ATR threshold
BARS_6M       = 6 * 30 * 24 * 60   # ~259,200 M1 bars


def simulate_exact(df, sigs, p, spread_cost, max_trades_day):
    bal   = p["InitialBalance"]
    peak  = bal
    rr    = p["RewardPerTrade"] / p["RiskPerTrade"]
    asl   = p["ATR_SL_Multi"]
    max_bars = p["MaxTradeBars"]
    max_dd = p["MaxDrawdownPct"] / 100.0

    ha    = df["High"].values
    la    = df["Low"].values
    oa    = df["Open"].values
    ca    = df["Close"].values
    aa    = df["atr"].values
    sa    = sigs.values
    times = df.index

    trades = []
    ot     = None
    daily  = {}
    dpnl   = {}

    for i in range(1, len(ha) - 1):
        if peak > 0 and (peak - bal) / peak > max_dd:
            print(f"  [!] Max drawdown hit at bar {i}, stopping.")
            break

        h = float(ha[i])
        l = float(la[i])

        if ot is not None:
            res = None
            pnl = 0.0
            bars = i - ot["i"]
            if max_bars > 0 and bars >= max_bars:
                c   = float(ca[i])
                pnl = (ot["r"] * (c - ot["e"]) / ot["sd"]
                       if ot["d"] == 1
                       else ot["r"] * (ot["e"] - c) / ot["sd"]) - spread_cost
                res = "TO"
            elif ot["d"] == 1:
                if l <= ot["sl"]:
                    pnl = -ot["r"] - spread_cost
                    res = "SL"
                elif h >= ot["tp"]:
                    pnl = ot["rw"] - spread_cost
                    res = "TP"
            else:
                if h >= ot["sl"]:
                    pnl = -ot["r"] - spread_cost
                    res = "SL"
                elif l <= ot["tp"]:
                    pnl = ot["rw"] - spread_cost
                    res = "TP"
            if res:
                bal  += pnl
                peak  = max(peak, bal)
                day   = times[i].date()
                dpnl[day] = dpnl.get(day, 0.0) + pnl
                trades.append({
                    "pnl":  round(pnl, 3),
                    "res":  res,
                    "bal":  round(bal, 2),
                    "date": day,
                    "hr":   ot["hr"],
                    "dir":  ot["d"],
                })
                ot = None

        if ot is None and int(sa[i]) != 0:
            day = times[i].date()
            daily[day] = daily.get(day, 0) + 1
            if daily[day] > max_trades_day:
                continue
            sig_v = int(sa[i])
            entry = float(oa[i + 1])
            av    = float(aa[i])
            if np.isnan(av) or av <= 0:
                continue
            sd   = av * asl
            r    = bal * p["RiskPct"] / 100.0
            rw   = r * rr
            sl   = entry - sd if sig_v == 1 else entry + sd
            tp   = entry + sd * rr if sig_v == 1 else entry - sd * rr
            ot   = {"d": sig_v, "e": entry, "sl": sl, "tp": tp,
                    "sd": sd, "r": r, "rw": rw, "i": i, "hr": int(times[i].hour)}

    return pd.DataFrame(trades), dpnl


def print_report(tdf, dpnl, days):
    if tdf is None or tdf.empty:
        print("No trades generated.")
        return

    wins = tdf[tdf["pnl"] > 0]
    loss = tdf[tdf["pnl"] <= 0]
    net  = tdf["pnl"].sum()
    tl   = loss["pnl"].abs().sum()
    pf   = wins["pnl"].sum() / tl if tl > 0 else 99.0
    wr   = len(wins) / len(tdf) * 100
    cum  = tdf["pnl"].cumsum() + 100
    pk   = cum.cummax()
    mdd  = ((pk - cum) / pk * 100).max()
    dv   = sorted(dpnl.values())
    best = max(dv) if dv else 0
    worst= min(dv) if dv else 0
    avg  = sum(dv) / len(dv) if dv else 0
    pos  = sum(1 for v in dv if v > 0)

    print(f"\n{'='*62}")
    print(f"  ScalpMaster HFT | XAUUSD M1 | 6 Months")
    print(f"{'='*62}")
    print(f"  Period        : {days} days")
    print(f"  Total Trades  : {len(tdf)}  ({len(tdf)/days:.1f}/day)")
    print(f"  Win Rate      : {wr:.1f}%")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  Net PnL       : ${net:.2f}")
    print(f"  Final Balance : ${100+net:.2f}")
    print(f"  Max Drawdown  : {mdd:.1f}%")
    print(f"  Best day      : ${best:.2f}")
    print(f"  Worst day     : ${worst:.2f}")
    print(f"  Avg/day       : ${avg:.2f}")
    print(f"  Green days    : {pos}/{len(dv)}  ({pos/max(len(dv),1)*100:.0f}%)")

    for res in ["TP", "SL", "TO"]:
        sub = tdf[tdf["res"] == res]
        if len(sub):
            print(f"  {res:<3}           : {len(sub)} trades  PnL ${sub['pnl'].sum():.2f}")

    # Hour breakdown
    print(f"\n  Win rate by hour (UTC):")
    for hr, grp in tdf.groupby("hr"):
        w  = (grp["pnl"] > 0).sum()
        wr2 = w / len(grp) * 100
        bar = "#" * int(wr2 / 5)
        print(f"    {hr:02d}:00  {len(grp):3d} trades  WR {wr2:5.1f}%  {bar}")

    print(f"\n  Daily P&L:")
    for d, v in sorted(dpnl.items()):
        tag  = "WIN " if v >= 0 else "LOSS"
        bar  = "#" * min(int(abs(v) / 1.5), 35)
        sign = "+" if v >= 0 else ""
        print(f"    {d}  {sign}${v:>7.2f}  {tag}  {bar}")

    # Verdict
    print(f"\n{'='*62}")
    if pf >= 1.5 and wr >= 45:
        verdict = "PROFITABLE — strategy works on Gold"
    elif pf >= 1.2 and wr >= 42:
        verdict = "MARGINALLY PROFITABLE — needs tuning"
    else:
        verdict = "NOT PROFITABLE — strategy does not transfer to Gold"
    print(f"  VERDICT: {verdict}")
    print(f"{'='*62}")

    print(f"\n  Compound growth projection (same edge):")
    dt   = len(tdf) / days
    wr2  = wr / 100
    risk = PARAMS["RiskPct"] / 100
    rr_v = PARAMS["RewardPerTrade"] / PARAMS["RiskPerTrade"]
    for day in [30, 60, 90, 180]:
        b2 = 100.0
        for _ in range(day):
            w  = dt * wr2
            lo = dt * (1 - wr2)
            b2 *= (1 + w * risk * rr_v - lo * risk)
        print(f"    Day {day:3d}: ${b2:>9.2f}  ({(b2-100):.1f}% gain)")


if __name__ == "__main__":
    connect()
    SYMBOL_CONFIG["_atr_min"] = ATR_MIN_PIPS

    print(f"Fetching {BARS_6M} M1 bars for {SYMBOL} (6 months)...")
    raw = fetch_ohlcv(SYMBOL, mt5.TIMEFRAME_M1, BARS_6M)
    pip = get_pip_size(SYMBOL)
    days = (raw.index[-1] - raw.index[0]).days
    print(f"Bars: {len(raw)}  |  Period: {days} days  |  Pip: {pip}")
    print(f"From: {raw.index[0]}  To: {raw.index[-1]}")

    df = add_indicators(raw, PARAMS)
    df = df.dropna()
    print(f"After dropna: {len(df)} bars")

    a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
        df, PARAMS, pip, session_hours=SESSIONS)
    sigs = signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid,
                                PARAMS["RequiredScore"], df.index)

    nsig = int((sigs != 0).sum())
    print(f"Signals: {nsig} total ({nsig/days:.1f}/day)  |  Sessions: {SESSIONS}")

    tdf, dpnl = simulate_exact(df, sigs, PARAMS, SPREAD_COST, MAX_TRADES_DAY)
    print_report(tdf, dpnl, days)

    disconnect()
    print("\nDone.")
