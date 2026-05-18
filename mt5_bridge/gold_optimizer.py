# encoding: utf-8
"""
XAUUSD Gold Optimizer — high frequency, daily DD < 5%, compounding.
Targets: 2+ trades/day, WR > 48%, daily loss limit 4.5%, compound sizing.
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from itertools import product

sys.path.insert(0, '.')
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size
from backtest import add_indicators, compute_score_arrays, signals_from_scores
from config import SYMBOL_CONFIG

SYMBOL       = "XAUUSD"
BARS_6M      = 6 * 30 * 24 * 60
SPREAD_COST  = 0.30
ATR_MIN_PIPS = 2.0    # loosened for more signals
DAILY_DD_LIMIT = 4.5  # % — stop trading day if hit

BASE_PARAMS = {
    "EMA_Fast": 9, "EMA_Slow": 21, "RSI_Period": 7,
    "RSI_OB": 70, "RSI_OS": 30, "ATR_Period": 14,
    "BB_Period": 20, "BB_Deviation": 2.0,
    "MACD_Fast": 8, "MACD_Slow": 17, "MACD_Signal": 9,
    "MomCandles": 2, "MinCandleBody": 0.20,
    "EMASlopePeriod": 5,
    "InitialBalance": 100.0,
    "MaxDrawdownPct": 30.0,
    "UseTrailingTP": False, "TrailTrigger": 1.0, "TrailStep": 0.5,
    "MaxTradeBars": 0,
}

GRID = {
    "RequiredScore":  [3, 4, 5],
    "ATR_SL_Multi":   [0.5, 0.8, 1.0, 1.2],
    "RR":             [1.5, 2.0, 2.5],
    "RiskPct":        [1.0, 1.5, 2.0],
    "Sessions": [
        [(8, 12), (19, 23)],
        [(9, 13), (20, 23)],
        [(10, 13), (20, 23)],
        [(8, 17)],
        [(8, 13), (19, 23)],
    ],
}


def simulate(df, sigs, p, spread_cost, rr, riskpct, daily_dd_limit):
    bal   = p["InitialBalance"]
    peak  = bal
    asl   = p["ATR_SL_Multi"]
    max_dd = p["MaxDrawdownPct"] / 100.0

    ha    = df["High"].values
    la    = df["Low"].values
    oa    = df["Open"].values
    ca    = df["Close"].values
    aa    = df["atr"].values
    sa    = sigs.values
    times = df.index

    trades    = []
    ot        = None
    daily     = {}
    dpnl      = {}
    daily_start_bal = {}

    for i in range(1, len(ha) - 1):
        if peak > 0 and (peak - bal) / peak > max_dd:
            break

        h = float(ha[i])
        l = float(la[i])
        day = times[i].date()

        # track start-of-day balance for daily DD calculation
        if day not in daily_start_bal:
            daily_start_bal[day] = bal

        # daily DD check — stop trading today if exceeded
        day_dd = (daily_start_bal[day] - bal) / daily_start_bal[day] * 100 if daily_start_bal[day] > 0 else 0
        day_blocked = day_dd >= daily_dd_limit

        if ot is not None:
            res = None
            pnl = 0.0
            if ot["d"] == 1:
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
                dpnl[day] = dpnl.get(day, 0.0) + pnl
                trades.append({"pnl": round(pnl, 3), "res": res,
                               "bal": round(bal, 2), "date": day, "hr": ot["hr"]})
                ot = None

        if ot is None and not day_blocked and int(sa[i]) != 0:
            daily[day] = daily.get(day, 0) + 1
            if daily[day] > 20:
                continue
            sig_v = int(sa[i])
            entry = float(oa[i + 1])
            av    = float(aa[i])
            if np.isnan(av) or av <= 0:
                continue
            sd   = av * asl
            r    = bal * riskpct / 100.0
            rw   = r * rr
            sl   = entry - sd if sig_v == 1 else entry + sd
            tp   = entry + sd * rr if sig_v == 1 else entry - sd * rr
            ot   = {"d": sig_v, "e": entry, "sl": sl, "tp": tp,
                    "sd": sd, "r": r, "rw": rw, "i": i, "hr": int(times[i].hour)}

    return pd.DataFrame(trades), dpnl


def score_result(tdf, dpnl, days):
    if tdf is None or tdf.empty or len(tdf) < 10:
        return -999
    wins = tdf[tdf["pnl"] > 0]
    loss = tdf[tdf["pnl"] <= 0]
    tl   = loss["pnl"].abs().sum()
    pf   = wins["pnl"].sum() / tl if tl > 0 else 0
    wr   = len(wins) / len(tdf)
    tpd  = len(tdf) / days
    net  = tdf["pnl"].sum()
    dv   = list(dpnl.values())
    avg_dd = sum(abs(v) for v in dv if v < 0) / max(len([v for v in dv if v < 0]), 1)
    cum  = tdf["pnl"].cumsum() + 100
    pk   = cum.cummax()
    mdd  = ((pk - cum) / pk * 100).max()
    # scoring: reward frequency + WR + PF, penalize drawdown
    return (tpd * 2) + (wr * 10) + (pf * 3) + (net / 10) - (mdd / 5)


if __name__ == "__main__":
    connect()
    SYMBOL_CONFIG["_atr_min"] = ATR_MIN_PIPS

    print(f"Fetching {BARS_6M} M1 bars for {SYMBOL}...")
    raw = fetch_ohlcv(SYMBOL, mt5.TIMEFRAME_M1, BARS_6M)
    pip = get_pip_size(SYMBOL)
    days = (raw.index[-1] - raw.index[0]).days
    print(f"Bars: {len(raw)}  |  Period: {days} days  |  Pip: {pip}")

    # pre-compute indicators once for each EMA combo (only one set here)
    df_base = add_indicators(raw, BASE_PARAMS).dropna()

    keys   = ["RequiredScore", "ATR_SL_Multi", "RR", "RiskPct", "Sessions"]
    combos = list(product(*[GRID[k] for k in keys]))
    total  = len(combos)
    print(f"Testing {total} combinations...\n")

    results = []
    for idx, vals in enumerate(combos):
        p = BASE_PARAMS.copy()
        rs, asl, rr, riskpct, sessions = vals
        p["RequiredScore"] = rs
        p["ATR_SL_Multi"]  = asl
        p["RiskPct"]       = riskpct
        p["RiskPerTrade"]  = riskpct
        p["RewardPerTrade"] = riskpct * rr

        a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
            df_base, p, pip, session_hours=sessions)
        sigs = signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid, rs, df_base.index)

        nsig = int((sigs != 0).sum())
        if nsig < 5:
            continue

        tdf, dpnl = simulate(df_base, sigs, p, SPREAD_COST, rr, riskpct, DAILY_DD_LIMIT)
        sc = score_result(tdf, dpnl, days)
        if sc > -999 and not tdf.empty:
            wins = tdf[tdf["pnl"] > 0]
            loss = tdf[tdf["pnl"] <= 0]
            tl   = loss["pnl"].abs().sum()
            pf   = wins["pnl"].sum() / tl if tl > 0 else 0
            wr   = len(wins) / len(tdf) * 100
            net  = tdf["pnl"].sum()
            cum  = tdf["pnl"].cumsum() + 100
            pk   = cum.cummax()
            mdd  = ((pk - cum) / pk * 100).max()
            results.append({
                "score": sc, "RequiredScore": rs, "ATR_SL_Multi": asl,
                "RR": rr, "RiskPct": riskpct, "Sessions": str(sessions),
                "trades": len(tdf), "tpd": len(tdf)/days,
                "wr": wr, "pf": pf, "net": net, "mdd": mdd,
                "final": 100 + net,
            })

        if (idx + 1) % 50 == 0:
            print(f"  {idx+1}/{total} done...", flush=True)

    if not results:
        print("No profitable results found.")
        disconnect()
        sys.exit(1)

    rdf = pd.DataFrame(results).sort_values("score", ascending=False)
    top = rdf.head(10)

    print(f"\n{'='*70}")
    print(f"  TOP 10 RESULTS — XAUUSD | Daily DD < {DAILY_DD_LIMIT}% | Compounding")
    print(f"{'='*70}")
    for i, row in top.iterrows():
        print(f"\n  #{list(top.index).index(i)+1}  "
              f"WR={row['wr']:.1f}%  PF={row['pf']:.2f}  "
              f"DD={row['mdd']:.1f}%  Net=${row['net']:.2f}  "
              f"Trades/day={row['tpd']:.1f}  Final=${row['final']:.2f}")
        print(f"       Sessions     : {row['Sessions']}")
        print(f"       RequiredScore: {row['RequiredScore']}")
        print(f"       ATR_SL_Multi : {row['ATR_SL_Multi']}")
        print(f"       RR           : {row['RR']}")
        print(f"       RiskPct      : {row['RiskPct']}%")

    # ── Full simulation on best params ──────────────────────────────────────
    best = rdf.iloc[0]
    sessions_str = best["Sessions"]
    # parse sessions from string back
    import ast
    sessions = ast.literal_eval(sessions_str)

    p = BASE_PARAMS.copy()
    p["RequiredScore"] = int(best["RequiredScore"])
    p["ATR_SL_Multi"]  = float(best["ATR_SL_Multi"])
    p["RiskPct"]       = float(best["RiskPct"])
    p["RiskPerTrade"]  = float(best["RiskPct"])
    p["RewardPerTrade"] = float(best["RiskPct"]) * float(best["RR"])
    rr = float(best["RR"])

    a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
        df_base, p, pip, session_hours=sessions)
    sigs = signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid,
                                p["RequiredScore"], df_base.index)

    tdf, dpnl = simulate(df_base, sigs, p, SPREAD_COST, rr, p["RiskPct"], DAILY_DD_LIMIT)

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
    pos  = sum(1 for v in dv if v > 0)

    print(f"\n{'='*70}")
    print(f"  BEST PARAMS — FULL SIMULATION")
    print(f"{'='*70}")
    print(f"  Period        : {days} days")
    print(f"  Trades total  : {len(tdf)}  ({len(tdf)/days:.1f}/day)")
    print(f"  Win Rate      : {wr:.1f}%")
    print(f"  Profit Factor : {pf:.2f}")
    print(f"  Net PnL       : ${net:.2f}")
    print(f"  Final Balance : ${100+net:.2f}")
    print(f"  Max Drawdown  : {mdd:.1f}%")
    print(f"  Best day      : ${max(dv):.2f}")
    print(f"  Worst day     : ${min(dv):.2f}")
    print(f"  Avg/day       : ${sum(dv)/len(dv):.2f}")
    print(f"  Green days    : {pos}/{len(dv)} ({pos/max(len(dv),1)*100:.0f}%)")

    print(f"\n  Daily P&L:")
    for d, v in sorted(dpnl.items()):
        tag  = "WIN " if v >= 0 else "LOSS"
        bar  = "#" * min(int(abs(v) / 1.0), 40)
        sign = "+" if v >= 0 else ""
        print(f"    {d}  {sign}${v:>7.2f}  {tag}  {bar}")

    # Daily DD check
    print(f"\n  Daily DD analysis:")
    day_groups = tdf.groupby("date")["pnl"].sum()
    dd_days = day_groups[day_groups < 0]
    print(f"  Days with loss: {len(dd_days)}/{len(day_groups)}")
    worst_day_dd = (dd_days.min() / 100 * -100) if not dd_days.empty else 0
    print(f"  Worst single-day loss: ${dd_days.min():.2f} ({dd_days.min()/100*-100:.1f}% of $100)")
    days_over_5pct = sum(1 for v in dd_days if abs(v) > 5)
    print(f"  Days DD exceeded 5%: {days_over_5pct}")

    print(f"\n{'='*70}")
    print(f"  USE THESE PARAMS IN MT5 EA:")
    print(f"{'='*70}")
    print(f"  Sessions      = {sessions}")
    print(f"  RequiredScore = {int(best['RequiredScore'])}")
    print(f"  ATR_SL_Multi  = {best['ATR_SL_Multi']}")
    print(f"  RR            = {best['RR']}")
    print(f"  RiskPct       = {best['RiskPct']}%")
    print(f"  DailyDDLimit  = {DAILY_DD_LIMIT}%")
    print(f"  Compounding   = ON")

    disconnect()
    print("\nDone.")
