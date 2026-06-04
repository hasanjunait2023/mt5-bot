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
       "GBPJPY": 0.01, "EURGBP": 0.0001, "XAGUSD": 0.01, "BTCUSD": 1.0}
# round-trip cost in PRICE units (spread + slippage, conservative)
COST = {"USDJPY": 0.020, "AUDUSD": 0.00018, "GBPUSD": 0.00020, "AUDJPY": 0.028,
        "NZDJPY": 0.038, "NZDUSD": 0.00024, "XAUUSD": 0.45,
        "EURUSD": 0.00015, "USDCHF": 0.00022, "USDCAD": 0.00025, "EURJPY": 0.025,
        "GBPJPY": 0.035, "EURGBP": 0.00022, "XAGUSD": 0.04, "BTCUSD": 40.0}


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


def s6_sweep_reclaim(df, sym):
    """Fake-breakout / stop-hunt reversal (S6). Sweep a Donchian(20) extreme then
    close back inside, entered WITH the HTF trend (EMA200 proxy). RSI 30-70. TP 1:2."""
    df = df.copy()
    df["rsi"] = rsi(df["close"])
    df["ema"] = df["close"].ewm(span=200, adjust=False).mean()
    N = 20
    df["dch"] = df["high"].rolling(N).max().shift(1)
    df["dcl"] = df["low"].rolling(N).min().shift(1)
    rows = df.reset_index(drop=True)
    buf = 2 * PIP[sym]
    setups = []
    for i in range(N + 1, len(rows) - 1):
        r = rows.iloc[i]
        if not (0 <= r["hour"] < 6):           # Asian session entries
            continue
        if not (30 <= r["rsi"] <= 70):
            continue
        if np.isnan(r["dch"]) or np.isnan(r["ema"]):
            continue
        up = r["close"] > r["ema"]
        if up and r["low"] < r["dcl"] and r["close"] > r["dcl"]:      # sweep low, reclaim, uptrend → long
            sl = r["low"] - buf; risk = r["close"] - sl
            if risk > 0:
                setups.append({"idx": i, "dir": 1, "sl": sl, "tp": r["close"] + 2 * risk, "exit_hour": 7})
        elif (not up) and r["high"] > r["dch"] and r["close"] < r["dch"]:  # sweep high, reclaim, downtrend → short
            sl = r["high"] + buf; risk = sl - r["close"]
            if risk > 0:
                setups.append({"idx": i, "dir": -1, "sl": sl, "tp": r["close"] - 2 * risk, "exit_hour": 7})
    return setups


def s1c_fade_atr(df, sym):
    """S1 fade but with a VOLATILITY-based stop (SL = edge - 1.0*ATR14) instead of
    a fixed pip stop — required for high-priced assets (gold/silver/BTC) where a
    fixed '12 pip' stop is absurdly tight and inflates PF. Realistic test."""
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
                setups.append({"idx": idx, "dir": 1, "sl": lo - 1.0 * a,
                               "tp": lo + 0.70 * width, "exit_hour": 7})
            elif r["high"] >= hi:
                setups.append({"idx": idx, "dir": -1, "sl": hi + 1.0 * a,
                               "tp": hi - 0.70 * width, "exit_hour": 7})
    return sorted(setups, key=lambda s: s["idx"])


def s5b_gold_v2(df, sym):
    """Gold breakout v2 — SGE-aligned window. Box 00:00-01:30 UTC, execute in the
    high-volume 01:30-06:00 window (SGE 01:30 + MCX 03:30), breakout close beyond box
    + EMA200 bias, SL 1.5*ATR(14), TP 1:2, exit before 08:00."""
    df = df.copy()
    df["atr"] = atr(df); df["ema"] = df["close"].ewm(span=200, adjust=False).mean()
    df["m"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    setups = []
    for _, g in df.groupby("date"):
        box = g[(g["m"] >= 0) & (g["m"] < 90)]      # 00:00-01:30
        if len(box) < 2:
            continue
        hi, lo = box["high"].max(), box["low"].min()
        win = g[(g["m"] >= 90) & (g["m"] < 360)]     # 01:30-06:00
        for idx, r in win.iterrows():
            a = r["atr"]
            if np.isnan(a) or a <= 0:
                continue
            up = r["close"] > r["ema"]
            if r["close"] > hi and up:
                sl = r["low"] - 1.5 * a
                setups.append({"idx": idx, "dir": 1, "sl": sl, "tp": r["close"] + 2 * (r["close"] - sl), "exit_hour": 8}); break
            if r["close"] < lo and not up:
                sl = r["high"] + 1.5 * a
                setups.append({"idx": idx, "dir": -1, "sl": sl, "tp": r["close"] - 2 * (sl - r["close"]), "exit_hour": 8}); break
    return sorted(setups, key=lambda s: s["idx"])


# ── candidate strategies (distinct signals, all ATR-stop) ──────────────────────
def _session_vwap(g):
    tp = (g["high"] + g["low"] + g["close"]) / 3.0
    return (tp * g["volume"]).cumsum() / g["volume"].cumsum().replace(0, np.nan)


def stoch_k(df, n=14):
    ll = df["low"].rolling(n).min(); hh = df["high"].rolling(n).max()
    return 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)


def v_vwap(df, sym):
    """V1 — VWAP reversion. Fade >1.5*ATR from session VWAP back to VWAP."""
    df = df.copy(); df["atr"] = atr(df)
    setups = []
    for _, g in df.groupby("date"):
        vw = _session_vwap(g)
        for idx, r in g.iterrows():
            if not (2 <= r["hour"] < 7):
                continue
            a = r["atr"]; v = vw.get(idx, np.nan)
            if a != a or a <= 0 or v != v:
                continue
            dev = r["close"] - v
            if dev < -1.5 * a:
                setups.append({"idx": idx, "dir": 1, "sl": r["close"] - 1.5 * a, "tp": v, "exit_hour": 7})
            elif dev > 1.5 * a:
                setups.append({"idx": idx, "dir": -1, "sl": r["close"] + 1.5 * a, "tp": v, "exit_hour": 7})
    return sorted(setups, key=lambda s: s["idx"])


def v_stoch(df, sym):
    """V2 — Stochastic fade. Cross up out of <20 → long; down out of >80 → short. TP 1.5R."""
    df = df.copy(); df["atr"] = atr(df); df["k"] = stoch_k(df)
    rows = df.reset_index(drop=True); setups = []
    for i in range(15, len(rows) - 1):
        r = rows.iloc[i]; p = rows.iloc[i - 1]
        if not (0 <= r["hour"] < 6):
            continue
        a = r["atr"]
        if a != a or a <= 0 or r["k"] != r["k"] or p["k"] != p["k"]:
            continue
        if p["k"] < 20 and r["k"] >= 20:
            sl = r["close"] - a; setups.append({"idx": i, "dir": 1, "sl": sl, "tp": r["close"] + 1.5 * (r["close"] - sl), "exit_hour": 7})
        elif p["k"] > 80 and r["k"] <= 80:
            sl = r["close"] + a; setups.append({"idx": i, "dir": -1, "sl": sl, "tp": r["close"] - 1.5 * (sl - r["close"]), "exit_hour": 7})
    return setups


def v_bb(df, sym):
    """V3 — Bollinger(20,2) fade to mid, ATR stop, RSI 30-70 filter."""
    df = df.copy(); df["atr"] = atr(df); df["rsi"] = rsi(df["close"])
    mid = df["close"].rolling(20).mean(); sd = df["close"].rolling(20).std()
    df["mid"] = mid; df["up"] = mid + 2 * sd; df["lo"] = mid - 2 * sd
    rows = df.reset_index(drop=True); setups = []
    for i in range(20, len(rows) - 1):
        r = rows.iloc[i]
        if not (2 <= r["hour"] < 7) or not (30 <= r["rsi"] <= 70):
            continue
        a = r["atr"]
        if a != a or a <= 0 or r["mid"] != r["mid"]:
            continue
        if r["close"] < r["lo"]:
            setups.append({"idx": i, "dir": 1, "sl": r["close"] - a, "tp": r["mid"], "exit_hour": 7})
        elif r["close"] > r["up"]:
            setups.append({"idx": i, "dir": -1, "sl": r["close"] + a, "tp": r["mid"], "exit_hour": 7})
    return setups


def v_rsi2(df, sym):
    """V4 — RSI(2) extreme reversion. <10 long / >90 short, TP at SMA5, ATR stop."""
    df = df.copy(); df["atr"] = atr(df); df["r2"] = rsi(df["close"], 2); df["sma5"] = df["close"].rolling(5).mean()
    rows = df.reset_index(drop=True); setups = []
    for i in range(5, len(rows) - 1):
        r = rows.iloc[i]
        if not (0 <= r["hour"] < 6):
            continue
        a = r["atr"]
        if a != a or a <= 0 or r["r2"] != r["r2"] or r["sma5"] != r["sma5"]:
            continue
        if r["r2"] < 10:
            setups.append({"idx": i, "dir": 1, "sl": r["close"] - a, "tp": max(r["sma5"], r["close"] + 0.5 * a), "exit_hour": 7})
        elif r["r2"] > 90:
            setups.append({"idx": i, "dir": -1, "sl": r["close"] + a, "tp": min(r["sma5"], r["close"] - 0.5 * a), "exit_hour": 7})
    return setups


def v_nightscalp(df, sym):
    """V6 — 'night scalper' inverted-RR (claimed 75-85% WR). Range-edge touch entry,
    SMALL TP (0.7*ATR) + WIDE stop (2.0*ATR). High hit-rate, small wins, big losses —
    tests whether the inverted-RR range-scalp profile is actually profitable."""
    df = df.copy(); df["atr"] = atr(df); df["rsi"] = rsi(df["close"])
    setups = []
    for _, g in df.groupby("date"):
        rng = _day_range(g, 0, 2)
        if not rng:
            continue
        hi, lo = rng
        win = g[(g["hour"] >= 2) & (g["hour"] < 7)]
        for idx, r in win.iterrows():
            a = r["atr"]
            if a != a or a <= 0 or not (30 <= r["rsi"] <= 70):
                continue
            if r["low"] <= lo:
                setups.append({"idx": idx, "dir": 1, "sl": r["close"] - 2.0 * a, "tp": r["close"] + 0.7 * a, "exit_hour": 7})
            elif r["high"] >= hi:
                setups.append({"idx": idx, "dir": -1, "sl": r["close"] + 2.0 * a, "tp": r["close"] - 0.7 * a, "exit_hour": 7})
    return sorted(setups, key=lambda s: s["idx"])


def v_pdhl(df, sym):
    """V5 — fade Previous-Day High/Low during Asia. Touch PDH→short, PDL→long,
    target the prior-day midpoint, ATR stop. Distinct structural level vs the 00-02 range."""
    df = df.copy(); df["atr"] = atr(df)
    daily = df.groupby("date").agg(h=("high", "max"), l=("low", "min"))
    daily["pdh"] = daily["h"].shift(1); daily["pdl"] = daily["l"].shift(1)
    daily["pmid"] = (daily["pdh"] + daily["pdl"]) / 2.0
    setups = []
    for d, g in df.groupby("date"):
        if d not in daily.index:
            continue
        pdh, pdl, pmid = daily.loc[d, "pdh"], daily.loc[d, "pdl"], daily.loc[d, "pmid"]
        if pdh != pdh or pdl != pdl:
            continue
        win = g[(g["hour"] >= 0) & (g["hour"] < 7)]
        for idx, r in win.iterrows():
            a = r["atr"]
            if a != a or a <= 0:
                continue
            if r["high"] >= pdh:
                setups.append({"idx": idx, "dir": -1, "sl": pdh + 1.0 * a, "tp": pmid, "exit_hour": 7}); break
            if r["low"] <= pdl:
                setups.append({"idx": idx, "dir": 1, "sl": pdl - 1.0 * a, "tp": pmid, "exit_hour": 7}); break
    return sorted(setups, key=lambda s: s["idx"])


STRATS = {
    "S1_fade":     (s1_fade,     ["USDJPY", "AUDUSD", "EURUSD", "GBPUSD", "USDCHF",
                                  "USDCAD", "AUDJPY", "NZDJPY", "EURJPY", "GBPJPY",
                                  "NZDUSD", "EURGBP"]),
    "S2_ict_sweep":(s2_ict_sweep,["USDJPY", "AUDUSD", "NZDUSD", "AUDJPY", "NZDJPY", "XAUUSD"]),
    "S3_pipstorm": (s3_pipstorm, ["GBPUSD"]),
    "S4_orb":      (s4_orb,      ["USDJPY", "AUDJPY", "NZDJPY", "AUDUSD", "NZDUSD"]),
    "S5_gold":     (s5_gold,     ["XAUUSD"]),
    "S5b_gold_v2": (s5b_gold_v2, ["XAUUSD"]),
    "S6_sweep":    (s6_sweep_reclaim, ["USDJPY", "AUDJPY", "EURJPY", "GBPJPY",
                                       "NZDJPY", "XAUUSD", "XAGUSD", "BTCUSD"]),
    "S1_metals_btc": (s1_fade,   ["XAUUSD", "XAGUSD", "BTCUSD"]),
    "S1c_fade_atr": (s1c_fade_atr, ["USDJPY", "AUDJPY", "XAUUSD", "XAGUSD", "BTCUSD",
                                    "EURJPY", "GBPJPY"]),
    "V1_vwap":  (v_vwap,  ["USDJPY", "AUDJPY", "XAUUSD", "BTCUSD", "EURJPY"]),
    "V2_stoch": (v_stoch, ["USDJPY", "AUDJPY", "XAUUSD", "BTCUSD", "EURJPY"]),
    "V3_bb":    (v_bb,    ["USDJPY", "AUDJPY", "XAUUSD", "BTCUSD", "EURJPY"]),
    "V4_rsi2":  (v_rsi2,  ["USDJPY", "AUDJPY", "XAUUSD", "BTCUSD", "EURJPY"]),
    "V5_pdhl":  (v_pdhl,  ["USDJPY", "AUDJPY", "XAUUSD", "BTCUSD", "EURJPY", "XAGUSD"]),
    "V6_nightscalp": (v_nightscalp, ["USDJPY", "AUDJPY", "XAUUSD", "BTCUSD", "EURJPY", "XAGUSD"]),
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
