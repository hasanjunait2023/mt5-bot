"""
Asia fade parameter sweep — naive-touch entry (proven best in bt_improve), vary
TP fraction, SL ATR multiple, and exit hour. Judge by ROBUSTNESS, not best-pair:
a combo only "wins" if it beats base on the MEAN oos-PF across all 6 pairs AND
keeps >=5/6 pairs at oos-PF >= 1.3. Guards against per-pair curve-fitting.

    python3 -m trading_agents.asia_desk.bt_sweep
"""
import numpy as np
from trading_agents.asia_desk.backtest import (
    fetch, simulate, rsi, atr, stats, _day_range, PIP,
)

PAIRS = ["USDJPY", "AUDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "EURJPY"]
TPS = [0.5, 0.6, 0.7, 0.85, 1.0]
SLS = [0.75, 1.0, 1.5]
EXITS = [6, 7]


def gen(df, sym, tp_frac, sl_atr, exit_h):
    df = df.copy(); df["rsi"] = rsi(df["close"]); df["atr"] = atr(df)
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 2)
        if not rng:
            continue
        hi, lo = rng; width = hi - lo
        if width <= 0:
            continue
        win = g[(g["hour"] >= 2) & (g["hour"] < exit_h)]
        for idx, r in win.iterrows():
            a = r["atr"]
            if np.isnan(a) or a <= 0 or not (30 <= r["rsi"] <= 70):
                continue
            if r["low"] <= lo:
                setups.append({"idx": idx, "dir": 1, "sl": lo - sl_atr * a,
                               "tp": lo + tp_frac * width, "exit_hour": exit_h})
            elif r["high"] >= hi:
                setups.append({"idx": idx, "dir": -1, "sl": hi + sl_atr * a,
                               "tp": hi - tp_frac * width, "exit_hour": exit_h})
    return sorted(setups, key=lambda s: s["idx"])


def main():
    cache = {}
    for sym in PAIRS:
        try:
            cache[sym] = fetch(sym)
        except Exception as e:
            print(f"{sym}: fetch fail {e}")
    cuts = {s: cache[s]["ts"].iloc[int(len(cache[s]) * 0.6)] for s in cache}

    rows = []
    for tp in TPS:
        for sl in SLS:
            for ex in EXITS:
                oos_pfs, wrs, n_ok = [], [], 0
                for sym in PAIRS:
                    if sym not in cache:
                        continue
                    tr = simulate(cache[sym], gen(cache[sym], sym, tp, sl, ex), sym)
                    oos = stats([t for t in tr if t["ts"] > cuts[sym]], PIP[sym])
                    if oos:
                        oos_pfs.append(oos["pf"]); wrs.append(oos["wr"])
                        if oos["pf"] >= 1.3:
                            n_ok += 1
                rows.append({
                    "tp": tp, "sl": sl, "ex": ex,
                    "mean_oos_pf": float(np.mean(oos_pfs)) if oos_pfs else 0,
                    "min_oos_pf": float(np.min(oos_pfs)) if oos_pfs else 0,
                    "mean_wr": float(np.mean(wrs)) if wrs else 0,
                    "n_ok": n_ok,
                })

    base = next(r for r in rows if r["tp"] == 0.7 and r["sl"] == 1.0 and r["ex"] == 7)
    print(f"\n{'='*88}\nASIA FADE PARAM SWEEP — oos40 robustness across 6 pairs (50k bars ~1.4yr)\n{'='*88}")
    print(f"BASE (tp0.70 sl1.00 ex7): mean_oosPF={base['mean_oos_pf']:.2f} "
          f"min={base['min_oos_pf']:.2f} meanWR={base['mean_wr']:.1f}% pairs>=1.3:{base['n_ok']}/6\n")
    print(f"{'tp':>5}{'sl':>6}{'ex':>4} | {'meanPF':>7}{'minPF':>7}{'meanWR':>8}{'ok/6':>6}  verdict")
    for r in sorted(rows, key=lambda x: -x["mean_oos_pf"]):
        better = (r["mean_oos_pf"] > base["mean_oos_pf"] and r["n_ok"] >= 5
                  and r["min_oos_pf"] >= base["min_oos_pf"] - 0.02)
        tag = "<< robust beat" if better and r != base else ("BASE" if r == base else "")
        print(f"{r['tp']:>5.2f}{r['sl']:>6.2f}{r['ex']:>4} | {r['mean_oos_pf']:>7.2f}"
              f"{r['min_oos_pf']:>7.2f}{r['mean_wr']:>7.1f}%{r['n_ok']:>5}/6  {tag}")


if __name__ == "__main__":
    main()
