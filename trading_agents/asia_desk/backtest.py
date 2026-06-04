"""
Asian-Session multi-strategy backtest — real-cost screen.

Implements the 5 strategies in STRATEGY_SPECS.md and runs each on M15 bars pulled
from the live bridge /bars endpoint (read-only, no MT5 session). 5000 bars ≈ 72d
— a SCREEN to rank strategies, not a final verdict. Survivors (PF ≥ 1.3, stable
in/out-of-sample) graduate to a proper 2yr run + demo deploy.

ICT (S2) M1/M5 MSS+FVG is approximated on M15 (sweep + close-back-inside). Gold
(S5) HTF bias approximated with M15 EMA200. Noted in specs.

    python3 -m trading_agents.asia_desk.backtest            # all strategies
"""
import json
import urllib.request
import numpy as np
import pandas as pd

BRIDGE = "http://localhost:8090"
LIMIT = 50000

PIP = {"USDJPY": 0.01, "AUDUSD": 0.0001, "GBPUSD": 0.0001, "AUDJPY": 0.01,
       "NZDJPY": 0.01, "NZDUSD": 0.0001, "XAUUSD": 0.1,
       "EURUSD": 0.0001, "USDCHF": 0.0001, "USDCAD": 0.0001, "EURJPY": 0.01,
       "GBPJPY": 0.01, "EURGBP": 0.0001}
# round-trip cost in PRICE units (spread + slippage, conservative)
COST = {"USDJPY": 0.020, "AUDUSD": 0.00018, "GBPUSD": 0.00020, "AUDJPY": 0.028,
        "NZDJPY": 0.038, "NZDUSD": 0.00024, "XAUUSD": 0.45,
        "EURUSD": 0.00015, "USDCHF": 0.00022, "USDCAD": 0.00025, "EURJPY": 0.025,
        "GBPJPY": 0.035, "EURGBP": 0.00022}


# ── data ───────────────────────────────────────────────────────────────────────
def fetch(sym, tf="15min", limit=LIMIT):
    url = f"{BRIDGE}/bars/{sym}?timeframe={tf}&limit={limit}"
    with urllib.request.urlopen(url, timeout=90) as r:
        d = json.loads(r.read())
    df = pd.DataFrame({
        "ts": pd.to_datetime(d["time"], unit="s", utc=True),
        "open": d["open"], "high": d["high"], "low": d["low"],
        "close": d["close"], "volume": d["volume"],
    })
    df["hour"] = df["ts"].dt.hour
    df["date"] = df["ts"].dt.date
    return df


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50)


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"].shift()
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def daily_macd_hist(df):
    """Daily MACD histogram (12,26,9) reindexed onto M15 bars (prior-day value)."""
    d1 = df.set_index("ts")["close"].resample("1D").last().dropna()
    ema12 = d1.ewm(span=12, adjust=False).mean()
    ema26 = d1.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    hist_prev = hist.shift(1)            # use yesterday's completed hist
    rising = hist_prev > hist_prev.shift(1)
    s = pd.DataFrame({"h": hist_prev, "rising": rising})
    m = df["ts"].dt.normalize().map(s["h"]).to_numpy()
    r = df["ts"].dt.normalize().map(s["rising"]).to_numpy()
    return m, r


# ── generic simulator ──────────────────────────────────────────────────────────
def simulate(df, setups, sym):
    """setups: list of dict{idx,dir,sl,tp,exit_hour}. Walk forward, SL-first,
    time-exit at first bar with hour>=exit_hour on/after entry day. No overlap."""
    cost = COST[sym]
    o, h, l, c = (df["open"].to_numpy(), df["high"].to_numpy(),
                  df["low"].to_numpy(), df["close"].to_numpy())
    hr = df["hour"].to_numpy()
    n = len(df)
    trades = []
    last_exit = -1
    for s in setups:
        i = s["idx"]
        if i <= last_exit or i >= n - 1:
            continue
        d, sl, tp = s["dir"], s["sl"], s["tp"]
        entry = c[i]
        pnl = None
        j = i + 1
        while j < n:
            if d == 1:
                if l[j] <= sl: pnl = sl - entry; break
                if h[j] >= tp: pnl = tp - entry; break
            else:
                if h[j] >= sl: pnl = entry - sl; break
                if l[j] <= tp: pnl = entry - tp; break
            if hr[j] >= s["exit_hour"] and j > i:
                pnl = (c[j] - entry) if d == 1 else (entry - c[j])
                break
            j += 1
        if pnl is None:
            break
        trades.append({"idx": i, "ts": df["ts"].iloc[i], "pnl": pnl - cost})
        last_exit = j
    return trades


# ── strategies: each returns list of setups ────────────────────────────────────
def _day_range(g, h0, h1):
    w = g[(g["hour"] >= h0) & (g["hour"] < h1)]
    if len(w) < 2:
        return None
    return w["high"].max(), w["low"].min()


def s1_fade(df, sym):
    df = df.copy(); df["rsi"] = rsi(df["close"])
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 2)
        if not rng:
            continue
        hi, lo = rng; width = hi - lo
        if width <= 0:
            continue
        pip = PIP[sym]
        win = g[(g["hour"] >= 2) & (g["hour"] < 7)]
        for idx, r in win.iterrows():
            if not (30 <= r["rsi"] <= 70):
                continue
            if r["low"] <= lo:      # touch support → long
                setups.append({"idx": idx, "dir": 1, "sl": lo - 12 * pip,
                               "tp": lo + 0.70 * width, "exit_hour": 7})
            elif r["high"] >= hi:   # touch resistance → short
                setups.append({"idx": idx, "dir": -1, "sl": hi + 12 * pip,
                               "tp": hi - 0.70 * width, "exit_hour": 7})
    return sorted(setups, key=lambda s: s["idx"])


def s2_ict_sweep(df, sym):
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 5)
        if not rng:
            continue
        hi, lo = rng
        win = g[(g["hour"] >= 6) & (g["hour"] < 8)]
        swept = None
        for idx, r in win.iterrows():
            if swept is None:
                if r["high"] > hi:
                    swept = ("up", idx, r["high"])
                elif r["low"] < lo:
                    swept = ("down", idx, r["low"])
            else:
                kind, sidx, ext = swept
                if kind == "up" and r["close"] < hi:   # back inside → short
                    setups.append({"idx": idx, "dir": -1, "sl": ext + 2 * PIP[sym],
                                   "tp": lo, "exit_hour": 13}); break
                if kind == "down" and r["close"] > lo:  # back inside → long
                    setups.append({"idx": idx, "dir": 1, "sl": ext - 2 * PIP[sym],
                                   "tp": hi, "exit_hour": 13}); break
    return sorted(setups, key=lambda s: s["idx"])


def s3_pipstorm(df, sym):
    df = df.copy()
    mh, rising = daily_macd_hist(df)
    df["mh"], df["rising"] = mh, rising
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 8)
        if not rng:
            continue
        hi, lo = rng; height = hi - lo
        if height <= 0:
            continue
        win = g[(g["hour"] >= 8) & (g["hour"] < 12)]
        for idx, r in win.iterrows():
            long_ok = (r["mh"] > 0) and bool(r["rising"])
            short_ok = (r["mh"] < 0) and (not bool(r["rising"]))
            if r["high"] > hi and long_ok:
                setups.append({"idx": idx, "dir": 1, "sl": lo,
                               "tp": r["close"] + height, "exit_hour": 16}); break
            if r["low"] < lo and short_ok:
                setups.append({"idx": idx, "dir": -1, "sl": hi,
                               "tp": r["close"] - height, "exit_hour": 16}); break
    return sorted(setups, key=lambda s: s["idx"])


def s4_orb(df, sym):
    setups = []
    pip = PIP[sym]
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 1)            # first hour = 4 M15 bars
        if not rng:
            continue
        hi, lo = rng
        win = g[(g["hour"] >= 1) & (g["hour"] < 6)]
        for idx, r in win.iterrows():
            if r["close"] > hi:
                setups.append({"idx": idx, "dir": 1, "sl": lo,
                               "tp": r["close"] + 15 * pip, "exit_hour": 7}); break
            if r["close"] < lo:
                setups.append({"idx": idx, "dir": -1, "sl": hi,
                               "tp": r["close"] - 15 * pip, "exit_hour": 7}); break
    return sorted(setups, key=lambda s: s["idx"])


def s5_gold(df, sym):
    df = df.copy()
    df["atr"] = atr(df); df["ema"] = df["close"].ewm(span=200, adjust=False).mean()
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 2)
        if not rng:
            continue
        hi, lo = rng
        win = g[(g["hour"] >= 2) & (g["hour"] < 4)]
        for idx, r in win.iterrows():
            a = r["atr"]
            if np.isnan(a) or a <= 0:
                continue
            up_bias = r["close"] > r["ema"]
            if r["close"] > hi and up_bias:
                sl = r["low"] - 1.5 * a
                setups.append({"idx": idx, "dir": 1, "sl": sl,
                               "tp": r["close"] + 2 * (r["close"] - sl),
                               "exit_hour": 7}); break
            if r["close"] < lo and not up_bias:
                sl = r["high"] + 1.5 * a
                setups.append({"idx": idx, "dir": -1, "sl": sl,
                               "tp": r["close"] - 2 * (sl - r["close"]),
                               "exit_hour": 7}); break
    return sorted(setups, key=lambda s: s["idx"])


STRATS = {
    "S1_fade":     (s1_fade,     ["USDJPY", "AUDUSD", "EURUSD", "GBPUSD", "USDCHF",
                                  "USDCAD", "AUDJPY", "NZDJPY", "EURJPY", "GBPJPY",
                                  "NZDUSD", "EURGBP"]),
    "S2_ict_sweep":(s2_ict_sweep,["USDJPY", "AUDUSD", "NZDUSD", "AUDJPY", "NZDJPY", "XAUUSD"]),
    "S3_pipstorm": (s3_pipstorm, ["GBPUSD"]),
    "S4_orb":      (s4_orb,      ["USDJPY", "AUDJPY", "NZDJPY", "AUDUSD", "NZDUSD"]),
    "S5_gold":     (s5_gold,     ["XAUUSD"]),
}


def stats(trades, pip):
    if not trades:
        return None
    pnl = np.array([t["pnl"] for t in trades])
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    eq = np.cumsum(pnl); dd = (np.maximum.accumulate(eq) - eq).max()
    return {"n": len(trades), "pf": pf, "wr": (pnl > 0).mean() * 100,
            "pnl_pips": pnl.sum() / pip, "dd_pips": dd / pip}


def line(label, st):
    if not st:
        print(f"  {label:28s} no trades"); return
    inf = "  ⭐" if st["pf"] >= 1.3 and st["n"] >= 20 else ""
    print(f"  {label:28s} n={st['n']:4d}  PF={st['pf']:5.2f}  WR={st['wr']:4.1f}%  "
          f"netPips={st['pnl_pips']:8.1f}  maxDD={st['dd_pips']:7.1f}p{inf}")


def main():
    print(f"ASIAN-SESSION MULTI-STRATEGY SCREEN — M15 {LIMIT} bars (~72d), real cost")
    print("⭐ = PF≥1.3 & n≥20\n")
    import sys
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cache = {}
    for name, (fn, syms) in STRATS.items():
        if only and name != only:
            continue
        print(name)
        agg = []
        for sym in syms:
            if sym not in cache:
                try:
                    cache[sym] = fetch(sym)
                except Exception as e:
                    print(f"  {sym}: fetch fail {e}"); continue
            df = cache[sym]
            tr = simulate(df, fn(df, sym), sym)
            agg += tr
            cut = df["ts"].iloc[int(len(df) * 0.6)]
            line(f"{sym}/all", stats(tr, PIP[sym]))
            line(f"{sym}/oos40", stats([t for t in tr if t["ts"] > cut], PIP[sym]))
        if len(syms) > 1:
            # combined uses USDJPY pip as common unit only for display scale
            line("ALL/combined(pips~)", stats(agg, 0.01))
        print()


if __name__ == "__main__":
    main()
