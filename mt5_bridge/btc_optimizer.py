"""
BTCUSD-specific optimizer — improved simulation with spread cost,
next-bar entry, daily trade limit, and wide parameter grid.

Usage:
    python btc_optimizer.py
"""

import itertools
import sys
from copy import deepcopy

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from backtest import add_indicators, compute_score_arrays, signals_from_scores


SYMBOL = "BTCUSD"
MONTHS = 2          # 2 months of M1 data
INITIAL_BALANCE = 100.0
RISK_PCT = 1.5      # % of equity per trade
MAX_DD_PCT = 0.20
MAX_TRADES_PER_DAY = 15
TOP_N = 5


# ─────────────────────────────────────────────
# Improved simulation — spread cost + next-bar entry + daily limit
# ─────────────────────────────────────────────

def simulate_btc(df: pd.DataFrame, signals: pd.Series, p: dict,
                 pip_size: float, spread_cost: float) -> pd.DataFrame:
    """
    Improved simulation for BTCUSD:
    - Entry at NEXT bar's open (no look-ahead bias)
    - Spread cost subtracted from every trade PnL
    - Daily trade limit enforced
    - Force-close after MaxTradeBars bars
    """
    balance    = INITIAL_BALANCE
    initial    = balance
    rr         = p["RR"]
    atr_sl     = p["ATR_SL_Multi"]
    max_bars   = p.get("MaxTradeBars", 0)

    high_arr  = df["High"].values
    low_arr   = df["Low"].values
    open_arr  = df["Open"].values
    close_arr = df["Close"].values
    atr_arr   = df["atr"].values
    sig_arr   = signals.values
    times     = df.index

    trades     = []
    open_trade = None
    daily_counts = {}

    for i in range(1, len(high_arr) - 1):
        if (initial - balance) / initial >= MAX_DD_PCT:
            break

        high  = high_arr[i]
        low   = low_arr[i]
        close = close_arr[i]

        # ── Manage open trade ──
        if open_trade is not None:
            direction  = open_trade["direction"]
            entry      = open_trade["entry"]
            sl_dist    = open_trade["sl_dist"]
            risk_usd   = open_trade["risk_usd"]
            reward_usd = open_trade["reward_usd"]
            sl         = open_trade["sl"]
            tp         = open_trade["tp"]

            bars_held = i - open_trade["entry_idx"]

            # Force-close timeout
            if max_bars > 0 and bars_held >= max_bars:
                pnl = risk_usd * (close - entry) / sl_dist if direction == 1 \
                      else risk_usd * (entry - close) / sl_dist
                pnl -= spread_cost
                balance += pnl
                trades.append({**open_trade, "exit": close, "exit_time": times[i],
                               "result": "TO", "pnl": round(pnl, 4),
                               "balance": round(balance, 4)})
                open_trade = None

            elif direction == 1:  # BUY
                if low <= sl:
                    pnl = risk_usd * (sl - entry) / sl_dist - spread_cost
                    balance += pnl
                    trades.append({**open_trade, "exit": sl, "exit_time": times[i],
                                   "result": "TSL" if pnl >= 0 else "SL",
                                   "pnl": round(pnl, 4), "balance": round(balance, 4)})
                    open_trade = None
                elif high >= tp:
                    pnl = reward_usd - spread_cost
                    balance += pnl
                    trades.append({**open_trade, "exit": tp, "exit_time": times[i],
                                   "result": "TP", "pnl": round(pnl, 4),
                                   "balance": round(balance, 4)})
                    open_trade = None

            else:  # SELL
                if high >= sl:
                    pnl = risk_usd * (entry - sl) / sl_dist - spread_cost
                    balance += pnl
                    trades.append({**open_trade, "exit": sl, "exit_time": times[i],
                                   "result": "TSL" if pnl >= 0 else "SL",
                                   "pnl": round(pnl, 4), "balance": round(balance, 4)})
                    open_trade = None
                elif low <= tp:
                    pnl = reward_usd - spread_cost
                    balance += pnl
                    trades.append({**open_trade, "exit": tp, "exit_time": times[i],
                                   "result": "TP", "pnl": round(pnl, 4),
                                   "balance": round(balance, 4)})
                    open_trade = None

        # ── New trade entry (signal at bar i → enter at open of bar i+1) ──
        if open_trade is None and sig_arr[i] != 0:
            day_key = times[i].date()
            daily_counts.setdefault(day_key, 0)
            if daily_counts[day_key] >= MAX_TRADES_PER_DAY:
                continue

            sig     = int(sig_arr[i])
            entry   = open_arr[i + 1]   # next bar's open — no look-ahead
            atr_val = atr_arr[i]
            if np.isnan(atr_val) or atr_val <= 0:
                continue

            sl_dist    = max(atr_val * atr_sl, pip_size * 10)
            risk_usd   = balance * RISK_PCT / 100.0
            reward_usd = risk_usd * rr

            if sig == 1:
                sl = entry - sl_dist
                tp = entry + sl_dist * rr
            else:
                sl = entry + sl_dist
                tp = entry - sl_dist * rr

            daily_counts[day_key] += 1

            open_trade = {
                "direction":  sig,
                "entry":      entry,
                "entry_time": times[i + 1],
                "entry_idx":  i,
                "sl":         sl,
                "tp":         tp,
                "sl_dist":    sl_dist,
                "risk_usd":   risk_usd,
                "reward_usd": reward_usd,
                "hour":       int(times[i].hour),
                "trail_on":   False,
            }

    return pd.DataFrame(trades) if trades else pd.DataFrame()


def metrics(trades: pd.DataFrame) -> dict:
    if trades.empty or len(trades) < 5:
        return {}
    wins  = trades[trades["pnl"] > 0]
    loss  = trades[trades["pnl"] <= 0]
    tp    = wins["pnl"].sum()
    tl    = loss["pnl"].abs().sum()
    net   = trades["pnl"].sum()
    wr    = len(wins) / len(trades) * 100
    pf    = tp / tl if tl > 0 else 99.0
    cum   = trades["pnl"].cumsum() + INITIAL_BALANCE
    peak  = cum.cummax()
    dd    = ((peak - cum) / peak * 100).max()
    return {
        "trades": len(trades), "wr": round(wr, 1), "pf": round(pf, 2),
        "net": round(net, 2), "dd": round(dd, 2),
        "final": round(INITIAL_BALANCE + net, 2),
    }


# ─────────────────────────────────────────────
# Grid search
# ─────────────────────────────────────────────

GRID = {
    "EMA_Fast":      [5, 7, 9],
    "EMA_Slow":      [15, 21, 30],
    "RSI_Period":    [5, 7, 9],
    "ATR_SL_Multi":  [0.8, 1.2, 1.6, 2.0],
    "RequiredScore": [4, 5],
    "RR":            [1.5, 2.0],
    "MaxTradeBars":  [0, 45],
}

SESSION_COMBOS = [
    [(10, 12), (21, 23)],   # tightest — best WR hours only
    [(10, 13), (20, 23)],   # slightly wider
    [(9,  13), (20, 23)],   # wider London + NY close
]


def run_optimizer():
    print(f"\n{'='*65}")
    print(f"  BTCUSD OPTIMIZER  |  {MONTHS} months  |  Spread-adjusted")
    print(f"{'='*65}")

    if not check_symbol(SYMBOL):
        print("BTCUSD not available"); return

    bars = MONTHS * 30 * 24 * 60
    print(f"Fetching {bars} M1 bars...")
    raw_df = fetch_ohlcv(SYMBOL, mt5.TIMEFRAME_M1, bars)
    if raw_df.empty:
        print("No data"); return

    pip = get_pip_size(SYMBOL)

    # Estimate average spread from bid/ask snapshots (use $15 as Exness BTC typical)
    spread_usd  = 15.0  # typical BTCUSD spread in price units
    # Spread cost per trade as fraction of risk: risk_usd * (spread / sl_dist)
    # We'll apply it directly in dollars — use fixed $0.25 per side (conservative)
    spread_cost_per_trade = 0.25

    print(f"Bars: {len(raw_df)} | Pip: {pip} | Spread cost/trade: ${spread_cost_per_trade}")

    keys   = list(GRID.keys())
    values = list(GRID.values())
    combos = list(itertools.product(*values))
    total  = len(combos) * len(SESSION_COMBOS)

    print(f"Testing {len(combos)} param combos × {len(SESSION_COMBOS)} session sets = {total} runs\n")

    results = []
    run_idx = 0

    for session_hours in SESSION_COMBOS:
        for combo in combos:
            run_idx += 1
            p = dict(zip(keys, combo))

            # Skip invalid EMA combos
            if p["EMA_Fast"] >= p["EMA_Slow"]:
                continue

            # Build full params for add_indicators
            full_p = {
                "EMA_Fast": p["EMA_Fast"], "EMA_Slow": p["EMA_Slow"],
                "RSI_Period": p["RSI_Period"], "RSI_OB": 70, "RSI_OS": 30,
                "ATR_Period": 14, "ATR_SL_Multi": p["ATR_SL_Multi"],
                "BB_Period": 20, "BB_Deviation": 2.0,
                "MACD_Fast": 8, "MACD_Slow": 17, "MACD_Signal": 9,
                "MomCandles": 2, "MinCandleBody": 0.25,
                "RequiredScore": p["RequiredScore"],
                "EMASlopePeriod": 5, "MaxTradeBars": p["MaxTradeBars"],
                "RR": p["RR"],
                # for add_indicators compat
                "InitialBalance": INITIAL_BALANCE,
                "RiskPct": RISK_PCT, "RiskPerTrade": 1.5,
                "RewardPerTrade": p["RR"] * 1.5,
                "MaxDrawdownPct": 20.0,
                "UseTrailingTP": False, "TrailTrigger": 1.0, "TrailStep": 0.5,
            }

            try:
                from config import SYMBOL_CONFIG
                SYMBOL_CONFIG["_atr_min"] = 5.0  # BTC needs at least 5 pip ATR

                df = add_indicators(raw_df, full_p)
                df = df.dropna()

                a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
                    df, full_p, pip, session_hours)
                sigs = signals_from_scores(
                    a_buy, a_sell, b_buy, b_sell, valid, p["RequiredScore"], df.index)

                trades = simulate_btc(df, sigs, full_p, pip, spread_cost_per_trade)
                m = metrics(trades)

                if not m or m["trades"] < 20:
                    continue

                score = m["pf"] if m["dd"] < 20.0 else 0.0

                if run_idx % 50 == 0:
                    print(f"  [{run_idx}/{total}] sess={session_hours} "
                          f"EMA={p['EMA_Fast']}/{p['EMA_Slow']} "
                          f"ATR={p['ATR_SL_Multi']} Score={p['RequiredScore']} "
                          f"RR={p['RR']} → "
                          f"PF={m['pf']} WR={m['wr']}% DD={m['dd']}% "
                          f"Net=${m['net']} Trades={m['trades']}")

                results.append({
                    "session": str(session_hours),
                    "params":  p,
                    "pf":      m["pf"], "wr": m["wr"], "dd": m["dd"],
                    "net":     m["net"], "trades": m["trades"],
                    "final":   m["final"], "score": score,
                })

            except Exception as e:
                continue

    if not results:
        print("No valid results."); return []

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:TOP_N]

    print(f"\n{'='*65}")
    print(f"  TOP {TOP_N} RESULTS — BTCUSD (spread-adjusted, next-bar entry)")
    print(f"{'='*65}")

    for rank, r in enumerate(top, 1):
        p = r["params"]
        print(f"\n  #{rank}  PF={r['pf']:.2f}  WR={r['wr']:.1f}%  "
              f"DD={r['dd']:.1f}%  Net=${r['net']:.2f}  "
              f"Trades={r['trades']}  Final=${r['final']:.2f}")
        print(f"       Sessions:    {r['session']}")
        print(f"       EMA:         {p['EMA_Fast']}/{p['EMA_Slow']}")
        print(f"       RSI_Period:  {p['RSI_Period']}")
        print(f"       ATR_SL_Multi:{p['ATR_SL_Multi']}")
        print(f"       RequiredScore:{p['RequiredScore']}")
        print(f"       RR:          {p['RR']}")
        print(f"       MaxTradeBars:{p['MaxTradeBars']}")

    best = top[0]
    bp   = best["params"]
    print(f"\n{'='*65}")
    print(f"  BEST PARAMS TO USE IN MT5 EA:")
    print(f"{'='*65}")
    print(f"  EMA_Fast      = {bp['EMA_Fast']}")
    print(f"  EMA_Slow      = {bp['EMA_Slow']}")
    print(f"  RSI_Period    = {bp['RSI_Period']}")
    print(f"  ATR_SL_Multi  = {bp['ATR_SL_Multi']}")
    print(f"  RequiredScore = {bp['RequiredScore']}")
    print(f"  RR            = {bp['RR']}")
    print(f"  Sessions      = {best['session']}")
    print(f"  MaxTradeBars  = {bp['MaxTradeBars']}")
    print(f"{'='*65}\n")

    return top


if __name__ == "__main__":
    if not connect():
        sys.exit(1)
    top = run_optimizer()
    disconnect()
    print("Optimizer complete.")
