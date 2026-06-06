"""Per-pair confirm: live BASE (sl1.0) vs chosen (sl0.75), tp0.70 exit7, with DD."""
import numpy as np
from trading_agents.asia_desk.backtest import (
    fetch, simulate, rsi, atr, stats, _day_range, PIP,
)

PAIRS = ["USDJPY", "AUDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "EURJPY"]


def gen(df, sym, sl_atr):
    df = df.copy(); df["rsi"] = rsi(df["close"]); df["atr"] = atr(df)
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 2)
        if not rng:
            continue
        hi, lo = rng; width = hi - lo
        if width <= 0:
            continue
        win = g[(g["hour"] >= 2) & (g["hour"] < 7)]
        for idx, r in win.iterrows():
            a = r["atr"]
            if np.isnan(a) or a <= 0 or not (30 <= r["rsi"] <= 70):
                continue
            if r["low"] <= lo:
                setups.append({"idx": idx, "dir": 1, "sl": lo - sl_atr * a,
                               "tp": lo + 0.70 * width, "exit_hour": 7})
            elif r["high"] >= hi:
                setups.append({"idx": idx, "dir": -1, "sl": hi + sl_atr * a,
                               "tp": hi - 0.70 * width, "exit_hour": 7})
    return sorted(setups, key=lambda s: s["idx"])


def row(sym, df, sl):
    cut = df["ts"].iloc[int(len(df) * 0.6)]
    tr = simulate(df, gen(df, sym, sl), sym)
    a = stats(tr, PIP[sym]); o = stats([t for t in tr if t["ts"] > cut], PIP[sym])
    return (f"  sl{sl:.2f} | all n={a['n']:4d} PF={a['pf']:4.2f} WR={a['wr']:4.1f}% "
            f"DD={a['dd_pips']:8.1f}p | oos PF={o['pf']:4.2f} WR={o['wr']:4.1f}%")


def main():
    print("PER-PAIR CONFIRM — tp0.70 exit7 | BASE sl1.00 vs CHOSEN sl0.75\n" + "=" * 84)
    for sym in PAIRS:
        try:
            df = fetch(sym)
        except Exception as e:
            print(f"{sym}: fetch fail {e}"); continue
        print(sym)
        print(row(sym, df, 1.00))
        print(row(sym, df, 0.75))


if __name__ == "__main__":
    main()
