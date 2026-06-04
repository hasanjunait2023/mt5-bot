"""
Asian-Session Mean-Reversion (ASMR) — first-pass edge screen.

Hypothesis: AUDJPY / NZDJPY / USDJPY range-revert during the Tokyo session
(00:00-06:00 UTC). Fade Bollinger-band pierces back to the mean. Momentum
strategies (MTF) deliberately skip this window; this tests whether a
mean-reversion edge lives there instead.

Read-only: pulls bars from the live bridge /bars HTTP endpoint (no MT5 session,
no live-system disruption). 5000 M15 bars ≈ 72 days — a SCREEN, not a verdict.
If PF clears ~1.3 here, the next step is a proper 2yr in/out-of-sample run.

    python3 asia_meanrev_backtest.py
"""
import json
import urllib.request
import numpy as np
import pandas as pd

BRIDGE = "http://localhost:8090"
PAIRS = ["AUDJPY", "NZDJPY", "USDJPY"]
TF = "15min"
LIMIT = 5000

# Round-trip cost in PRICE (JPY pip = 0.01): spread + slippage, conservative.
COST = {"AUDJPY": 0.030, "NZDJPY": 0.040, "USDJPY": 0.020}

# Strategy params
BB_N, BB_K = 20, 2.0
RSI_N = 2
ATR_N = 14
RSI_BUY, RSI_SELL = 15.0, 85.0
SL_ATR = 1.5
BO_TP_ATR = 2.0                  # breakout extension target
BO_SL_ATR = 1.0                  # breakout stop
SESS_START, SESS_END = 0, 6      # entry hours [0,6); force-exit at hour >= EXIT_H
EXIT_H = 7


def fetch(sym):
    url = f"{BRIDGE}/bars/{sym}?timeframe={TF}&limit={LIMIT}"
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.loads(r.read())
    df = pd.DataFrame({
        "time": pd.to_datetime(d["time"], unit="s", utc=True),
        "open": d["open"], "high": d["high"], "low": d["low"],
        "close": d["close"], "volume": d["volume"],
    }).set_index("time")
    return df


def rsi(series, n):
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df, n):
    h, l, c = df["high"], df["low"], df["close"].shift()
    tr = pd.concat([(h - l), (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def indicators(df):
    mid = df["close"].rolling(BB_N).mean()
    sd = df["close"].rolling(BB_N).std()
    df["mid"] = mid
    df["upper"] = mid + BB_K * sd
    df["lower"] = mid - BB_K * sd
    df["rsi"] = rsi(df["close"], RSI_N)
    df["atr"] = atr(df, ATR_N)
    df["hour"] = df.index.hour
    return df.dropna()


def simulate(df, cost, mode="revert"):
    """Walk bars; one position at a time. Returns list of net-PnL (price units).

    mode='revert'   : fade band pierces back to the mean (TP=mid, SL=ATR beyond).
    mode='breakout' : trade WITH the band break (TP=ATR extension, SL back to mid).
    """
    trades = []
    i, n = 0, len(df)
    rows = df.reset_index(drop=True)
    while i < n - 1:
        r = rows.iloc[i]
        if not (SESS_START <= r["hour"] < SESS_END):
            i += 1
            continue
        sig = 0
        if mode == "revert":
            if r["close"] < r["lower"] and r["rsi"] < RSI_BUY:
                sig = 1
            elif r["close"] > r["upper"] and r["rsi"] > RSI_SELL:
                sig = -1
        elif mode == "revert_confirm":
            # rejection: prior bar pierced the band, this bar closes back inside
            p = rows.iloc[i - 1] if i > 0 else r
            if p["low"] < p["lower"] and r["close"] > r["lower"] and r["rsi"] < 35:
                sig = 1
            elif p["high"] > p["upper"] and r["close"] < r["upper"] and r["rsi"] > 65:
                sig = -1
        else:  # breakout: enter in the direction of the break
            if r["close"] > r["upper"] and r["rsi"] > RSI_SELL:
                sig = 1
            elif r["close"] < r["lower"] and r["rsi"] < RSI_BUY:
                sig = -1
        if sig == 0:
            i += 1
            continue
        entry = r["close"]
        if mode in ("revert", "revert_confirm"):
            tp = r["mid"]
            sl = entry - SL_ATR * r["atr"] if sig == 1 else entry + SL_ATR * r["atr"]
        else:  # breakout
            tp = entry + BO_TP_ATR * r["atr"] if sig == 1 else entry - BO_TP_ATR * r["atr"]
            sl = entry - BO_SL_ATR * r["atr"] if sig == 1 else entry + BO_SL_ATR * r["atr"]
        # walk forward
        j = i + 1
        pnl = None
        while j < n:
            b = rows.iloc[j]
            if sig == 1:
                if b["low"] <= sl:      # SL first (conservative)
                    pnl = sl - entry; break
                if b["high"] >= tp:
                    pnl = tp - entry; break
            else:
                if b["high"] >= sl:
                    pnl = entry - sl; break
                if b["low"] <= tp:
                    pnl = entry - tp; break
            if b["hour"] >= EXIT_H:      # time-stop at session end
                pnl = (b["close"] - entry) if sig == 1 else (entry - b["close"])
                break
            j += 1
        if pnl is None:
            break
        trades.append({"t": rows.iloc[i] if False else df.index[i],
                       "dir": sig, "pnl": pnl - cost})
        i = j + 1     # no overlapping positions
    return trades


def stats(trades, label):
    if not trades:
        print(f"  {label:20s} no trades")
        return None
    pnl = np.array([t["pnl"] for t in trades])
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    wr = (pnl > 0).mean() * 100
    # equity DD (in price units)
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq).max()
    print(f"  {label:20s} n={len(trades):4d}  PF={pf:5.2f}  WR={wr:4.1f}%  "
          f"netPnL={pnl.sum():8.3f}  maxDD={dd:6.3f}  exp/trade={pnl.mean():.4f}")
    return {"n": len(trades), "pf": pf, "wr": wr, "pnl": pnl.sum()}


def main():
    print(f"Asian-Session screen — M15, {LIMIT} bars (~72d), real cost. "
          f"Both modes per pair.\n")
    for sym in PAIRS:
        df = indicators(fetch(sym))
        span = f"{df.index[0].date()}→{df.index[-1].date()}"
        cut = df.index[int(len(df) * 0.6)]
        print(f"{sym}  ({span}, {len(df)} bars)")
        for mode in ("revert", "revert_confirm", "breakout"):
            tr = simulate(df, COST[sym], mode)
            stats(tr, f"  {mode}/all")
            ins = [t for t in tr if t["t"] <= cut]
            oos = [t for t in tr if t["t"] > cut]
            stats(ins, f"  {mode}/in-samp")
            stats(oos, f"  {mode}/oos")
        print()


if __name__ == "__main__":
    main()
