"""
Asia fade improvement A/B — compares the live S1c_fade_atr baseline against
candidate filters on the SAME 50k-bar (~1.4yr) real-cost data, in + oos40.

Variants tested (all keep SL=1.0*ATR, TP=0.70*width, exit 07:00, RSI 30-70):
  base      — exact live logic (naive touch)
  reclaim   — require the touch bar to CLOSE back inside the range (reject, not break)
  rr0.8     — skip setups whose reward/risk (0.70*width / 1.0*ATR) < 0.8
  rr1.0     — same, RR floor 1.0
  recl+rr08 — reclaim AND RR floor 0.8
  width0.5  — skip ranges narrower than 0.5*ATR (pure noise)

    python3 -m trading_agents.asia_desk.bt_improve
"""
import numpy as np
from trading_agents.asia_desk.backtest import (
    fetch, simulate, rsi, atr, stats, _day_range, PIP,
)

PAIRS = ["USDJPY", "AUDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "EURJPY"]


def gen(df, sym, reclaim=False, min_rr=0.0, min_width_atr=0.0):
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
            if min_width_atr and width < min_width_atr * a:
                continue
            if min_rr and (0.70 * width) < min_rr * (1.0 * a):
                continue
            if r["low"] <= lo:
                if reclaim and not (r["close"] > lo):
                    continue
                setups.append({"idx": idx, "dir": 1, "sl": lo - 1.0 * a,
                               "tp": lo + 0.70 * width, "exit_hour": 7})
            elif r["high"] >= hi:
                if reclaim and not (r["close"] < hi):
                    continue
                setups.append({"idx": idx, "dir": -1, "sl": hi + 1.0 * a,
                               "tp": hi - 0.70 * width, "exit_hour": 7})
    return sorted(setups, key=lambda s: s["idx"])


VARIANTS = {
    "base":       dict(),
    "reclaim":    dict(reclaim=True),
    "rr0.8":      dict(min_rr=0.8),
    "rr1.0":      dict(min_rr=1.0),
    "recl+rr08":  dict(reclaim=True, min_rr=0.8),
    "width0.5":   dict(min_width_atr=0.5),
    "recl+w0.5":  dict(reclaim=True, min_width_atr=0.5),
}


def fmt(st):
    if not st:
        return f"{'—':>26}"
    star = "*" if (st["pf"] >= 1.3 and st["n"] >= 20) else " "
    return f"n={st['n']:4d} PF={st['pf']:4.2f} WR={st['wr']:4.1f}%{star}"


def main():
    cache = {}
    for sym in PAIRS:
        try:
            cache[sym] = fetch(sym)
        except Exception as e:
            print(f"{sym}: fetch fail {e}")
    print(f"\n{'='*100}\nASIA FADE IMPROVEMENT A/B — 50k bars (~1.4yr) real cost | in-sample / oos40\n{'='*100}")
    for sym in PAIRS:
        if sym not in cache:
            continue
        df = cache[sym]
        cut = df["ts"].iloc[int(len(df) * 0.6)]
        print(f"\n{sym}")
        for vname, kw in VARIANTS.items():
            tr = simulate(df, gen(df, sym, **kw), sym)
            allst = stats(tr, PIP[sym])
            oos = stats([t for t in tr if t["ts"] > cut], PIP[sym])
            print(f"  {vname:11s} | all  {fmt(allst):30s} | oos {fmt(oos)}")


if __name__ == "__main__":
    main()
