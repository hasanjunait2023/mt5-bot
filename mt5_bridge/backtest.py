"""
Backtest engine — replicates ScalpMaster HFT strategy logic in Python.

Usage:
    python backtest.py --symbol EURUSD --months 3
    python backtest.py --symbol XAUUSD --months 6
    python backtest.py --symbol BTCUSD --months 1
"""

import argparse
import sys
from datetime import datetime, timedelta

import bridge_client as mt5  # HTTP-bridge shim — only TIMEFRAME_* used here; runs on Linux VPS too
import pandas as pd
import numpy as np

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import SYMBOL_CONFIG, DEFAULT_PARAMS


# ─────────────────────────────────────────────
# Indicator calculations
# ─────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def bollinger(series: pd.Series, period: int, std: float):
    mid   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def macd(series: pd.Series, fast: int, slow: int, signal: int):
    fast_ema   = series.ewm(span=fast,   adjust=False).mean()
    slow_ema   = series.ewm(span=slow,   adjust=False).mean()
    macd_line  = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def add_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"]   = ema(df["Close"], p["EMA_Fast"])
    df["ema_slow"]   = ema(df["Close"], p["EMA_Slow"])
    df["rsi"]        = rsi(df["Close"], p["RSI_Period"])
    df["atr"]        = atr(df,          p["ATR_Period"])
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger(
        df["Close"], p["BB_Period"], p["BB_Deviation"])
    df["macd"], df["macd_sig"] = macd(
        df["Close"], p["MACD_Fast"], p["MACD_Slow"], p["MACD_Signal"])
    df["body"]  = (df["Close"] - df["Open"]).abs()
    df["range"] = df["High"] - df["Low"]
    # EMA momentum slope: change in fast EMA over N bars, normalized by ATR
    slope_n = p.get("EMASlopePeriod", 5)
    df["ema_slope"] = (df["ema_fast"] - df["ema_fast"].shift(slope_n)) / df["atr"].replace(0, np.nan)
    # Volatility rank: current ATR vs rolling 50-bar ATR (1=high vol, 0=low vol)
    df["vol_rank"] = df["atr"].rank(pct=True, method="average").rolling(50).mean()
    return df


# ─────────────────────────────────────────────
# Signal generation (mirrors MQL5 logic)
# ─────────────────────────────────────────────

def is_valid_session(hour: int, session_hours: list) -> bool:
    for start, end in session_hours:
        if start <= end:
            if start <= hour < end:
                return True
        else:
            if hour >= start or hour < end:
                return True
    return False


def compute_score_arrays(df: pd.DataFrame, p: dict, pip_size: float,
                          session_hours: list = None):
    """Vectorized: compute per-bar a_buy/a_sell/b_buy/b_sell score arrays + valid mask.
    Returns (a_buy, a_sell, b_buy, b_sell, valid) as numpy int arrays."""
    min_atr_pips = SYMBOL_CONFIG.get("_atr_min", 1.0)
    mc  = p["MomCandles"]
    mcb = p["MinCandleBody"]

    close = df["Close"].values
    high  = df["High"].values
    low   = df["Low"].values
    open_ = df["Open"].values

    ef   = df["ema_fast"].values
    es   = df["ema_slow"].values
    rsi  = df["rsi"].values
    atr  = df["atr"].values
    macd = df["macd"].values
    msig = df["macd_sig"].values
    bbu  = df["bb_upper"].values
    bbl  = df["bb_lower"].values

    rsi_ob = p["RSI_OB"]
    rsi_os = p["RSI_OS"]

    # EMA
    ef_p = np.roll(ef, 1);  es_p = np.roll(es, 1)
    ema_bull  = (ef > es) & (ef_p <= es_p)
    ema_bear  = (ef < es) & (ef_p >= es_p)
    ema_above = ef > es
    ema_below = ef < es

    # RSI
    rsi_buy       = (rsi > rsi_os) & (rsi < 45)
    rsi_sell      = (rsi > 55)     & (rsi < rsi_ob)
    rsi_oversold  = rsi <= rsi_os
    rsi_overbought = rsi >= rsi_ob

    # BB (prev bar low/high)
    low_p  = np.roll(low,  1)
    high_p = np.roll(high, 1)
    bbl_p  = np.roll(bbl,  1)
    bbu_p  = np.roll(bbu,  1)
    bb_up   = (close <= bbl) | (low_p  <= bbl_p)
    bb_down = (close >= bbu) | (high_p >= bbu_p)

    # MACD
    macd_p = np.roll(macd, 1); msig_p = np.roll(msig, 1)
    macd_bull_x = (macd > msig) & (macd_p <= msig_p)
    macd_bear_x = (macd < msig) & (macd_p >= msig_p)
    macd_bull   = macd > msig
    macd_bear   = macd < msig

    # Momentum: mc consecutive candles all bull/bear with body ratio >= mcb
    candle_bull  = (close > open_).astype(np.int8)
    candle_bear  = (close < open_).astype(np.int8)
    rng          = np.where(high - low > 0, high - low, np.nan)
    body_ok      = ((np.abs(close - open_) / rng) >= mcb).astype(np.int8)
    bull_ok_bar  = candle_bull * body_ok
    bear_ok_bar  = candle_bear * body_ok

    # Convolve with ones to sum over mc bars
    kernel = np.ones(mc, dtype=np.int8)
    bull_mom = np.convolve(bull_ok_bar, kernel, mode="full")[:len(close)] == mc
    bear_mom = np.convolve(bear_ok_bar, kernel, mode="full")[:len(close)] == mc
    # Shift so the window is the mc bars ending at current bar
    bull_mom = np.roll(bull_mom, 0)
    bear_mom = np.roll(bear_mom, 0)

    # ATR gate
    atr_ok = (~np.isnan(atr)) & (atr / pip_size >= min_atr_pips)

    # Session filter
    if session_hours:
        hours = np.array([t.hour for t in df.index])
        sess_ok = np.zeros(len(df), dtype=bool)
        for start, end in session_hours:
            if start <= end:
                sess_ok |= (hours >= start) & (hours < end)
            else:
                sess_ok |= (hours >= start) | (hours < end)
    else:
        sess_ok = np.ones(len(df), dtype=bool)

    valid = atr_ok & sess_ok

    # Strategy A scores (0-5)
    a_buy = (
        (ema_bull | ema_above).astype(int)
        + (rsi_buy | rsi_oversold).astype(int)
        + (macd_bull_x | macd_bull).astype(int)
        + bull_mom.astype(int)
        + (close > es).astype(int)
    )
    a_sell = (
        (ema_bear | ema_below).astype(int)
        + (rsi_sell | rsi_overbought).astype(int)
        + (macd_bear_x | macd_bear).astype(int)
        + bear_mom.astype(int)
        + (close < es).astype(int)
    )

    # Strategy B scores (0-5)
    b_buy  = ((bb_up   & rsi_oversold ).astype(int) * 3
              + macd_bull_x.astype(int)
              + (close > open_).astype(int))
    b_sell = ((bb_down & rsi_overbought).astype(int) * 3
              + macd_bear_x.astype(int)
              + (close < open_).astype(int))

    return a_buy, a_sell, b_buy, b_sell, valid


def signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid, req, index):
    """Apply score threshold to get signal Series. O(n) numpy."""
    sig = np.zeros(len(index), dtype=np.int8)
    sig = np.where(valid & (a_buy  >= req), np.int8(1),  sig)
    sig = np.where(valid & (sig == 0) & (a_sell >= req), np.int8(-1), sig)
    sig = np.where(valid & (sig == 0) & (b_buy  >= req), np.int8(1),  sig)
    sig = np.where(valid & (sig == 0) & (b_sell >= req), np.int8(-1), sig)
    return pd.Series(sig, index=index)


def compute_signals(df: pd.DataFrame, p: dict, pip_size: float,
                    session_hours: list = None) -> pd.Series:
    """Return Series of signals: 1=BUY, -1=SELL, 0=no trade. Vectorized."""
    a_buy, a_sell, b_buy, b_sell, valid = compute_score_arrays(
        df, p, pip_size, session_hours)
    return signals_from_scores(a_buy, a_sell, b_buy, b_sell, valid,
                                p["RequiredScore"], df.index)


# ─────────────────────────────────────────────
# Trade simulation
# ─────────────────────────────────────────────

def simulate_trades(df: pd.DataFrame, signals: pd.Series, p: dict, pip_size: float) -> pd.DataFrame:
    """Simulate trades — numpy array access for 10x faster inner loop."""
    balance    = p["InitialBalance"]
    initial    = balance
    max_dd_pct = p["MaxDrawdownPct"] / 100.0
    rr         = p["RewardPerTrade"] / p["RiskPerTrade"]
    risk_pct   = p.get("RiskPct", 0.0)
    use_trail  = p.get("UseTrailingTP", False)
    trail_trigger = p.get("TrailTrigger", 1.0)
    trail_step    = p.get("TrailStep", 0.5)
    max_bars      = p.get("MaxTradeBars", 0)
    atr_sl        = p["ATR_SL_Multi"]

    # Pull numpy arrays upfront to avoid pandas .iloc overhead in the loop
    high_arr  = df["High"].values
    low_arr   = df["Low"].values
    close_arr = df["Close"].values
    atr_arr   = df["atr"].values
    sig_arr   = signals.values
    times     = df.index
    hours     = times.hour

    trades     = []
    open_trade = None

    for i in range(1, len(high_arr)):
        high  = high_arr[i]
        low   = low_arr[i]
        close = close_arr[i]

        if (initial - balance) / initial >= max_dd_pct:
            break

        # ── Manage open trade ──
        if open_trade is not None:
            direction  = open_trade["direction"]
            entry      = open_trade["entry"]
            sl_dist    = open_trade["sl_dist"]
            risk_usd   = open_trade["risk_usd"]
            reward_usd = open_trade["reward_usd"]
            sl         = open_trade["sl"]
            tp         = open_trade["tp"]
            trail_on   = open_trade["trail_on"]

            # Force-close timeout
            if max_bars > 0 and (i - open_trade["entry_idx"]) >= max_bars:
                pnl = risk_usd * (close - entry) / sl_dist if direction == 1 \
                      else risk_usd * (entry - close) / sl_dist
                balance += pnl
                trades.append({**open_trade, "exit": close, "exit_time": times[i],
                               "result": "TO", "pnl": round(pnl, 4), "balance": round(balance, 4)})
                open_trade = None

            elif direction == 1:
                if low <= sl:
                    pnl = risk_usd * (sl - entry) / sl_dist
                    balance += pnl
                    trades.append({**open_trade, "exit": sl, "exit_time": times[i],
                                   "result": "TSL" if pnl >= 0 else "SL",
                                   "pnl": round(pnl, 4), "balance": round(balance, 4)})
                    open_trade = None
                else:
                    if use_trail:
                        if not trail_on and close >= entry + sl_dist * trail_trigger:
                            open_trade["trail_on"] = True
                            trail_on = True
                            if open_trade["sl"] < entry:
                                open_trade["sl"] = entry
                        if trail_on:
                            new_sl = close - sl_dist * trail_step
                            if new_sl > open_trade["sl"]:
                                open_trade["sl"] = new_sl
                    if not trail_on and high >= tp:
                        balance += reward_usd
                        trades.append({**open_trade, "exit": tp, "exit_time": times[i],
                                       "result": "TP", "pnl": reward_usd, "balance": round(balance, 4)})
                        open_trade = None

            else:  # SELL
                if high >= sl:
                    pnl = risk_usd * (entry - sl) / sl_dist
                    balance += pnl
                    trades.append({**open_trade, "exit": sl, "exit_time": times[i],
                                   "result": "TSL" if pnl >= 0 else "SL",
                                   "pnl": round(pnl, 4), "balance": round(balance, 4)})
                    open_trade = None
                else:
                    if use_trail:
                        if not trail_on and close <= entry - sl_dist * trail_trigger:
                            open_trade["trail_on"] = True
                            trail_on = True
                            if open_trade["sl"] > entry:
                                open_trade["sl"] = entry
                        if trail_on:
                            new_sl = close + sl_dist * trail_step
                            if new_sl < open_trade["sl"]:
                                open_trade["sl"] = new_sl
                    if not trail_on and low <= tp:
                        balance += reward_usd
                        trades.append({**open_trade, "exit": tp, "exit_time": times[i],
                                       "result": "TP", "pnl": reward_usd, "balance": round(balance, 4)})
                        open_trade = None

        # ── New trade entry ──
        if open_trade is None and sig_arr[i] != 0:
            sig     = int(sig_arr[i])
            entry   = close
            atr_val = atr_arr[i]
            if np.isnan(atr_val) or atr_val <= 0:
                continue

            sl_dist    = max(atr_val * atr_sl, pip_size)
            risk_usd   = (balance * risk_pct / 100.0) if risk_pct > 0 else p["RiskPerTrade"]
            reward_usd = risk_usd * rr

            if sig == 1:
                sl = entry - sl_dist
                tp = entry + sl_dist * rr
            else:
                sl = entry + sl_dist
                tp = entry - sl_dist * rr

            open_trade = {
                "direction":  sig,
                "entry":      entry,
                "entry_time": times[i],
                "entry_idx":  i,
                "sl":         sl,
                "tp":         tp,
                "sl_dist":    sl_dist,
                "risk_usd":   risk_usd,
                "reward_usd": reward_usd,
                "sl_pips":    sl_dist / pip_size,
                "hour":       int(hours[i]),
                "trail_on":   False,
            }

    return pd.DataFrame(trades) if trades else pd.DataFrame()


# ─────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────

def compute_metrics(trades: pd.DataFrame, initial_balance: float) -> dict:
    if trades.empty:
        return {"error": "No trades generated"}

    wins   = trades[trades["pnl"] > 0]    # TP + TSL with profit
    losses = trades[trades["pnl"] <= 0]  # SL only

    total_profit = wins["pnl"].sum()
    total_loss   = losses["pnl"].abs().sum()
    net_pnl      = trades["pnl"].sum()

    win_rate     = len(wins) / len(trades) * 100
    profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

    # Max drawdown
    cumulative = trades["pnl"].cumsum() + initial_balance
    peak       = cumulative.cummax()
    drawdown   = (peak - cumulative) / peak * 100
    max_dd     = drawdown.max()

    # Sharpe (simplified daily)
    if len(trades) > 1:
        daily = trades.groupby(trades["entry_time"].dt.date)["pnl"].sum()
        sharpe = (daily.mean() / daily.std() * (252 ** 0.5)) if daily.std() > 0 else 0
    else:
        sharpe = 0

    # Session breakdown
    session_stats = {}
    for hour, grp in trades.groupby("hour"):
        w = (grp["pnl"] > 0).sum()   # counts TP, TSL, and TO wins
        session_stats[hour] = {"trades": len(grp), "wins": w,
                                "wr": w / len(grp) * 100}

    return {
        "total_trades":   len(trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate_pct":   round(win_rate, 1),
        "profit_factor":  round(profit_factor, 2),
        "net_pnl":        round(net_pnl, 2),
        "total_profit":   round(total_profit, 2),
        "total_loss":     round(total_loss, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio":   round(sharpe, 2),
        "final_balance":  round(initial_balance + net_pnl, 2),
        "session_stats":  session_stats,
    }


# ─────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────

def run_with_data(raw_df: pd.DataFrame, symbol: str, params: dict, pip: float) -> dict:
    """Run backtest on pre-fetched raw DataFrame (no MT5 call). Used by optimizer."""
    sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
    SYMBOL_CONFIG["_atr_min"] = sym_cfg["atr_min_pips"]

    df = add_indicators(raw_df, params)
    df = df.dropna()

    session_hours = sym_cfg.get("session_hours")
    signals = compute_signals(df, params, pip, session_hours=session_hours)
    trades  = simulate_trades(df, signals, params, pip)
    metrics = compute_metrics(trades, params["InitialBalance"])
    return {"symbol": symbol, "params": params, "metrics": metrics, "trades": trades}


def run(symbol: str, months: int, params: dict = None) -> dict:
    if params is None:
        params = DEFAULT_PARAMS.copy()

    sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])

    # Inject symbol-specific ATR min into a reachable spot
    SYMBOL_CONFIG["_atr_min"] = sym_cfg["atr_min_pips"]

    bars = months * 30 * 24 * 60   # approximate M1 bars

    print(f"\nFetching {bars} M1 bars for {symbol}...")
    if not check_symbol(symbol):
        return {"error": f"Symbol {symbol} not available"}

    df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
    if df.empty:
        return {"error": "No data fetched"}

    print(f"Got {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    pip = get_pip_size(symbol)
    print(f"Pip size: {pip} | Computing indicators...")

    df = add_indicators(df, params)
    df.dropna(inplace=True)

    print("Generating signals...")
    session_hours = sym_cfg.get("session_hours")
    signals = compute_signals(df, params, pip, session_hours=session_hours)

    sig_count = (signals != 0).sum()
    print(f"Total signals (after session filter): {sig_count}")

    print("Simulating trades...")
    trades = simulate_trades(df, signals, params, pip)

    metrics = compute_metrics(trades, params["InitialBalance"])
    return {"symbol": symbol, "months": months, "params": params,
            "metrics": metrics, "trades": trades}


def print_results(result: dict):
    m = result.get("metrics", {})
    if "error" in m:
        print(f"ERROR: {m['error']}")
        return

    print("\n" + "=" * 55)
    print(f"  BACKTEST RESULTS — {result['symbol']} ({result['months']} months)")
    print("=" * 55)
    print(f"  Total Trades:    {m['total_trades']}")
    print(f"  Wins / Losses:   {m['wins']} / {m['losses']}")
    print(f"  Win Rate:        {m['win_rate_pct']}%")
    print(f"  Profit Factor:   {m['profit_factor']}")
    print(f"  Net P&L:         ${m['net_pnl']}")
    print(f"  Total Profit:    ${m['total_profit']}")
    print(f"  Total Loss:      ${m['total_loss']}")
    print(f"  Max Drawdown:    {m['max_drawdown_pct']}%")
    print(f"  Sharpe Ratio:    {m['sharpe_ratio']}")
    print(f"  Final Balance:   ${m['final_balance']}")
    print("=" * 55)

    # Session breakdown
    ss = m.get("session_stats", {})
    if ss:
        print("\n  Hour-by-hour win rates (server time):")
        for h in sorted(ss.keys()):
            d = ss[h]
            bar = "#" * int(d["wr"] / 5)
            print(f"    {h:02d}:00  {d['trades']:4d} trades  WR {d['wr']:5.1f}%  {bar}")


def main():
    parser = argparse.ArgumentParser(description="ScalpMaster HFT Backtest")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to backtest")
    parser.add_argument("--months", type=int, default=3, help="Months of M1 history")
    args = parser.parse_args()

    if not connect():
        sys.exit(1)

    result = run(args.symbol.upper(), args.months)
    print_results(result)

    disconnect()


if __name__ == "__main__":
    main()
