# encoding: utf-8
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
import sys
sys.path.insert(0, '.')
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size
from backtest import add_indicators
from config import SYMBOL_CONFIG


def btc_hfq_signals(df, pip, sessions=None):
    if sessions is None:
        sessions = [(9, 13), (20, 23)]
    close = df["Close"].values
    high  = df["High"].values
    low   = df["Low"].values
    open_ = df["Open"].values
    ef    = df["ema_fast"].values
    es    = df["ema_slow"].values
    rsi   = df["rsi"].values
    atr   = df["atr"].values
    macd  = df["macd"].values
    msig  = df["macd_sig"].values
    times = df.index
    n     = len(df)
    sig   = np.zeros(n, dtype=np.int8)
    LB    = 5

    def in_sess(h):
        for s, e in sessions:
            if s <= h < e:
                return True
        return False

    for i in range(LB + 2, n - 1):
        if not in_sess(times[i].hour):
            continue
        if np.isnan(atr[i]) or atr[i] < pip * 3:
            continue
        lo = max(0, i - 50)
        atr_ok = float(atr[i]) > float(np.nanpercentile(atr[lo:i], 40))
        rh = float(np.max(high[i - LB:i]))
        rl = float(np.min(low[i - LB:i]))
        bo_bull = float(close[i]) > rh and float(close[i - 1]) <= rh
        bo_bear = float(close[i]) < rl and float(close[i - 1]) >= rl
        trend_bull = float(ef[i]) > float(es[i])
        trend_bear = float(ef[i]) < float(es[i])
        rsi_ok_bull = 28 < float(rsi[i]) < 72
        rsi_ok_bear = 28 < float(rsi[i]) < 72
        macd_bull = float(macd[i]) > float(msig[i])
        macd_bear = float(macd[i]) < float(msig[i])
        body = abs(float(close[i]) - float(open_[i]))
        rng  = float(high[i]) - float(low[i])
        ratio = body / max(rng, 1e-9)
        strong_bull = float(close[i]) > float(open_[i]) and ratio >= 0.35
        strong_bear = float(close[i]) < float(open_[i]) and ratio >= 0.35

        if bo_bull and trend_bull and rsi_ok_bull and (macd_bull or strong_bull) and atr_ok:
            sig[i] = 1
        elif bo_bear and trend_bear and rsi_ok_bear and (macd_bear or strong_bear) and atr_ok:
            sig[i] = -1
        elif float(rsi[i]) <= 18 and trend_bull and strong_bull and atr_ok:
            sig[i] = 1
        elif float(rsi[i]) >= 82 and trend_bear and strong_bear and atr_ok:
            sig[i] = -1

    return pd.Series(sig, index=df.index)


def simulate_hfq(df, sigs, atr_sl, rr, risk_pct, max_bars, spread, initial, max_d):
    bal  = initial
    peak = initial
    mdd  = 0.0
    ha   = df["High"].values
    la   = df["Low"].values
    oa   = df["Open"].values
    ca   = df["Close"].values
    aa   = df["atr"].values
    sa   = sigs.values
    times = df.index
    trades = []
    ot     = None
    daily  = {}
    dpnl   = {}

    for i in range(1, len(ha) - 1):
        cur_dd = (peak - bal) / peak * 100 if peak > 0 else 0
        if cur_dd > 40:
            break
        h = float(ha[i])
        l = float(la[i])

        if ot is not None:
            res  = None
            pnl  = 0.0
            bars = i - ot["i"]
            if max_bars > 0 and bars >= max_bars:
                c   = float(ca[i])
                pnl = (ot["r"] * (c - ot["e"]) / ot["sd"]
                       if ot["d"] == 1
                       else ot["r"] * (ot["e"] - c) / ot["sd"]) - spread
                res = "TO"
            elif ot["d"] == 1:
                if l <= ot["sl"]:
                    pnl = ot["r"] * (ot["sl"] - ot["e"]) / ot["sd"] - spread
                    res = "SL"
                elif h >= ot["tp"]:
                    pnl = ot["rw"] - spread
                    res = "TP"
            else:
                if h >= ot["sl"]:
                    pnl = ot["r"] * (ot["e"] - ot["sl"]) / ot["sd"] - spread
                    res = "SL"
                elif l <= ot["tp"]:
                    pnl = ot["rw"] - spread
                    res = "TP"
            if res:
                bal  += pnl
                day   = times[i].date()
                dpnl[day] = dpnl.get(day, 0) + pnl
                trades.append({"pnl": round(pnl, 3), "hr": ot["hr"],
                               "res": res, "bal": round(bal, 2), "date": day})
                ot = None
            peak = max(peak, bal)
            mdd  = max(mdd, (peak - bal) / peak * 100 if peak > 0 else 0)

        if ot is None and int(sa[i]) != 0:
            day = times[i].date()
            daily[day] = daily.get(day, 0) + 1
            if daily[day] > max_d:
                continue
            sig_v = int(sa[i])
            entry = float(oa[i + 1])
            av    = float(aa[i])
            if np.isnan(av) or av <= 0:
                continue
            sd = max(av * atr_sl, 0.1 * 5)
            r  = bal * risk_pct / 100.0
            rw = r * rr
            sl = entry - sd if sig_v == 1 else entry + sd
            tp = entry + sd * rr if sig_v == 1 else entry - sd * rr
            ot = {"d": sig_v, "e": entry, "sl": sl, "tp": tp,
                  "sd": sd, "r": r, "rw": rw, "i": i, "hr": int(times[i].hour)}

    return pd.DataFrame(trades), dpnl


def print_results(label, tdf, dpnl, days):
    if tdf is None or tdf.empty:
        print(f"{label}: no trades")
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
    worst = min(dv) if dv else 0
    avg  = sum(dv) / len(dv) if dv else 0
    pos  = sum(1 for v in dv if v > 0)

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Trades/day : {len(tdf)/days:.1f}   Total: {len(tdf)}")
    print(f"  Win Rate   : {wr:.1f}%")
    print(f"  Prof Factor: {pf:.2f}")
    print(f"  Net PnL    : ${net:.2f}")
    print(f"  Final Bal  : ${100+net:.2f}")
    print(f"  Max DD     : {mdd:.1f}%")
    print(f"  Best day   : ${best:.2f}")
    print(f"  Worst day  : ${worst:.2f}")
    print(f"  Avg/day    : ${avg:.2f}")
    print(f"  Green days : {pos}/{len(dv)}  ({pos/max(len(dv),1)*100:.0f}%)")
    print(f"\n  Daily PnL (all trading days):")
    for d, v in sorted(dpnl.items()):
        tag = "WIN " if v >= 0 else "LOSS"
        bar = "#" * min(int(abs(v) / 1.5), 35)
        sign = "+" if v >= 0 else ""
        print(f"    {d}  {sign}${v:>7.2f}  {tag}  {bar}")

    # Compound projection
    print(f"\n  COMPOUND GROWTH PROJECTION:")
    b = 100.0
    dt = len(tdf) / days
    wr2 = wr / 100
    risk = float(label.split("%")[0].split()[-1]) / 100
    rr_val = 2.5
    for day in [7, 14, 30, 60, 90, 180]:
        b2 = 100.0
        for _ in range(day):
            w = dt * wr2
            lo = dt * (1 - wr2)
            b2 *= (1 + w * risk * rr_val - lo * risk)
        print(f"    Day {day:3d}: ${b2:>9.2f}  ({(b2-100):.1f}% gain)")


if __name__ == "__main__":
    connect()
    SYMBOL_CONFIG["_atr_min"] = 3.0
    raw = fetch_ohlcv("BTCUSD", mt5.TIMEFRAME_M1, 86400)
    pip = get_pip_size("BTCUSD")
    days = (raw.index[-1] - raw.index[0]).days

    p = {
        "EMA_Fast": 9, "EMA_Slow": 21, "RSI_Period": 7,
        "RSI_OB": 70, "RSI_OS": 30, "ATR_Period": 14,
        "ATR_SL_Multi": 0.8, "BB_Period": 20, "BB_Deviation": 2.0,
        "MACD_Fast": 8, "MACD_Slow": 17, "MACD_Signal": 9,
        "MomCandles": 2, "MinCandleBody": 0.25, "RequiredScore": 3,
        "EMASlopePeriod": 5, "MaxTradeBars": 0, "InitialBalance": 100,
        "RiskPct": 5.0, "RiskPerTrade": 5, "RewardPerTrade": 15,
        "MaxDrawdownPct": 40, "UseTrailingTP": False,
        "TrailTrigger": 1, "TrailStep": 0.5,
    }
    df = add_indicators(raw, p)
    df = df.dropna()

    print(f"Bars: {len(raw)} | Period: {days} days")

    sigs = btc_hfq_signals(df, pip, [(9, 13), (20, 23)])
    nsig = int((sigs != 0).sum())
    print(f"HFQ signals generated: {nsig}  ({nsig/days:.1f}/day)")

    for risk_pct, rr, max_d, label in [
        (3.0,  2.5, 10, "Conservative  3%/trade | RR 1:2.5"),
        (5.0,  2.5, 12, "Moderate      5%/trade | RR 1:2.5"),
        (10.0, 3.0, 15, "Aggressive   10%/trade | RR 1:3.0"),
    ]:
        tdf, dpnl = simulate_hfq(df, sigs, 0.8, rr, risk_pct, 60, 0.25, 100.0, max_d)
        print_results(label, tdf, dpnl, days)

    disconnect()
    print("\nDone.")
