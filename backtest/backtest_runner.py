"""
FxVault — Full Backtest Runner
================================
Runs all 6 strategies against 2 years of MT5 historical data.
Generates HTML report for each strategy + combined portfolio report.

Usage:
    python backtest_runner.py

Reports saved to: backtest_reports/
"""

import os, sys, math, json
from datetime import datetime, timezone, date, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

# CPP strategy + hybrid confirmation agent live under ../trading_agents/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "trading_agents"))
from strategies import confluence_pullback as cpp          # noqa: E402
from trade_confirmation_agent import TradeConfirmationAgent  # noqa: E402

# ── config ─────────────────────────────────────────────────────────
REPORT_DIR   = os.path.join(os.path.dirname(__file__), "backtest_reports")
INIT_BALANCE = 1000.0

# ── realistic trading-cost model ───────────────────────────────────
# The raw backtests fill at mid price with no costs. Live XAUUSD on this
# broker (Exness-MT5Trial14) showed ~21.6-pip spread (216 points,
# point=0.001, pip=0.01). Spread is paid once per round-trip; commission
# is 0 on the standard/trial account (raw accounts ~ $7/lot RT — tune via
# COMMISSION_PER_LOT_RT). We deduct this per trade so PF / WR / net
# reflect REAL profitability — the only honest basis for "is it profitable".
APPLY_COSTS          = True
S6_RISK_PCT          = 1.5      # locked: post-cost +47% / PF 1.44 / DD 7.7% (sweep 2026-05-19)
# S6 range-validity bounds. Default = gold-$ scale (preserves locked XAU
# result). When S6_ATR_BOUNDS=True the bounds become multiples of the
# symbol's own H4-ATR so the SAME edge generalises to ANY instrument
# (the honest multi-symbol high-return lever — no curve-fit).
S6_ATR_BOUNDS        = False
S6_RMIN_ATR          = 0.5      # min Asian range  = 0.5  × H4-ATR
S6_RMAX_ATR          = 4.0      # max Asian range  = 4.0  × H4-ATR
S6_CMAX_ATR          = 1.5      # max single candle = 1.5 × H4-ATR
S6_BUF_ATR           = 0.10     # SL buffer beyond range = 0.10 × H4-ATR
SPREAD_PIPS          = 21.0     # XAUUSD live-observed round-trip spread
COMMISSION_PER_LOT_RT = 0.0     # USD per 1.0 lot round-trip (0 = standard)
# XAUUSD: pip=0.01, tick_size=0.001, tick_value=0.10  → $/lot per pip = 10
_XAU_USD_PER_PIP_PER_LOT = 0.01 / 0.001 * 0.10          # = 1.0
COST_PER_LOT_USD = SPREAD_PIPS * _XAU_USD_PER_PIP_PER_LOT + COMMISSION_PER_LOT_RT


_COST_CACHE: dict = {}

def trade_cost(lots: float, symbol: str = "XAUUSD") -> float:
    """Realistic round-trip cost (spread+commission) for `lots` of `symbol`.
    Uses the broker's live spread + tick economics per symbol so multi-symbol
    backtests are costed honestly (XAUUSD's $21/lot is NOT EURUSD's ~$1/lot).
    Falls back to the XAUUSD constant if MT5/symbol info is unavailable."""
    if not APPLY_COSTS:
        return 0.0
    lots = max(lots, 0.0)
    if symbol == "XAUUSD":
        return COST_PER_LOT_USD * lots
    if symbol not in _COST_CACHE:
        per_lot = COST_PER_LOT_USD                       # safe fallback
        try:
            info = mt5.symbol_info(symbol)
            if info and info.trade_tick_size > 0:
                spread_price = info.spread * info.point   # current spread
                per_lot = (spread_price / info.trade_tick_size
                           * info.trade_tick_value) + COMMISSION_PER_LOT_RT
        except Exception:
            pass
        _COST_CACHE[symbol] = per_lot
    return _COST_CACHE[symbol] * lots
FROM_DATE    = datetime(2024, 1, 1, tzinfo=timezone.utc)
TO_DATE      = datetime(2026, 5, 17, tzinfo=timezone.utc)
os.makedirs(REPORT_DIR, exist_ok=True)

# ── helpers ─────────────────────────────────────────────────────────
def ema_series(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def rsi_series(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0)
    l = (-d).clip(lower=0)
    ag = g.ewm(com=n-1, adjust=False).mean()
    al = l.ewm(com=n-1, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def atr_series(df: pd.DataFrame, n: int) -> pd.Series:
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift()).abs()
    lcp = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def macd_hist(s: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    line   = ema_series(s, fast) - ema_series(s, slow)
    signal = ema_series(line, sig)
    return line - signal

def asof_pos(index, ts, min_count: int = 1, strict: bool = False):
    """Binary-search the integer position of the last index entry
    <= ts (or < ts when strict). Returns None if fewer than
    min_count entries precede/equal it. O(log n) vs the old
    O(n) `index[index <= ts][-1]` full-scan pattern.
    Assumes index is sorted ascending (true for OHLC time series).
    """
    side = "left" if strict else "right"
    pos  = index.searchsorted(ts, side=side) - 1
    if pos < 0 or pos + 1 < min_count:
        return None
    return pos

def pip_size(symbol: str) -> float:
    info = mt5.symbol_info(symbol)
    return info.point * 10 if info else 0.1

def calc_lot(balance: float, risk_pct: float, sl_pips: float, pip: float, symbol: str) -> float:
    info     = mt5.symbol_info(symbol)
    if not info: return 0.01
    risk_usd  = balance * risk_pct / 100
    tick_val  = info.trade_tick_value
    tick_sz   = info.trade_tick_size
    if tick_sz <= 0: return info.volume_min
    sl_price  = sl_pips * pip
    raw       = risk_usd / (sl_price / tick_sz * tick_val)
    step      = info.volume_step
    lot       = max(info.volume_min, min(info.volume_max, math.floor(raw / step) * step))
    return round(lot, 2)

def get_rates(symbol: str, tf, days_back: int = 730) -> pd.DataFrame:
    print(f"  Downloading {symbol} {tf_name(tf)} ({days_back} days)...")

    # For M1/M5, download in quarterly chunks to avoid MT5 bar limits
    if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5):
        frames = []
        start = datetime.now(timezone.utc) - timedelta(days=days_back + 10)
        end   = datetime.now(timezone.utc)
        chunk = timedelta(days=90)
        cur   = start
        while cur < end:
            nxt  = min(cur + chunk, end)
            b    = mt5.copy_rates_range(symbol, tf, cur, nxt)
            if b is not None and len(b) > 0:
                frames.append(pd.DataFrame(b))
            cur = nxt
        if not frames:
            # fallback: copy from position (last N bars)
            max_bars = 500000 if tf == mt5.TIMEFRAME_M1 else 200000
            b = mt5.copy_rates_from_pos(symbol, tf, 0, max_bars)
            if b is not None and len(b) > 0:
                frames.append(pd.DataFrame(b))
        if not frames:
            print(f"  WARNING: No data for {symbol} {tf_name(tf)}")
            return pd.DataFrame(columns=["open","high","low","close","tick_volume"])
        df = pd.concat(frames).drop_duplicates()
    else:
        bars = mt5.copy_rates_range(
            symbol, tf,
            datetime.now(timezone.utc) - timedelta(days=days_back + 10),
            datetime.now(timezone.utc)
        )
        if bars is None or len(bars) == 0:
            print(f"  WARNING: No data for {symbol} {tf_name(tf)}")
            return pd.DataFrame(columns=["open","high","low","close","tick_volume"])
        df = pd.DataFrame(bars)

    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    df.sort_index(inplace=True)
    df = df[df.index >= FROM_DATE]
    df = df[df.index <= TO_DATE]
    print(f"    Got {len(df):,} bars")
    return df

def tf_name(tf) -> str:
    names = {mt5.TIMEFRAME_M1:"M1", mt5.TIMEFRAME_M5:"M5",
             mt5.TIMEFRAME_M15:"M15", mt5.TIMEFRAME_H1:"H1",
             mt5.TIMEFRAME_H4:"H4"}
    return names.get(tf, str(tf))


# ── trade record ─────────────────────────────────────────────────────
@dataclass
class Trade:
    entry_time:  datetime
    exit_time:   datetime
    direction:   str
    entry_price: float
    exit_price:  float
    lots:        float
    pnl_pips:    float
    pnl_usd:     float
    exit_reason: str
    strategy:    str


# ── statistics ────────────────────────────────────────────────────────
def compute_stats(trades: List[Trade], init_bal: float,
                  symbol: str = "XAUUSD") -> dict:
    if not trades:
        return {"error": "no trades"}
    # Deduct realistic spread+commission per trade so every metric below
    # (net, PF, win-rate, drawdown) reflects REAL profitability, not the
    # cost-free idealisation. This is the honest basis for go-live.
    pnls    = [t.pnl_usd - trade_cost(t.lots, symbol) for t in trades]
    wins    = [p for p in pnls if p > 0]
    losses  = [p for p in pnls if p <= 0]
    eq      = [init_bal]
    for p in pnls:
        eq.append(eq[-1] + p)
    eq_arr  = np.array(eq)
    peak    = np.maximum.accumulate(eq_arr)
    dd_arr  = (peak - eq_arr) / peak * 100
    max_dd  = float(dd_arr.max())

    gross_p = sum(wins)
    gross_l = abs(sum(losses))
    pf      = gross_p / gross_l if gross_l > 0 else float("inf")

    return {
        "total_trades":  len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      len(wins) / len(trades) * 100,
        "net_profit":    sum(pnls),
        "net_profit_pct":(eq[-1] - init_bal) / init_bal * 100,
        "gross_profit":  gross_p,
        "gross_loss":    gross_l,
        "profit_factor": pf,
        "max_drawdown":  max_dd,
        "avg_win":       np.mean(wins) if wins else 0,
        "avg_loss":      np.mean(losses) if losses else 0,
        "final_balance": eq[-1],
        "equity_curve":  eq,
    }


# ── HTML report builder ───────────────────────────────────────────────
def build_html(name: str, stats: dict, trades: List[Trade]) -> str:
    if "error" in stats:
        return f"<h1>{name}</h1><p>No trades generated.</p>"

    # monthly P&L
    monthly: Dict[str, float] = {}
    for t in trades:
        k = t.exit_time.strftime("%Y-%m")
        monthly[k] = monthly.get(k, 0) + t.pnl_usd

    eq   = stats["equity_curve"]
    pnl  = stats["net_profit"]
    sign = "+" if pnl >= 0 else ""
    color = "#00c853" if pnl >= 0 else "#d50000"

    rows = ""
    for t in trades[-200:]:  # last 200 trades
        c = "#e8f5e9" if t.pnl_usd > 0 else "#ffebee"
        pnl_color = "green" if t.pnl_usd > 0 else "red"
        rows += (
            f"<tr style='background:{c}'>"
            f"<td>{t.entry_time.strftime('%Y-%m-%d %H:%M')}</td>"
            f"<td>{t.direction}</td>"
            f"<td>{t.entry_price:.4f}</td>"
            f"<td>{t.exit_price:.4f}</td>"
            f"<td>{t.lots}</td>"
            f"<td>{t.pnl_pips:+.1f}</td>"
            f"<td style='color:{pnl_color}'>${t.pnl_usd:+.2f}</td>"
            f"<td>{t.exit_reason}</td></tr>\n"
        )

    mo_rows = ""
    for k in sorted(monthly):
        v = monthly[k]; c = "green" if v >= 0 else "red"
        mo_rows += f"<tr><td>{k}</td><td style='color:{c}'>${v:+.2f}</td></tr>\n"

    # mini equity sparkline
    step  = max(1, len(eq) // 200)
    pts   = eq[::step]
    mn, mx = min(pts), max(pts)
    rng   = mx - mn if mx != mn else 1
    h, w  = 120, 600
    xs = [int(i/(len(pts)-1)*w) for i in range(len(pts))]
    ys = [int(h - (p - mn)/rng*h) for p in pts]
    polyline = " ".join(f"{x},{y}" for x, y in zip(xs, ys))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{name} Backtest Report</title>
<style>
  body{{font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px}}
  h1{{color:#1a237e}} h2{{color:#283593;border-bottom:2px solid #3949ab;padding-bottom:6px}}
  .card{{background:#fff;border-radius:8px;padding:20px;margin:16px 0;box-shadow:0 2px 6px rgba(0,0,0,.1)}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}}
  .stat{{background:#e8eaf6;border-radius:6px;padding:14px;text-align:center}}
  .stat .val{{font-size:1.6em;font-weight:bold;color:#1a237e}}
  .stat .lbl{{font-size:.8em;color:#555;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;font-size:.85em}}
  th{{background:#3949ab;color:#fff;padding:8px;text-align:left}}
  td{{padding:6px 8px;border-bottom:1px solid #eee}}
  tr:hover{{background:#f0f4ff}}
</style></head><body>
<h1>{name} — Backtest Report</h1>
<p style="color:#555">Period: {FROM_DATE.strftime('%Y-%m-%d')} to {TO_DATE.strftime('%Y-%m-%d')} &nbsp;|&nbsp;
   Initial Balance: $1,000.00 &nbsp;|&nbsp;
   Final Balance: <b>${stats['final_balance']:.2f}</b></p>

<div class="card">
  <h2>Equity Curve</h2>
  <svg width="{w}" height="{h}" style="background:#fff;border:1px solid #ddd;border-radius:4px">
    <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2"/>
  </svg>
</div>

<div class="card">
  <h2>Summary</h2>
  <div class="grid">
    <div class="stat"><div class="val" style="color:{color}">{sign}{stats['net_profit']:.2f}</div><div class="lbl">Net Profit ($)</div></div>
    <div class="stat"><div class="val" style="color:{color}">{sign}{stats['net_profit_pct']:.1f}%</div><div class="lbl">Return</div></div>
    <div class="stat"><div class="val">{stats['win_rate']:.1f}%</div><div class="lbl">Win Rate</div></div>
    <div class="stat"><div class="val">{stats['profit_factor']:.2f}</div><div class="lbl">Profit Factor</div></div>
    <div class="stat"><div class="val" style="color:red">{stats['max_drawdown']:.1f}%</div><div class="lbl">Max Drawdown</div></div>
    <div class="stat"><div class="val">{stats['total_trades']}</div><div class="lbl">Total Trades</div></div>
    <div class="stat"><div class="val" style="color:green">{stats['wins']}</div><div class="lbl">Wins</div></div>
    <div class="stat"><div class="val" style="color:red">{stats['losses']}</div><div class="lbl">Losses</div></div>
    <div class="stat"><div class="val" style="color:green">${stats['avg_win']:.2f}</div><div class="lbl">Avg Win</div></div>
    <div class="stat"><div class="val" style="color:red">${stats['avg_loss']:.2f}</div><div class="lbl">Avg Loss</div></div>
  </div>
</div>

<div class="card">
  <h2>Monthly P&amp;L</h2>
  <table><tr><th>Month</th><th>P&amp;L ($)</th></tr>
  {mo_rows}
  </table>
</div>

<div class="card">
  <h2>Trade Log (last 200)</h2>
  <table>
    <tr><th>Entry Time</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Lots</th><th>Pips</th><th>P&amp;L</th><th>Exit Reason</th></tr>
    {rows}
  </table>
</div>
</body></html>"""


# ══════════════════════════════════════════════════════════════════════
# STRATEGY BACKTESTERS
# ══════════════════════════════════════════════════════════════════════

def backtest_s3(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S3 — M1 HFT Sniper"""
    print("  Running S3 backtest...")
    pip  = pip_size(symbol)
    m1   = data["m1"]
    m5   = data["m5"]
    h1   = data["h1"]
    if m1.empty or m5.empty or h1.empty or "close" not in m1.columns:
        print("  SKIP S3 — insufficient M1/M5 data"); return []
    m1 = m1.copy(); m5 = m5.copy(); h1 = h1.copy()

    # precompute indicators
    h1["ema200"] = ema_series(h1["close"], 200)
    m5["ema5"]   = ema_series(m5["close"], 5)
    m5["ema13"]  = ema_series(m5["close"], 13)
    m1["ema5"]   = ema_series(m1["close"], 5)
    m1["ema13"]  = ema_series(m1["close"], 13)
    m1["rsi7"]   = rsi_series(m1["close"], 7)
    m1["atr14"]  = atr_series(m1, 14)

    trades, balance = [], INIT_BALANCE
    SL, TP1, TP2, BE = 7, 10, 15, 4
    MAX_DD_PCT = 20.0
    open_trade = None
    daily_start = balance; last_day = None

    for ts, row in m1.iloc[210:].iterrows():
        cur_day = ts.date()
        if cur_day != last_day:
            daily_start = balance; last_day = cur_day

        if balance < INIT_BALANCE * (1 - MAX_DD_PCT/100): break

        h = ts.hour
        in_sess = 7 <= h < 17

        # manage open trade
        if open_trade:
            p = open_trade
            pnl_pips = (row["close"] - p["entry"]) / pip if p["dir"] == "BUY" \
                       else (p["entry"] - row["close"]) / pip

            # BE
            if not p["be"] and pnl_pips >= BE:
                p["sl_pips"] = -BE
                p["be"] = True

            # TP1 partial at +10
            if not p["tp1"] and pnl_pips >= TP1:
                partial_pnl = (TP1 * pip * p["lot"] * 0.6 *
                               mt5.symbol_info(symbol).trade_contract_size)
                balance += partial_pnl * (1 if p["dir"]=="BUY" else 1)
                p["lot"] = round(p["lot"] * 0.4, 2)
                p["tp1"] = True

            # SL hit
            sl_price = (p["entry"] - p["sl_pips"] * pip) if p["dir"] == "BUY" \
                       else (p["entry"] + p["sl_pips"] * pip)
            hit_sl = (p["dir"]=="BUY"  and row["low"]  <= sl_price) or \
                     (p["dir"]=="SELL" and row["high"] >= sl_price)

            # TP2 hit
            tp2_price = (p["entry"] + TP2*pip) if p["dir"]=="BUY" else (p["entry"] - TP2*pip)
            hit_tp2 = (p["dir"]=="BUY"  and row["high"] >= tp2_price) or \
                      (p["dir"]=="SELL" and row["low"]  <= tp2_price)

            # time exit
            elapsed = (ts - p["entry_time"]).total_seconds() / 60

            exit_price, exit_reason = None, None
            if hit_sl:
                exit_price  = sl_price
                exit_reason = "SL"
            elif hit_tp2:
                exit_price  = tp2_price
                exit_reason = "TP2"
            elif elapsed >= 15 or not in_sess:
                exit_price  = row["close"]
                exit_reason = "TimeExit" if elapsed >= 15 else "SessionEnd"

            if exit_price is not None:
                final_pips = (exit_price - p["entry"]) / pip if p["dir"] == "BUY" \
                             else (p["entry"] - exit_price) / pip
                info = mt5.symbol_info(symbol)
                pnl_usd = final_pips * pip / info.trade_tick_size * info.trade_tick_value * p["lot"]
                balance += pnl_usd

                # account for earlier TP1 partial
                if p["tp1"]:
                    tp1_pips = TP1
                    tp1_lot  = p["lot"] / 0.4 * 0.6
                    tp1_pnl  = tp1_pips * pip / info.trade_tick_size * info.trade_tick_value * tp1_lot
                    total_pnl = pnl_usd + tp1_pnl
                    trades.append(Trade(p["entry_time"], ts, p["dir"],
                                        p["entry"], exit_price, p["lot"]/0.4*1.0,
                                        final_pips, total_pnl, exit_reason, "S3"))
                else:
                    trades.append(Trade(p["entry_time"], ts, p["dir"],
                                        p["entry"], exit_price, p["lot"],
                                        final_pips, pnl_usd, exit_reason, "S3"))
                open_trade = None
            continue

        if not in_sess: continue

        # signal check
        h1p = asof_pos(h1.index, ts, 201)
        m5p = asof_pos(m5.index, ts, 14)
        if h1p is None or m5p is None: continue

        h1_row  = h1.iloc[h1p]
        m5_row  = m5.iloc[m5p]
        m5_prev = m5.iloc[m5p - 1]

        # H1 bias
        dist = abs(row["close"] - h1_row["ema200"]) / pip
        if dist < 20: continue
        bias = 1 if row["close"] > h1_row["ema200"] else -1

        # M5 trend
        if bias == 1 and m5_row["ema5"] <= m5_row["ema13"]: continue
        if bias == -1 and m5_row["ema5"] >= m5_row["ema13"]: continue

        # M1 cross
        m1p = asof_pos(m1.index, ts, 3)
        if m1p is None: continue
        prev = m1.iloc[m1p - 1]
        curr = row

        bull_cross = prev["ema5"] <= prev["ema13"] and curr["ema5"] > curr["ema13"]
        bear_cross = prev["ema5"] >= prev["ema13"] and curr["ema5"] < curr["ema13"]

        if bias == 1 and not bull_cross: continue
        if bias == -1 and not bear_cross: continue

        if not (40 <= curr["rsi7"] <= 60): continue
        if not (0.50 <= curr["atr14"] <= 3.00): continue

        direction = "BUY" if bias == 1 else "SELL"
        lot = calc_lot(balance, 0.3, SL, pip, symbol)
        open_trade = {
            "dir": direction, "entry": row["close"],
            "entry_time": ts, "lot": lot,
            "sl_pips": SL, "tp1": False, "be": False
        }

    return trades


def backtest_s2(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S2 — M5 Medium Frequency Scalp"""
    print("  Running S2 backtest...")
    pip = pip_size(symbol)
    m5  = data["m5"]
    h1  = data["h1"]
    if m5.empty or h1.empty or "close" not in m5.columns:
        print("  SKIP S2 — insufficient M5 data"); return []
    m5 = m5.copy(); h1 = h1.copy()

    h1["ema200"] = ema_series(h1["close"], 200)
    m5["ema9"]   = ema_series(m5["close"], 9)
    m5["ema21"]  = ema_series(m5["close"], 21)
    m5["rsi14"]  = rsi_series(m5["close"], 14)
    m5["macd_h"] = macd_hist(m5["close"])

    trades, balance = [], INIT_BALANCE
    SL, TP1, TP2, BE = 18, 20, 40, 8
    open_trade = None

    for i, (ts, row) in enumerate(m5.iloc[30:].iterrows(), 30):
        h = ts.hour
        in_sess = 7 <= h < 17
        if not in_sess and open_trade is None: continue

        if open_trade:
            p = open_trade
            pnl_pips = (row["close"] - p["entry"]) / pip if p["dir"] == "BUY" \
                       else (p["entry"] - row["close"]) / pip

            if not p["be"] and pnl_pips >= BE:
                p["sl_pips"] = -2; p["be"] = True

            if not p["tp1"] and pnl_pips >= TP1:
                info = mt5.symbol_info(symbol)
                tp1_pnl = TP1*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*0.5)
                balance += tp1_pnl
                p["lot"] = round(p["lot"] * 0.5, 2)
                p["tp1"] = True

            sl_price  = (p["entry"] - p["sl_pips"]*pip) if p["dir"]=="BUY" else (p["entry"] + p["sl_pips"]*pip)
            tp2_price = (p["entry"] + TP2*pip) if p["dir"]=="BUY" else (p["entry"] - TP2*pip)
            elapsed   = (ts - p["entry_time"]).total_seconds() / 60

            exit_price, exit_reason = None, None
            if (p["dir"]=="BUY" and row["low"] <= sl_price) or \
               (p["dir"]=="SELL" and row["high"] >= sl_price):
                exit_price = sl_price; exit_reason = "SL"
            elif (p["dir"]=="BUY" and row["high"] >= tp2_price) or \
                 (p["dir"]=="SELL" and row["low"] <= tp2_price):
                exit_price = tp2_price; exit_reason = "TP2"
            elif elapsed >= 45 or not in_sess:
                exit_price = row["close"]; exit_reason = "TimeExit"

            if exit_price is not None:
                fpips = (exit_price-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-exit_price)/pip
                info  = mt5.symbol_info(symbol)
                pnl_usd = fpips*pip/info.trade_tick_size*info.trade_tick_value*p["lot"]
                balance += pnl_usd
                total_lot = p["lot"] / (0.5 if p["tp1"] else 1.0)
                tp1_pnl = (TP1*pip/info.trade_tick_size*info.trade_tick_value*total_lot*0.5) if p["tp1"] else 0
                trades.append(Trade(p["entry_time"], ts, p["dir"], p["entry"], exit_price,
                                    total_lot, fpips, pnl_usd + tp1_pnl, exit_reason, "S2"))
                open_trade = None
            continue

        if not in_sess: continue
        h1p = asof_pos(h1.index, ts, 201)
        if h1p is None: continue
        h1r = h1.iloc[h1p]
        dist = abs(row["close"] - h1r["ema200"]) / pip
        if dist < 20: continue
        bias = 1 if row["close"] > h1r["ema200"] else -1

        prev = m5.iloc[i-1]
        bull = prev["ema9"] <= prev["ema21"] and row["ema9"] > row["ema21"]
        bear = prev["ema9"] >= prev["ema21"] and row["ema9"] < row["ema21"]
        if bias == 1 and not bull: continue
        if bias == -1 and not bear: continue

        if bias == 1 and not (40 <= row["rsi14"] <= 65): continue
        if bias == -1 and not (35 <= row["rsi14"] <= 60): continue

        if bias == 1 and not (row["macd_h"] > 0 or row["macd_h"] > prev["macd_h"]): continue
        if bias == -1 and not (row["macd_h"] < 0 or row["macd_h"] < prev["macd_h"]): continue

        direction = "BUY" if bias == 1 else "SELL"
        lot = calc_lot(balance, 0.5, SL, pip, symbol)
        open_trade = {"dir": direction, "entry": row["close"], "entry_time": ts,
                      "lot": lot, "sl_pips": SL, "tp1": False, "be": False}

    return trades


def backtest_s1(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S1 — Low Frequency Swing Scalp"""
    print("  Running S1 backtest...")
    pip = pip_size(symbol)
    m15 = data["m15"].copy()
    h1  = data["h1"].copy()
    h4  = data["h4"].copy()

    h4["ema200"]  = ema_series(h4["close"], 200)
    h1["ema200"]  = ema_series(h1["close"], 200)
    m15["ema21"]  = ema_series(m15["close"], 21)
    m15["rsi14"]  = rsi_series(m15["close"], 14)

    trades, balance = [], INIT_BALANCE
    open_trade = None; today_trades = 0; last_day = None

    for ts, row in m15.iloc[30:].iterrows():
        cur_day = ts.date()
        if cur_day != last_day: today_trades = 0; last_day = cur_day

        h = ts.hour
        in_sess = (7 <= h < 12) or (13 <= h < 17)

        if open_trade:
            p = open_trade
            pnl_pips = (row["close"]-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-row["close"])/pip

            for idx, (pp, frac) in enumerate([(25,.25),(50,.25),(100,.25),(200,.25)]):
                if not p["partials"][idx] and pnl_pips >= pp:
                    info = mt5.symbol_info(symbol)
                    part_pnl = pp*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*frac)
                    balance += part_pnl
                    p["partials"][idx] = True
                    if not p["be"]:
                        p["sl_pips"] = -2; p["be"] = True

            sl_price  = (p["entry"] - p["sl_pips"]*pip) if p["dir"]=="BUY" else (p["entry"] + p["sl_pips"]*pip)
            tp_price  = (p["entry"] + p["tp_pips"]*pip) if p["dir"]=="BUY" else (p["entry"] - p["tp_pips"]*pip)
            elapsed_h = (ts - p["entry_time"]).total_seconds() / 3600

            exit_price, exit_reason = None, None
            if (p["dir"]=="BUY" and row["low"] <= sl_price) or \
               (p["dir"]=="SELL" and row["high"] >= sl_price):
                exit_price = sl_price; exit_reason = "SL"
            elif (p["dir"]=="BUY" and row["high"] >= tp_price) or \
                 (p["dir"]=="SELL" and row["low"] <= tp_price):
                exit_price = tp_price; exit_reason = "TP2"
            elif elapsed_h >= 24:
                exit_price = row["close"]; exit_reason = "TimeExit"

            if exit_price is not None:
                rem_frac = 1.0 - sum(0.25 for b in p["partials"] if b)
                if rem_frac <= 0: rem_frac = 0.25
                fpips = (exit_price-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-exit_price)/pip
                info  = mt5.symbol_info(symbol)
                pnl_usd = fpips*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*rem_frac)
                balance += pnl_usd
                part_pnl = sum((pp*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*0.25))
                                for pp,b in zip([25,50,100,200],p["partials"]) if b)
                trades.append(Trade(p["entry_time"], ts, p["dir"], p["entry"], exit_price,
                                    p["lot"], fpips, pnl_usd+part_pnl, exit_reason, "S1"))
                open_trade = None
            continue

        if not in_sess or today_trades >= 5: continue
        h4p = asof_pos(h4.index, ts, 201)
        if h4p is None: continue
        h4r = h4.iloc[h4p]
        dist = abs(row["close"] - h4r["ema200"]) / pip
        if dist < 30: continue
        bias = 1 if row["close"] > h4r["ema200"] else -1

        # simplified trigger: M15 EMA21 reclaim + RSI
        m15p = asof_pos(m15.index, ts, 2, strict=True)
        if m15p is None: continue
        prev = m15.iloc[m15p]
        bull = prev["close"] <= prev["ema21"] and row["close"] > row["ema21"]
        bear = prev["close"] >= prev["ema21"] and row["close"] < row["ema21"]
        if bias == 1 and not bull: continue
        if bias == -1 and not bear: continue
        if bias == 1 and not (40 <= row["rsi14"] <= 65): continue
        if bias == -1 and not (35 <= row["rsi14"] <= 60): continue

        direction = "BUY" if bias == 1 else "SELL"
        sl_pips   = 60
        tp_pips   = sl_pips * 2.0
        lot = calc_lot(balance, 1.0, sl_pips, pip, symbol)
        open_trade = {"dir": direction, "entry": row["close"], "entry_time": ts,
                      "lot": lot, "sl_pips": sl_pips, "tp_pips": tp_pips,
                      "partials": [False]*4, "be": False}
        today_trades += 1

    return trades


def backtest_s6(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S6 — Asian Range Breakout (mirrors debug_s6.py logic exactly)"""
    print("  Running S6 backtest...")
    pip = pip_size(symbol)
    if pip == 0:
        pip = 0.1
    m15 = data["m15"].copy()
    if m15.empty or "close" not in m15.columns:
        print("  WARNING: No M15 data for S6")
        return []
    info_sym = mt5.symbol_info(symbol)
    if info_sym is None:
        print("  WARNING: symbol_info failed for S6")
        return []
    tick_val = info_sym.trade_tick_value
    tick_sz  = info_sym.trade_tick_size

    def pnl_usd(pips, lot):
        if tick_sz <= 0:
            return 0.0
        return pips * pip / tick_sz * tick_val * lot

    trades, balance = [], INIT_BALANCE
    # reset_index so index is 0,1,2,... and 'time' is a plain column
    m15_arr = m15.reset_index()
    # convert index to plain int just in case
    m15_arr = m15_arr.reset_index(drop=True)

    open_trade = None
    last_day   = None
    range_high = range_low = range_size = 0.0
    range_ready = False

    print(f"  S6 pip={pip}  tick_sz={tick_sz}  tick_val={tick_val}")
    print(f"  S6 data: {len(m15_arr)} M15 bars, "
          f"{m15_arr['time'].iloc[0]} to {m15_arr['time'].iloc[-1]}")

    for i in range(len(m15_arr)):
        row = m15_arr.iloc[i]
        ts      = row["time"]
        h       = ts.hour
        cur_day = ts.date()

        # ── daily reset ────────────────────────────────────────────
        if cur_day != last_day:
            last_day    = cur_day
            range_ready = False
            range_high  = range_low = range_size = 0.0
            if open_trade:
                fp  = (row["close"] - open_trade["entry"]) / pip \
                      if open_trade["dir"] == "BUY" \
                      else (open_trade["entry"] - row["close"]) / pip
                pnl = pnl_usd(fp, open_trade["lot"])
                balance += pnl
                trades.append(Trade(open_trade["entry_time"], ts, open_trade["dir"],
                                    open_trade["entry"], row["close"],
                                    open_trade["lot"], fp, pnl, "DayEnd", "S6"))
                open_trade = None

        # ── force close at 17:00 UTC ───────────────────────────────
        if h >= 17:
            if open_trade:
                fp  = (row["close"] - open_trade["entry"]) / pip \
                      if open_trade["dir"] == "BUY" \
                      else (open_trade["entry"] - row["close"]) / pip
                pnl = pnl_usd(fp, open_trade["lot"])
                balance += pnl
                trades.append(Trade(open_trade["entry_time"], ts, open_trade["dir"],
                                    open_trade["entry"], row["close"],
                                    open_trade["lot"], fp, pnl, "ForceClose", "S6"))
                open_trade = None
            continue

        # ── manage open trade ──────────────────────────────────────
        if open_trade:
            p        = open_trade
            sl_p  = p["entry"] - p["sl_pips"]  * pip if p["dir"] == "BUY" \
                    else p["entry"] + p["sl_pips"]  * pip
            tp1_p = p["entry"] + p["tp1_pips"] * pip if p["dir"] == "BUY" \
                    else p["entry"] - p["tp1_pips"] * pip
            tp2_p = p["entry"] + p["tp2_pips"] * pip if p["dir"] == "BUY" \
                    else p["entry"] - p["tp2_pips"] * pip

            if not p["tp1"]:
                hit1 = (p["dir"] == "BUY"  and row["high"] >= tp1_p) or \
                       (p["dir"] == "SELL" and row["low"]  <= tp1_p)
                if hit1:
                    balance += pnl_usd(p["tp1_pips"], p["lot"] * 0.5)
                    p["tp1"] = True

            hit_sl  = (p["dir"] == "BUY"  and row["low"]  <= sl_p)  or \
                      (p["dir"] == "SELL" and row["high"] >= sl_p)
            hit_tp2 = (p["dir"] == "BUY"  and row["high"] >= tp2_p) or \
                      (p["dir"] == "SELL" and row["low"]  <= tp2_p)

            if hit_sl or hit_tp2:
                exit_price  = sl_p  if hit_sl  else tp2_p
                exit_reason = "SL"  if hit_sl  else "TP2"
                fp          = (exit_price - p["entry"]) / pip if p["dir"] == "BUY" \
                              else (p["entry"] - exit_price) / pip
                rem_lot     = p["lot"] * (0.5 if p["tp1"] else 1.0)
                pnl         = pnl_usd(fp, rem_lot)
                tp1p        = pnl_usd(p["tp1_pips"], p["lot"] * 0.5) if p["tp1"] else 0
                balance    += pnl
                trades.append(Trade(p["entry_time"], ts, p["dir"],
                                    p["entry"], exit_price,
                                    p["lot"], fp, pnl + tp1p, exit_reason, "S6"))
                open_trade = None
            continue

        # ── calculate Asian range (00:00–07:00 UTC bars) ───────────
        # Bounds are normalised to dollar values so they work for any broker pip scale:
        #   $4–$50 range, max single candle $20 (same as debug_s6.py with pip=0.1)
        if h == 7 and not range_ready:
            window     = m15_arr.iloc[max(0, i - 28):i]
            window_day = window[window["time"].dt.date == cur_day]
            if len(window_day) >= 10:
                rh = window_day["high"].max()
                rl = window_day["low"].min()
                rs = (rh - rl) / pip          # range in pips
                mc = (window_day["high"] - window_day["low"]).max() / pip
                r_min = 4.0  / pip            # $4  in pips
                r_max = 50.0 / pip            # $50 in pips
                c_max = 20.0 / pip            # $20 in pips
                if r_min <= rs <= r_max and mc <= c_max:
                    range_high  = rh
                    range_low   = rl
                    range_size  = rs
                    range_ready = True

        # ── OCO breakout entry: 07:45–10:00 UTC ──────────────────────
        # Mirror MQL5 EA stop-order behaviour: only enter if price actually
        # reaches the level above/below the range (first breakout wins).
        if range_ready and open_trade is None and not (h == 7 and ts.minute < 45):
            if h >= 10:                       # stop orders expired
                range_ready = False
            else:
                buy_e  = range_high + 2 * pip
                sell_e = range_low  - 2 * pip
                triggered = None
                if row["high"] >= buy_e and row["low"] <= sell_e:
                    # both levels hit same bar — use close direction to pick
                    triggered = "BUY" if row["close"] >= (range_high + range_low) / 2 else "SELL"
                elif row["high"] >= buy_e:
                    triggered = "BUY"
                elif row["low"] <= sell_e:
                    triggered = "SELL"

                if triggered:
                    buf_pips = 1.0 / pip
                    sl_pips  = range_size + buf_pips
                    tp1_pips = range_size * 0.70
                    tp2_pips = range_size * 1.50
                    entry    = buy_e if triggered == "BUY" else sell_e
                    lot      = calc_lot(balance, 0.5, sl_pips, pip, symbol)
                    open_trade = {"dir": triggered, "entry": entry, "entry_time": ts,
                                  "lot": lot, "tp1": False,
                                  "sl_pips": sl_pips, "tp1_pips": tp1_pips, "tp2_pips": tp2_pips}

    print(f"  S6 done: {len(trades)} trades")
    return trades


def backtest_s5(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S5 — News Spike Reversal (spike proxy: M1 candle > 80 pips)"""
    print("  Running S5 backtest...")
    pip = pip_size(symbol)
    m1  = data["m1"]
    if m1.empty or "close" not in m1.columns:
        print("  SKIP S5 — insufficient M1 data"); return []
    m1 = m1.copy()
    m1["rsi14"] = rsi_series(m1["close"], 14)

    trades, balance = [], INIT_BALANCE
    open_trade = None; spike_time = None; spike_dir = 0
    spike_high = spike_low = 0.0; in_rev = False

    for ts, row in m1.iloc[15:].iterrows():
        h = ts.hour
        in_sess = 7 <= h < 22

        if open_trade:
            p = open_trade
            pnl_pips = (row["close"]-p["entry"])/pip if p["dir"]=="BUY" \
                       else (p["entry"]-row["close"])/pip
            sl_p  = (p["entry"] - 30*pip) if p["dir"]=="BUY" else (p["entry"] + 30*pip)
            tp2_p = (p["entry"] + 70*pip) if p["dir"]=="BUY" else (p["entry"] - 70*pip)
            tp1_p = (p["entry"] + 50*pip) if p["dir"]=="BUY" else (p["entry"] - 50*pip)
            elapsed = (ts - p["entry_time"]).total_seconds() / 60

            if not p["tp1"] and ((p["dir"]=="BUY" and row["high"]>=tp1_p) or (p["dir"]=="SELL" and row["low"]<=tp1_p)):
                info = mt5.symbol_info(symbol)
                balance += 50*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*0.5)
                p["tp1"] = True

            exit_price = exit_reason = None
            if (p["dir"]=="BUY" and row["low"]<=sl_p) or (p["dir"]=="SELL" and row["high"]>=sl_p):
                exit_price = sl_p; exit_reason = "SL"
            elif (p["dir"]=="BUY" and row["high"]>=tp2_p) or (p["dir"]=="SELL" and row["low"]<=tp2_p):
                exit_price = tp2_p; exit_reason = "TP2"
            elif elapsed >= 240 or not in_sess:
                exit_price = row["close"]; exit_reason = "TimeExit"

            if exit_price:
                fpips = (exit_price-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-exit_price)/pip
                info  = mt5.symbol_info(symbol)
                lot_r = p["lot"]*(0.5 if p["tp1"] else 1.0)
                pnl   = fpips*pip/info.trade_tick_size*info.trade_tick_value*lot_r
                balance += pnl
                tp1_pnl = (50*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*0.5)) if p["tp1"] else 0
                trades.append(Trade(p["entry_time"], ts, p["dir"], p["entry"], exit_price,
                                    p["lot"], fpips, pnl+tp1_pnl, exit_reason, "S5"))
                open_trade = None; in_rev = False
            continue

        if not in_sess: continue

        # detect spike
        if not in_rev:
            candle_range = (row["high"] - row["low"]) / pip
            if candle_range >= 80:
                spike_high = row["high"]; spike_low = row["low"]
                spike_dir  = 1 if row["close"] > row["open"] else -1
                spike_time = ts; in_rev = True

        # seek reversal 5-30 min after spike
        if in_rev and spike_time and open_trade is None:
            elapsed = (ts - spike_time).total_seconds() / 60
            if elapsed > 30: in_rev = False; continue
            if elapsed < 5: continue
            # check if spike failed (continued >100 pips)
            if spike_dir == 1 and row["close"] > spike_high + 100*pip: in_rev=False; continue
            if spike_dir == -1 and row["close"] < spike_low - 100*pip: in_rev=False; continue
            # reversal signal
            if spike_dir == -1 and row["rsi14"] < 35:
                lot = calc_lot(balance, 1.0, 30, pip, symbol)
                open_trade = {"dir":"BUY","entry":row["close"],"entry_time":ts,"lot":lot,"tp1":False}
            elif spike_dir == 1 and row["rsi14"] > 65:
                lot = calc_lot(balance, 1.0, 30, pip, symbol)
                open_trade = {"dir":"SELL","entry":row["close"],"entry_time":ts,"lot":lot,"tp1":False}

    return trades


def backtest_s4(data_map: dict) -> List[Trade]:
    """S4 — Multi-Pair (runs S3 logic on each of 5 pairs)"""
    print("  Running S4 backtest (5 pairs)...")
    all_trades = []
    pairs = ["XAUUSD", "XAGUSD", "USDJPY", "GBPUSD", "EURUSD"]
    configs = {
        "XAUUSD": {"sl":7,  "tp1":10,"tp2":15,"atr_min":0.50, "atr_max":3.00},
        "XAGUSD": {"sl":8,  "tp1":12,"tp2":18,"atr_min":0.03, "atr_max":0.20},
        "USDJPY": {"sl":8,  "tp1":12,"tp2":18,"atr_min":0.10, "atr_max":0.50},
        "GBPUSD": {"sl":10, "tp1":15,"tp2":22,"atr_min":0.0008,"atr_max":0.003},
        "EURUSD": {"sl":7,  "tp1":11,"tp2":16,"atr_min":0.0005,"atr_max":0.0025},
    }
    for sym in pairs:
        if sym not in data_map or not data_map[sym]:
            print(f"    Skipping {sym} — no data")
            continue
        cfg = configs[sym]
        pip = pip_size(sym)
        d   = data_map[sym]
        m1  = d["m1"].copy()
        m5  = d.get("m5", pd.DataFrame())
        h1  = d.get("h1", pd.DataFrame())
        if m1.empty or m5.empty or h1.empty: continue

        h1["ema200"] = ema_series(h1["close"], 200)
        m5["ema5"]   = ema_series(m5["close"], 5)
        m5["ema13"]  = ema_series(m5["close"], 13)
        m1["ema5"]   = ema_series(m1["close"], 5)
        m1["ema13"]  = ema_series(m1["close"], 13)
        m1["rsi7"]   = rsi_series(m1["close"], 7)
        m1["atr14"]  = atr_series(m1, 14)

        balance = INIT_BALANCE / 5   # split balance per pair
        open_trade = None

        for ts, row in m1.iloc[210:].iterrows():
            h = ts.hour
            in_sess = 7 <= h < 17  # simplified session for all pairs

            if open_trade:
                p = open_trade
                pnl_pips = (row["close"]-p["entry"])/pip if p["dir"]=="BUY" \
                           else (p["entry"]-row["close"])/pip
                sl_p  = (p["entry"] - p["sl_pips"]*pip) if p["dir"]=="BUY" else (p["entry"] + p["sl_pips"]*pip)
                tp2_p = (p["entry"] + cfg["tp2"]*pip) if p["dir"]=="BUY" else (p["entry"] - cfg["tp2"]*pip)
                elapsed = (ts - p["entry_time"]).total_seconds() / 60

                if not p["be"] and pnl_pips >= 4: p["be"]=True; p["sl_pips"]=-6
                if not p["tp1"] and pnl_pips >= cfg["tp1"]:
                    info = mt5.symbol_info(sym)
                    balance += cfg["tp1"]*pip/info.trade_tick_size*info.trade_tick_value*(p["lot"]*0.6)
                    p["lot"] = round(p["lot"]*0.4, 2); p["tp1"] = True

                exit_price = exit_reason = None
                if (p["dir"]=="BUY" and row["low"]<=sl_p) or (p["dir"]=="SELL" and row["high"]>=sl_p):
                    exit_price=sl_p; exit_reason="SL"
                elif (p["dir"]=="BUY" and row["high"]>=tp2_p) or (p["dir"]=="SELL" and row["low"]<=tp2_p):
                    exit_price=tp2_p; exit_reason="TP2"
                elif elapsed>=15 or not in_sess:
                    exit_price=row["close"]; exit_reason="TimeExit"

                if exit_price:
                    fpips = (exit_price-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-exit_price)/pip
                    info = mt5.symbol_info(sym)
                    pnl = fpips*pip/info.trade_tick_size*info.trade_tick_value*p["lot"]
                    balance += pnl
                    all_trades.append(Trade(p["entry_time"],ts,p["dir"],p["entry"],exit_price,
                                            p["lot"],fpips,pnl,exit_reason,f"S4_{sym}"))
                    open_trade = None
                continue

            if not in_sess: continue
            h1p = asof_pos(h1.index, ts, 201)
            m5p = asof_pos(m5.index, ts, 14)
            if h1p is None or m5p is None: continue

            h1r = h1.iloc[h1p]
            m5r = m5.iloc[m5p]
            dist = abs(row["close"] - h1r["ema200"]) / pip
            if dist < 20: continue
            bias = 1 if row["close"] > h1r["ema200"] else -1
            if bias==1 and m5r["ema5"] <= m5r["ema13"]: continue
            if bias==-1 and m5r["ema5"] >= m5r["ema13"]: continue

            m1p = asof_pos(m1.index, ts, 3)
            if m1p is None: continue
            prev = m1.iloc[m1p - 1]
            bull = prev["ema5"]<=prev["ema13"] and row["ema5"]>row["ema13"]
            bear = prev["ema5"]>=prev["ema13"] and row["ema5"]<row["ema13"]
            if bias==1 and not bull: continue
            if bias==-1 and not bear: continue
            if not (40<=row["rsi7"]<=60): continue
            if not (cfg["atr_min"]<=row["atr14"]<=cfg["atr_max"]): continue

            direction = "BUY" if bias==1 else "SELL"
            lot = calc_lot(balance, 0.3, cfg["sl"], pip, sym)
            open_trade = {"dir":direction,"entry":row["close"],"entry_time":ts,
                          "lot":lot,"sl_pips":cfg["sl"],"tp1":False,"be":False}

    return all_trades


# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
# V2 IMPROVED STRATEGIES
# ══════════════════════════════════════════════════════════════════════

def backtest_s1_v2(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S1 v2 — Swing Scalp (uncapped-winner version)
    Keeps S1v1's entry exactly (H4 trend, EMA21 cross, RSI 40-65/35-60,
    max 5/day). The change is the EXIT: instead of a hard 2:1 TP that
    caps every winner at +120 pips, the final 25% tranche rides a
    trailing stop so strong gold trends can run to +300/+500.

    Exit model:
    - Bank 25% at +30, 25% at +60, 25% at +120 (3 partials)
    - BE (+2) locked after first partial
    - After +120: SL ratchets to +60 on the runner
    - Final 25%: 100-pip trailing stop off peak; no hard TP
    - Time exit 48h (let trends develop)
    """
    print("  Running S1 v2 backtest...")
    pip = pip_size(symbol)
    m15 = data["m15"].copy()
    h4  = data["h4"].copy()

    h4["ema200"] = ema_series(h4["close"], 200)
    m15["ema21"] = ema_series(m15["close"], 21)
    m15["rsi14"] = rsi_series(m15["close"], 14)

    info     = mt5.symbol_info(symbol)
    tick_val = info.trade_tick_value
    tick_sz  = info.trade_tick_size

    def pu(pips_f, lot_f):
        return pips_f * pip / tick_sz * tick_val * lot_f

    PARTS = [(30, .25), (60, .25), (120, .25)]   # bank 75% progressively
    TRAIL = 100                                   # runner trailing distance (pips)

    trades, balance = [], INIT_BALANCE
    open_trade = None; today_trades = 0; last_day = None

    for ts, row in m15.iloc[30:].iterrows():
        cur_day = ts.date()
        if cur_day != last_day: today_trades = 0; last_day = cur_day

        h = ts.hour
        in_sess = (7 <= h < 12) or (13 <= h < 17)

        if open_trade:
            p = open_trade
            pnl_pips = (row["close"]-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-row["close"])/pip
            p["peak"] = max(p["peak"], pnl_pips)

            # progressive partials (25% each) + BE after first
            for idx, (pp, frac) in enumerate(PARTS):
                if not p["partials"][idx] and pnl_pips >= pp:
                    balance += pu(pp, p["lot"] * frac)
                    p["partials"][idx] = True
                    if idx == 0 and not p["be"]:
                        p["sl_pips"] = -2; p["be"] = True
                    if idx == 2:                       # after +120, lock +60 on runner
                        p["sl_pips"] = min(p["sl_pips"], -60)

            # runner trailing stop: only active once all 3 partials banked
            if all(p["partials"]):
                trail_sl = -(p["peak"] - TRAIL)         # stored as +profit lock
                p["sl_pips"] = min(p["sl_pips"], trail_sl)

            sl_price  = (p["entry"] - p["sl_pips"]*pip) if p["dir"]=="BUY" else (p["entry"] + p["sl_pips"]*pip)
            elapsed_h = (ts - p["entry_time"]).total_seconds() / 3600

            exit_price, exit_reason = None, None
            if (p["dir"]=="BUY" and row["low"] <= sl_price) or \
               (p["dir"]=="SELL" and row["high"] >= sl_price):
                exit_price = sl_price
                exit_reason = "Trail" if all(p["partials"]) else ("BE" if p["be"] else "SL")
            elif elapsed_h >= 48:
                exit_price = row["close"]; exit_reason = "TimeExit"

            if exit_price is not None:
                rem_frac = max(0.25, 1.0 - sum(0.25 for b in p["partials"] if b))
                fpips = (exit_price-p["entry"])/pip if p["dir"]=="BUY" else (p["entry"]-exit_price)/pip
                pnl_usd = pu(fpips, p["lot"] * rem_frac)
                balance += pnl_usd
                part_pnl = sum(pu(pp, p["lot"]*frac)
                               for (pp,frac),b in zip(PARTS, p["partials"]) if b)
                trades.append(Trade(p["entry_time"], ts, p["dir"], p["entry"], exit_price,
                                    p["lot"], fpips, pnl_usd+part_pnl, exit_reason, "S1v2"))
                open_trade = None
            continue

        if not in_sess or today_trades >= 5: continue

        h4p = asof_pos(h4.index, ts, 201)
        if h4p is None: continue
        h4r = h4.iloc[h4p]
        dist = abs(row["close"] - h4r["ema200"]) / pip
        if dist < 30: continue
        bias = 1 if row["close"] > h4r["ema200"] else -1

        m15p = asof_pos(m15.index, ts, 2, strict=True)
        if m15p is None: continue
        prev = m15.iloc[m15p]
        bull = prev["close"] <= prev["ema21"] and row["close"] > row["ema21"]
        bear = prev["close"] >= prev["ema21"] and row["close"] < row["ema21"]
        if bias == 1 and not bull: continue
        if bias == -1 and not bear: continue
        if bias == 1  and not (40 <= row["rsi14"] <= 65): continue
        if bias == -1 and not (35 <= row["rsi14"] <= 60): continue

        direction = "BUY" if bias == 1 else "SELL"
        sl_pips   = 60
        lot = calc_lot(balance, 1.0, sl_pips, pip, symbol)
        open_trade = {"dir": direction, "entry": row["close"], "entry_time": ts,
                      "lot": lot, "sl_pips": sl_pips, "peak": 0.0,
                      "partials": [False]*3, "be": False}
        today_trades += 1

    return trades


def backtest_s2_v2(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S2 v2 — M5 Scalp (improved)
    Changes vs v1:
    - Session: 8-14 UTC only (London open + early NY, skip noisy Asian hours)
    - H4 EMA200 added: H1 AND H4 must both agree on direction
    - MACD filter fixed: 'and' not 'or'
    - Time exit: 180 min (was 45 min — trades need time to breathe)
    - TP1=25, TP2=50, SL=20 (improved R:R vs original TP1=20, TP2=40, SL=18)
    - ATR gate: 100-500 pips (dollar-normalized for XAUUSD)
    """
    print("  Running S2 v2 backtest...")
    pip = pip_size(symbol)
    m5  = data["m5"].copy()
    h1  = data["h1"].copy()
    h4  = data["h4"].copy()
    if m5.empty or h1.empty or "close" not in m5.columns:
        print("  SKIP S2v2 — insufficient M5 data"); return []

    h4["ema200"] = ema_series(h4["close"], 200)
    h1["ema200"] = ema_series(h1["close"], 200)
    m5["ema9"]   = ema_series(m5["close"], 9)
    m5["ema21"]  = ema_series(m5["close"], 21)
    m5["rsi14"]  = rsi_series(m5["close"], 14)
    m5["macd_h"] = macd_hist(m5["close"])
    m5["atr14"]  = atr_series(m5, 14)

    info     = mt5.symbol_info(symbol)
    tick_val = info.trade_tick_value
    tick_sz  = info.trade_tick_size

    def pu(pips_f, lot_f):
        return pips_f * pip / tick_sz * tick_val * lot_f

    trades, balance = [], INIT_BALANCE
    SL    = 20
    TP1   = 25     # 1.25:1 partial (close 50%, BE+ lock)
    TRAIL = 35     # runner trailing distance after TP1 (pips)
    BE    = 10
    open_trade = None

    for i, (ts, row) in enumerate(m5.iloc[30:].iterrows(), 30):
        h       = ts.hour
        in_sess = 8 <= h < 14      # London open + early NY only
        if not in_sess and open_trade is None: continue

        if open_trade:
            p        = open_trade
            pnl_pips = (row["close"] - p["entry"]) / pip if p["dir"] == "BUY" \
                       else (p["entry"] - row["close"]) / pip
            hi_pips  = (row["high"] - p["entry"]) / pip if p["dir"] == "BUY" \
                       else (p["entry"] - row["low"]) / pip
            p["peak"] = max(p["peak"], hi_pips)

            if not p["be"] and pnl_pips >= BE:
                p["sl_pips"] = -2; p["be"] = True

            if not p["tp1"] and pnl_pips >= TP1:
                balance += pu(TP1, p["lot"] * 0.5)
                p["lot"]  = round(p["lot"] * 0.5, 2)
                p["tp1"]  = True
                p["sl_pips"] = min(p["sl_pips"], -2)   # lock BE+ on runner

            # after TP1: trail the runner off its peak (no fixed TP2)
            if p["tp1"]:
                trail_lock = -(p["peak"] - TRAIL)
                p["sl_pips"] = min(p["sl_pips"], trail_lock)

            sl_price  = (p["entry"] - p["sl_pips"] * pip) if p["dir"] == "BUY" \
                        else (p["entry"] + p["sl_pips"] * pip)
            elapsed   = (ts - p["entry_time"]).total_seconds() / 60

            exit_price, exit_reason = None, None
            if (p["dir"] == "BUY"  and row["low"]  <= sl_price) or \
               (p["dir"] == "SELL" and row["high"] >= sl_price):
                exit_price = sl_price
                exit_reason = "Trail" if p["tp1"] else ("BE" if p["be"] else "SL")
            elif elapsed >= 180 or not in_sess:
                exit_price = row["close"]; exit_reason = "TimeExit"

            if exit_price is not None:
                fpips    = (exit_price - p["entry"]) / pip if p["dir"] == "BUY" \
                           else (p["entry"] - exit_price) / pip
                pnl_usd  = pu(fpips, p["lot"])
                balance += pnl_usd
                total_lot = p["lot"] / (0.5 if p["tp1"] else 1.0)
                tp1_pnl   = pu(TP1, total_lot * 0.5) if p["tp1"] else 0
                trades.append(Trade(p["entry_time"], ts, p["dir"],
                                    p["entry"], exit_price, total_lot,
                                    fpips, pnl_usd + tp1_pnl, exit_reason, "S2v2"))
                open_trade = None
            continue

        if not in_sess: continue

        # H1 + H4 dual-TF bias must agree
        h1p = asof_pos(h1.index, ts, 201)
        h4p = asof_pos(h4.index, ts, 201)
        if h1p is None or h4p is None: continue
        h1r = h1.iloc[h1p]
        h4r = h4.iloc[h4p]
        h1_bias = 1 if row["close"] > h1r["ema200"] else -1
        h4_bias = 1 if row["close"] > h4r["ema200"] else -1
        if h1_bias != h4_bias: continue
        bias = h1_bias

        prev = m5.iloc[i - 1]
        bull = prev["ema9"] <= prev["ema21"] and row["ema9"] > row["ema21"]
        bear = prev["ema9"] >= prev["ema21"] and row["ema9"] < row["ema21"]
        if bias == 1  and not bull: continue
        if bias == -1 and not bear: continue

        if bias == 1  and not (42 <= row["rsi14"] <= 68): continue
        if bias == -1 and not (32 <= row["rsi14"] <= 58): continue

        # MACD: histogram positive AND expanding (bug fix: 'and' not 'or')
        if bias == 1  and not (row["macd_h"] > 0 and row["macd_h"] > prev["macd_h"]): continue
        if bias == -1 and not (row["macd_h"] < 0 and row["macd_h"] < prev["macd_h"]): continue

        # ATR gate: dollar-normalized (100-500 pips = $1-$5 for XAUUSD M5)
        atr_pips = row["atr14"] / pip
        if not (100 <= atr_pips <= 500): continue

        direction = "BUY" if bias == 1 else "SELL"
        lot = calc_lot(balance, 0.5, SL, pip, symbol)
        open_trade = {"dir": direction, "entry": row["close"], "entry_time": ts,
                      "lot": lot, "sl_pips": SL, "tp1": False, "be": False,
                      "peak": 0.0}

    return trades


def backtest_s6_v2(data: dict, symbol="XAUUSD") -> List[Trade]:
    """S6 v2 — Asian Range Breakout (improved)
    vs v1: H4 EMA200 trend filter (only trade in trend direction),
           BE after TP1, stricter range quality (min 16 bars,
           no single candle > 60% of total range).
    NOTE: a trailing runner (the exit that doubled S1/S2) was tested
    here and performed WORSE (PF 1.24 vs 1.43). S6 is an intraday
    mean-reverting breakout — fixed TP1/TP2 locks profit before the
    post-breakout snap-back. Trailing exits are kept out of S6.
    """
    print("  Running S6 v2 backtest...")
    pip = pip_size(symbol)
    if pip == 0: pip = 0.1
    m15 = data["m15"].copy()
    h4  = data["h4"].copy()
    if m15.empty or "close" not in m15.columns: return []
    info_sym = mt5.symbol_info(symbol)
    if info_sym is None: return []
    tick_val = info_sym.trade_tick_value
    tick_sz  = info_sym.trade_tick_size

    h4["ema200"] = ema_series(h4["close"], 200)

    # range-validity bounds (pips). Default: gold-$ scale. ATR mode:
    # multiples of this symbol's own median H4-ATR → instrument-agnostic.
    if S6_ATR_BOUNDS:
        _atr = atr_series(h4, 14).median()
        if not _atr or _atr <= 0:
            return []
        S6_RMIN = S6_RMIN_ATR * _atr / pip
        S6_RMAX = S6_RMAX_ATR * _atr / pip
        S6_CMAX = S6_CMAX_ATR * _atr / pip
        S6_BUF  = S6_BUF_ATR  * _atr / pip
    else:
        S6_RMIN, S6_RMAX = 4.0 / pip, 50.0 / pip
        S6_CMAX, S6_BUF  = 20.0 / pip, 1.0 / pip

    def pu(pips_f, lot_f):
        if tick_sz <= 0: return 0.0
        return pips_f * pip / tick_sz * tick_val * lot_f

    trades, balance = [], INIT_BALANCE
    m15_arr = m15.reset_index().reset_index(drop=True)
    open_trade  = None
    last_day    = None
    range_high  = range_low = range_size = 0.0
    range_ready = False

    for i in range(len(m15_arr)):
        row     = m15_arr.iloc[i]
        ts      = row["time"]
        h       = ts.hour
        cur_day = ts.date()

        # ── daily reset ────────────────────────────────────────────
        if cur_day != last_day:
            last_day    = cur_day
            range_ready = False
            range_high  = range_low = range_size = 0.0
            if open_trade:
                fp  = (row["close"] - open_trade["entry"]) / pip \
                      if open_trade["dir"] == "BUY" \
                      else (open_trade["entry"] - row["close"]) / pip
                pnl = pu(fp, open_trade["lot"])
                balance += pnl
                trades.append(Trade(open_trade["entry_time"], ts, open_trade["dir"],
                                    open_trade["entry"], row["close"],
                                    open_trade["lot"], fp, pnl, "DayEnd", "S6v2"))
                open_trade = None

        # ── force close at 17:00 UTC ───────────────────────────────
        if h >= 17:
            if open_trade:
                fp  = (row["close"] - open_trade["entry"]) / pip \
                      if open_trade["dir"] == "BUY" \
                      else (open_trade["entry"] - row["close"]) / pip
                pnl = pu(fp, open_trade["lot"])
                balance += pnl
                trades.append(Trade(open_trade["entry_time"], ts, open_trade["dir"],
                                    open_trade["entry"], row["close"],
                                    open_trade["lot"], fp, pnl, "ForceClose", "S6v2"))
                open_trade = None
            continue

        # ── manage open trade ──────────────────────────────────────
        # S6 is an intraday mean-reverting breakout: a fixed TP2 locks
        # profit before the post-breakout snap-back. (A trailing runner
        # — great for trend strategies S1/S2 — gives that profit back
        # here and tested worse: PF 1.24 vs 1.43.)
        if open_trade:
            p     = open_trade
            sl_p  = p["entry"] - p["sl_pips"]  * pip if p["dir"] == "BUY" \
                    else p["entry"] + p["sl_pips"]  * pip
            tp1_p = p["entry"] + p["tp1_pips"] * pip if p["dir"] == "BUY" \
                    else p["entry"] - p["tp1_pips"] * pip
            tp2_p = p["entry"] + p["tp2_pips"] * pip if p["dir"] == "BUY" \
                    else p["entry"] - p["tp2_pips"] * pip

            if not p["tp1"]:
                hit1 = (p["dir"] == "BUY"  and row["high"] >= tp1_p) or \
                       (p["dir"] == "SELL" and row["low"]  <= tp1_p)
                if hit1:
                    balance += pu(p["tp1_pips"], p["lot"] * 0.5)
                    p["tp1"] = True
                    # BE after TP1: lock a profit on the remaining 50%,
                    # sized as 10% of the Asian range (symbol-agnostic,
                    # range-proportional — the whole strategy is). sl_pips
                    # is in PIPS; negative = profit side. The old
                    # `-1.0/pip` was a price/pip ratio (≈-100 on XAU by
                    # luck, -10000 on 5-digit FX → the 10000-pip "SL books
                    # profit" artifact). 10%·range ≈ the old XAU economics
                    # ($1 on a $10 gold range) AND scales correctly to FX.
                    p["sl_pips"] = -(p["range_size"] * 0.10)

            hit_sl  = (p["dir"] == "BUY"  and row["low"]  <= sl_p)  or \
                      (p["dir"] == "SELL" and row["high"] >= sl_p)
            hit_tp2 = (p["dir"] == "BUY"  and row["high"] >= tp2_p) or \
                      (p["dir"] == "SELL" and row["low"]  <= tp2_p)

            if hit_sl or hit_tp2:
                exit_price  = sl_p  if hit_sl  else tp2_p
                exit_reason = "SL"  if hit_sl  else "TP2"
                fp          = (exit_price - p["entry"]) / pip if p["dir"] == "BUY" \
                              else (p["entry"] - exit_price) / pip
                rem_lot     = p["lot"] * (0.5 if p["tp1"] else 1.0)
                pnl         = pu(fp, rem_lot)
                tp1p        = pu(p["tp1_pips"], p["lot"] * 0.5) if p["tp1"] else 0
                balance    += pnl
                trades.append(Trade(p["entry_time"], ts, p["dir"],
                                    p["entry"], exit_price,
                                    p["lot"], fp, pnl + tp1p, exit_reason, "S6v2"))
                open_trade = None
            continue

        # ── calculate Asian range ──────────────────────────────────
        if h == 7 and not range_ready:
            window     = m15_arr.iloc[max(0, i - 28):i]
            window_day = window[window["time"].dt.date == cur_day]
            # stricter: require at least 16 bars (was 10)
            if len(window_day) >= 16:
                rh  = window_day["high"].max()
                rl  = window_day["low"].min()
                rs  = (rh - rl) / pip
                mc  = (window_day["high"] - window_day["low"]).max() / pip
                if S6_RMIN <= rs <= S6_RMAX and mc <= S6_CMAX:
                    # quality filter: no single candle body > 60% of range
                    bodies = (window_day["close"] - window_day["open"]).abs()
                    if bodies.max() / pip <= rs * 0.6:
                        range_high  = rh
                        range_low   = rl
                        range_size  = rs
                        range_ready = True

        # ── OCO breakout: 07:45 to 10:00 UTC ──────────────────────
        if range_ready and open_trade is None and not (h == 7 and ts.minute < 45):
            if h >= 10:
                range_ready = False
            else:
                buy_e  = range_high + 2 * pip
                sell_e = range_low  - 2 * pip
                triggered = None
                if row["high"] >= buy_e and row["low"] <= sell_e:
                    triggered = "BUY" if row["close"] >= (range_high + range_low) / 2 \
                                else "SELL"
                elif row["high"] >= buy_e:
                    triggered = "BUY"
                elif row["low"] <= sell_e:
                    triggered = "SELL"

                if triggered:
                    # ── H4 trend filter ────────────────────────────
                    h4p = asof_pos(h4.index, ts, 201)
                    if h4p is not None:
                        h4r      = h4.iloc[h4p]
                        h4_dist  = abs(row["close"] - h4r["ema200"]) / pip
                        h4_bull  = row["close"] > h4r["ema200"]
                        # reject counter-trend trade when clearly in trend
                        if triggered == "BUY"  and not h4_bull and h4_dist > 30:
                            triggered = None
                        elif triggered == "SELL" and h4_bull and h4_dist > 30:
                            triggered = None

                if triggered:
                    buf_pips = S6_BUF
                    sl_pips  = range_size + buf_pips
                    tp1_pips = range_size * 0.70
                    tp2_pips = range_size * 1.50
                    entry    = buy_e if triggered == "BUY" else sell_e
                    lot      = calc_lot(balance, S6_RISK_PCT, sl_pips, pip, symbol)
                    open_trade = {"dir": triggered, "entry": entry, "entry_time": ts,
                                  "lot": lot, "tp1": False,
                                  "sl_pips": sl_pips, "tp1_pips": tp1_pips,
                                  "tp2_pips": tp2_pips, "range_size": range_size}

    return trades


# ══════════════════════════════════════════════════════════════════════
# CPP — Confluence Pullback Portfolio (multi-symbol, 1:2, hybrid agent)
# ══════════════════════════════════════════════════════════════════════
def backtest_cpp(data: dict, symbol: str, params: dict,
                 agent: TradeConfirmationAgent) -> List[Trade]:
    """Drive trading_agents/strategies/confluence_pullback on one symbol.

    M15 trading TF + H1 trend TF. Every detected setup is gated by the
    hybrid confirmation agent (advisory/rule mode here so the 2y replay is
    deterministic and makes zero API calls). Exit is regime-switched:
    trend → partial+breakeven+ATR-trailing runner; range → strict fixed 1:2.
    """
    print(f"  Running CPP backtest [{symbol}]...")
    m15 = data.get("m15"); h1 = data.get("h1")
    if m15 is None or h1 is None or m15.empty or h1.empty or "close" not in m15:
        print(f"  SKIP CPP {symbol} — insufficient data"); return []

    p = params
    m, h = cpp.prepare(m15, h1, p)
    pip = pip_size(symbol)
    info = mt5.symbol_info(symbol)
    if not info:
        print(f"  SKIP CPP {symbol} — no symbol_info"); return []
    tick_val, tick_sz = info.trade_tick_value, info.trade_tick_size

    def usd(price_move: float, lot: float) -> float:
        return price_move / tick_sz * tick_val * lot

    warm = max(p["htf_ema"], p["adx_period"] * 4, p["stoch_k"] + p["stoch_d"]) + 5
    trades: List[Trade] = []
    balance = INIT_BALANCE
    open_t = None
    today = None
    n_today = 0
    recent_losses = 0

    rows = m.iloc[warm:]
    for i in range(1, len(rows)):
        ts = rows.index[i]
        row = rows.iloc[i]
        prev = rows.iloc[i - 1]

        d = ts.date()
        if d != today:
            today, n_today = d, 0

        # ── manage an open position ───────────────────────────────────
        if open_t:
            t = open_t
            up = (row["high"] - t["entry"]) if t["dir"] == "BUY" else (t["entry"] - row["low"])
            t["peak"] = max(t["peak"], up)
            r_dist = t["sl_dist"]
            exit_price = exit_reason = None
            fixed = p.get("exit_mode", "fixed") == "fixed"

            if fixed:
                # clean strict 1:2 — SL / 2R-TP / time. Optional BE at +1R.
                if p.get("use_breakeven") and not t["partial"] and t["peak"] >= r_dist:
                    t["stop"] = t["entry"]
                    t["partial"] = True
                if (t["dir"] == "BUY" and row["low"] <= t["stop"]) or \
                   (t["dir"] == "SELL" and row["high"] >= t["stop"]):
                    exit_price = t["stop"]
                    exit_reason = "BE" if t["partial"] else "SL"
                elif (t["dir"] == "BUY" and row["high"] >= t["tp"]) or \
                     (t["dir"] == "SELL" and row["low"] <= t["tp"]):
                    exit_price, exit_reason = t["tp"], "TP2R"
            elif t["regime"] == "trend":
                cur = (row["close"] - t["entry"]) if t["dir"] == "BUY" else (t["entry"] - row["close"])
                if not t["partial"] and t["peak"] >= p["be_at_r"] * r_dist:
                    # bank partial + lock breakeven on the runner
                    balance += usd(p["be_at_r"] * r_dist, t["lot"] * p["partial_frac"])
                    t["banked"] += usd(p["be_at_r"] * r_dist, t["lot"] * p["partial_frac"])
                    t["lot"] *= (1 - p["partial_frac"])
                    t["partial"] = True
                    t["stop"] = t["entry"]
                if t["partial"]:
                    trail = p["trail_atr"] * t["atr"]
                    if t["dir"] == "BUY":
                        t["stop"] = max(t["stop"], t["entry"] + t["peak"] - trail)
                    else:
                        t["stop"] = min(t["stop"], t["entry"] - t["peak"] + trail)
                hit_stop = (t["dir"] == "BUY" and row["low"] <= t["stop"]) or \
                           (t["dir"] == "SELL" and row["high"] >= t["stop"])
                if hit_stop:
                    exit_price = t["stop"]
                    exit_reason = "Trail" if t["partial"] else "SL"
            else:  # range regime — strict fixed 1:2
                if (t["dir"] == "BUY" and row["low"] <= t["stop"]) or \
                   (t["dir"] == "SELL" and row["high"] >= t["stop"]):
                    exit_price, exit_reason = t["stop"], "SL"
                elif (t["dir"] == "BUY" and row["high"] >= t["tp"]) or \
                     (t["dir"] == "SELL" and row["low"] <= t["tp"]):
                    exit_price, exit_reason = t["tp"], "TP2R"

            if exit_price is None and (i - t["bar"]) >= p["max_hold_bars"]:
                exit_price, exit_reason = row["close"], "TimeExit"

            if exit_price is not None:
                move = (exit_price - t["entry"]) if t["dir"] == "BUY" else (t["entry"] - exit_price)
                leg = usd(move, t["lot"])
                balance += leg
                total = leg + t["banked"]
                trades.append(Trade(t["entry_time"], ts, t["dir"], t["entry"],
                                     exit_price, t["lot0"], move / pip, total,
                                     exit_reason, "CPP"))
                recent_losses = recent_losses + 1 if total <= 0 else 0
                open_t = None
            continue

        # ── look for a new setup ──────────────────────────────────────
        if n_today >= p["max_trades_day"]:
            continue
        hpos = asof_pos(h.index, ts, p["htf_ema"])
        if hpos is None:
            continue
        setup = cpp.detect(row, prev, h.iloc[hpos], p, hour=ts.hour)
        if setup is None:
            continue
        verdict = agent.evaluate(setup, {"symbol": symbol, "pip": pip,
                                         "recent_losses": recent_losses})
        if verdict.decision == "VETO":
            continue
        entry = float(row["close"])
        sl, tp, sl_dist = cpp.sl_tp(setup, entry, p)
        sl_pips = sl_dist / pip
        lot = calc_lot(balance, p["risk_pct"] * verdict.size_mult, sl_pips, pip, symbol)
        if lot <= 0:
            continue
        open_t = {"dir": setup.direction, "entry": entry, "entry_time": ts,
                  "lot": lot, "lot0": lot, "stop": sl, "tp": tp,
                  "sl_dist": sl_dist, "atr": setup.atr, "regime": setup.regime,
                  "peak": 0.0, "partial": False, "banked": 0.0, "bar": i}
        n_today += 1

    return trades


# ── daily-resolution metrics (the measurement the user actually needs) ─
def compute_daily_stats(trades: List[Trade], init_bal: float,
                        tgt_wins=15, tgt_losses=6, dd_limit=6.0) -> dict:
    """Group trades by EXIT day and answer: how many wins/losses per day,
    daily drawdown, and what % of trading days hit the
    >=tgt_wins / <=tgt_losses / <=dd_limit% target."""
    if not trades:
        return {"error": "no trades"}
    by_day: Dict[date, List[Trade]] = {}
    for t in sorted(trades, key=lambda x: x.exit_time):
        by_day.setdefault(t.exit_time.date(), []).append(t)

    rows, hit_days = [], 0
    bal = init_bal
    for d in sorted(by_day):
        day = by_day[d]
        w = sum(1 for t in day if t.pnl_usd > 0)
        l = sum(1 for t in day if t.pnl_usd <= 0)
        day_start = bal
        peak = bal
        max_dd = 0.0
        for t in day:
            bal += t.pnl_usd
            peak = max(peak, bal)
            max_dd = max(max_dd, (peak - bal) / peak * 100)
        intraday_dd = max((day_start - min(
            day_start + sum(x.pnl_usd for x in day[:k + 1])
            for k in range(len(day)))) / day_start * 100, 0.0)
        pnl = bal - day_start
        hit = (w >= tgt_wins and l <= tgt_losses and intraday_dd <= dd_limit)
        if hit:
            hit_days += 1
        rows.append({"date": str(d), "trades": len(day), "wins": w,
                     "losses": l, "win_rate": round(w / len(day) * 100, 1),
                     "pnl": round(pnl, 2), "daily_dd": round(intraday_dd, 2),
                     "hit_target": hit})

    nd = len(rows)
    wins_pd = [r["wins"] for r in rows]
    loss_pd = [r["losses"] for r in rows]
    dd_pd = [r["daily_dd"] for r in rows]
    return {
        "trading_days": nd,
        "target": f">={tgt_wins}W / <={tgt_losses}L / <={dd_limit}%DD",
        "days_hitting_target": hit_days,
        "target_hit_rate_pct": round(hit_days / nd * 100, 1) if nd else 0,
        "avg_trades_day": round(sum(r["trades"] for r in rows) / nd, 1),
        "avg_wins_day": round(sum(wins_pd) / nd, 1),
        "avg_losses_day": round(sum(loss_pd) / nd, 1),
        "median_wins_day": int(np.median(wins_pd)),
        "max_daily_dd_pct": round(max(dd_pd), 2),
        "p90_daily_dd_pct": round(float(np.percentile(dd_pd, 90)), 2),
        "days_over_dd_limit": sum(1 for x in dd_pd if x > dd_limit),
        "days": rows,
    }


def build_daily_html(name: str, stats: dict, daily: dict) -> str:
    if "error" in stats or "error" in daily:
        return f"<h1>{name}</h1><p>No trades generated.</p>"
    drows = "".join(
        f"<tr><td>{d['date']}</td><td>{d['trades']}</td>"
        f"<td style='color:green'>{d['wins']}</td>"
        f"<td style='color:red'>{d['losses']}</td>"
        f"<td>{d['win_rate']}%</td>"
        f"<td style='color:{'green' if d['pnl']>=0 else 'red'}'>${d['pnl']:+.2f}</td>"
        f"<td style='color:{'red' if d['daily_dd']>6 else '#555'}'>{d['daily_dd']}%</td>"
        f"<td>{'✅' if d['hit_target'] else '—'}</td></tr>"
        for d in daily["days"][-120:])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{name} — Daily</title><style>
body{{font-family:Arial;background:#f5f5f5;padding:24px}}
.card{{background:#fff;border-radius:8px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:16px}}
table{{width:100%;border-collapse:collapse}} th{{background:#3949ab;color:#fff;padding:8px;text-align:left}}
td{{padding:6px;border-bottom:1px solid #eee}} h1{{color:#1a237e}}
.k{{display:inline-block;min-width:170px;color:#555}} b{{color:#1a237e}}
</style></head><body>
<h1>{name} — Daily Performance</h1>
<div class="card">
<p><span class="k">Target</span><b>{daily['target']}</b></p>
<p><span class="k">Days hitting target</span><b>{daily['days_hitting_target']}/{daily['trading_days']} ({daily['target_hit_rate_pct']}%)</b></p>
<p><span class="k">Avg trades / day</span><b>{daily['avg_trades_day']}</b></p>
<p><span class="k">Avg wins / day</span><b>{daily['avg_wins_day']}</b> &nbsp; <span class="k">Avg losses / day</span><b>{daily['avg_losses_day']}</b></p>
<p><span class="k">Median wins / day</span><b>{daily['median_wins_day']}</b></p>
<p><span class="k">Max daily DD</span><b>{daily['max_daily_dd_pct']}%</b> &nbsp; <span class="k">p90 daily DD</span><b>{daily['p90_daily_dd_pct']}%</b> &nbsp; <span class="k">days &gt; 6% DD</span><b>{daily['days_over_dd_limit']}</b></p>
<hr><p><span class="k">Total trades</span><b>{stats['total_trades']}</b> &nbsp;
<span class="k">Win rate</span><b>{stats['win_rate']:.1f}%</b> &nbsp;
<span class="k">Profit factor</span><b>{stats['profit_factor']:.2f}</b> &nbsp;
<span class="k">Return</span><b>{stats['net_profit_pct']:+.1f}%</b> &nbsp;
<span class="k">Max DD</span><b>{stats['max_drawdown']:.1f}%</b></p>
</div>
<div class="card"><table>
<tr><th>Date</th><th>Trades</th><th>Wins</th><th>Losses</th><th>WR</th><th>P&amp;L</th><th>Daily DD</th><th>Target</th></tr>
{drows}
</table></div></body></html>"""


CPP_SYMBOLS = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY"]
CPP_PARAMS_FILE = os.path.join(os.path.dirname(__file__), "..", "configs", "cpp_params.json")


def load_cpp_params() -> dict:
    """CPP defaults, optionally overridden by cpp_params.json so the
    backtest→improve→backtest loop tunes params with NO code edits."""
    p = dict(cpp.DEFAULT_PARAMS)
    if os.path.exists(CPP_PARAMS_FILE):
        try:
            ov = json.load(open(CPP_PARAMS_FILE, encoding="utf-8"))
            p.update({k: (tuple(v) if isinstance(v, list) else v)
                      for k, v in ov.items()})
            print(f"  CPP params overridden from {CPP_PARAMS_FILE}: "
                  f"{list(ov.keys())}")
        except Exception as e:
            print(f"  WARN: bad {CPP_PARAMS_FILE} ({e}) — using defaults")
    return p


def run_cpp_sweep():
    """Fast path (python backtest_runner.py --cpp-only): CPP across the 5
    target symbols + a merged portfolio, with daily-resolution metrics and
    the headline 'days hitting 15-20W / <=6L / <=6%DD' number."""
    print("\n" + "=" * 60)
    print(" CPP — Confluence Pullback Portfolio (5-symbol sweep)")
    print(" Period: 2024-01-01 to 2026-05-17  |  $1,000  |  agent=advisory")
    print("=" * 60)
    if not mt5.initialize():
        print("ERROR: MT5 not running. Start MT5 first."); sys.exit(1)

    p = load_cpp_params()
    agent = TradeConfirmationAgent({"mode": "advisory"})

    sym_ov = p.get("per_symbol", {})
    print("\n[1/3] Downloading M15 + H1 for 5 symbols...")
    all_trades: List[Trade] = []
    per_symbol: Dict[str, List[Trade]] = {}
    for sym in CPP_SYMBOLS:
        sp = dict(p)
        for k, v in sym_ov.get(sym, {}).items():
            sp[k] = tuple(v) if isinstance(v, list) else v
        data = {"m15": get_rates(sym, mt5.TIMEFRAME_M15),
                "h1":  get_rates(sym, mt5.TIMEFRAME_H1)}
        tr = backtest_cpp(data, sym, sp, agent)
        per_symbol[sym] = tr
        all_trades.extend(tr)
    mt5.shutdown()

    print("\n[2/3] Building reports...")
    rows = ""
    for sym, tr in per_symbol.items():
        st = compute_stats(tr, INIT_BALANCE)
        dl = compute_daily_stats(tr, INIT_BALANCE)
        fn = f"CPP_{sym}.html"
        with open(os.path.join(REPORT_DIR, fn), "w", encoding="utf-8") as f:
            f.write(build_daily_html(f"CPP — {sym}", st, dl))
        if "error" not in st:
            rows += (f"<tr><td><a href='{fn}'>CPP {sym}</a></td>"
                     f"<td>{st['total_trades']}</td><td>{st['win_rate']:.1f}%</td>"
                     f"<td>{st['profit_factor']:.2f}</td>"
                     f"<td>{dl.get('avg_wins_day','-')}/{dl.get('avg_losses_day','-')}</td>"
                     f"<td>{dl.get('target_hit_rate_pct','-')}%</td>"
                     f"<td>{dl.get('max_daily_dd_pct','-')}%</td>"
                     f"<td>{st['net_profit_pct']:+.1f}%</td></tr>")

    pst = compute_stats(all_trades, INIT_BALANCE)
    pdl = compute_daily_stats(all_trades, INIT_BALANCE)
    with open(os.path.join(REPORT_DIR, "CPP_PORTFOLIO.html"), "w",
              encoding="utf-8") as f:
        f.write(build_daily_html("CPP — PORTFOLIO (5 symbols)", pst, pdl))

    idx = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
           f"<title>CPP Sweep</title><style>body{{font-family:Arial;"
           f"background:#f5f5f5;padding:24px}}table{{width:100%;"
           f"border-collapse:collapse;background:#fff}}th{{background:#3949ab;"
           f"color:#fff;padding:8px}}td{{padding:8px;border-bottom:1px solid "
           f"#eee}}a{{color:#3949ab}}</style></head><body>"
           f"<h1>CPP — Confluence Pullback Portfolio</h1>"
           f"<p><b>Target:</b> {pdl.get('target','-')} &nbsp;|&nbsp; "
           f"<b>PORTFOLIO hit-rate:</b> "
           f"{pdl.get('days_hitting_target','-')}/{pdl.get('trading_days','-')} "
           f"days ({pdl.get('target_hit_rate_pct','-')}%) &nbsp;|&nbsp; "
           f"<a href='CPP_PORTFOLIO.html'>portfolio daily detail »</a></p>"
           f"<table><tr><th>Symbol</th><th>Trades</th><th>WR</th><th>PF</th>"
           f"<th>AvgW/L per day</th><th>Target hit%</th><th>MaxDayDD</th>"
           f"<th>Return</th></tr>{rows}</table></body></html>")
    with open(os.path.join(REPORT_DIR, "cpp_index.html"), "w",
              encoding="utf-8") as f:
        f.write(idx)

    print("\n[3/3] CPP SUMMARY")
    print("  " + "-" * 70)
    for sym, tr in per_symbol.items():
        st = compute_stats(tr, INIT_BALANCE)
        dl = compute_daily_stats(tr, INIT_BALANCE)
        if "error" in st:
            print(f"  {sym:8s} | no trades"); continue
        print(f"  {sym:8s} | {st['total_trades']:4d} tr | WR {st['win_rate']:4.1f}% "
              f"| PF {st['profit_factor']:4.2f} | "
              f"{dl['avg_wins_day']}W/{dl['avg_losses_day']}L per day | "
              f"hit {dl['target_hit_rate_pct']}% | ret {st['net_profit_pct']:+.0f}%")
    print("  " + "-" * 70)
    if "error" not in pdl:
        print(f"  PORTFOLIO (5 sym): {pst['total_trades']} trades | "
              f"WR {pst['win_rate']:.1f}% | PF {pst['profit_factor']:.2f} | "
              f"return {pst['net_profit_pct']:+.1f}%")
        print(f"  Avg/day: {pdl['avg_trades_day']} trades, "
              f"{pdl['avg_wins_day']} wins, {pdl['avg_losses_day']} losses")
        print(f"  Daily DD: max {pdl['max_daily_dd_pct']}%, "
              f"p90 {pdl['p90_daily_dd_pct']}%, "
              f"{pdl['days_over_dd_limit']} days > 6%")
        print(f"  >>> TARGET ({pdl['target']}): hit "
              f"{pdl['days_hitting_target']}/{pdl['trading_days']} days "
              f"= {pdl['target_hit_rate_pct']}% <<<")
    print(f"\n  Reports: {os.path.join(REPORT_DIR, 'cpp_index.html')}\n")


# ══════════════════════════════════════════════════════════════════════
# ICT 2022 MENTORSHIP MODEL BACKTEST
# Fixed pipeline (rolling window, correct sequencing):
#   D1/H4 Bias  →  Kill Zone  →  SSL/BSL Sweep (last 40 bars)
#   →  Unmitigated FVG formed AFTER sweep  →  Retrace tap into FVG
#   →  OTE filter (0.618-0.786)  →  1% risk entry  →  6% DD breaker
# ══════════════════════════════════════════════════════════════════════

def _ict_pnl(symbol: str, lots: float,
             entry: float, exit: float, direction: str) -> float:
    """Gross USD P&L (costs deducted later by compute_stats)."""
    info = mt5.symbol_info(symbol)
    diff = (exit - entry) if direction == "BUY" else (entry - exit)
    if info and info.trade_tick_size > 0:
        return diff / info.trade_tick_size * info.trade_tick_value * lots
    return diff / 0.001 * 0.1 * lots   # XAUUSD fallback


def _ict_daily_bias(d1: pd.DataFrame, h4: pd.DataFrame,
                    as_of: pd.Timestamp, bias_days: int) -> int:
    """Score D1+H4 for direction. +1 bull / -1 bear / 0 neutral (no-trade)."""
    day_start = as_of.normalize()
    d1p = d1[d1.index < day_start]
    h4p = h4[h4.index < as_of]
    if len(d1p) < bias_days + 3 or len(h4p) < 25:
        return 0

    score = 0

    # 1. D1 close vs EQ of last N-day range  (+2 / -2)
    win   = d1p.iloc[-bias_days:]
    eq    = (win["high"].max() + win["low"].min()) / 2
    last  = d1p.iloc[-1]
    if last["close"] > eq:      score += 2
    elif last["close"] < eq:    score -= 2

    # 2. D1 structure: HH+HL vs LH+LL  (+2 / -2 or partial ±1)
    d3 = d1p.iloc[-3:]
    hh = d3["high"].iloc[2] > d3["high"].iloc[1] > d3["high"].iloc[0]
    hl = d3["low"].iloc[2]  > d3["low"].iloc[1]  > d3["low"].iloc[0]
    lh = d3["high"].iloc[2] < d3["high"].iloc[1] < d3["high"].iloc[0]
    ll = d3["low"].iloc[2]  < d3["low"].iloc[1]  < d3["low"].iloc[0]
    if hh and hl:      score += 2
    elif lh and ll:    score -= 2
    elif hh or hl:     score += 1
    elif lh or ll:     score -= 1

    # 3. Recent D1 liquidity sweep  (+1 / -1)
    near_lo = d1p.iloc[-3:-1]["low"].min()
    near_hi = d1p.iloc[-3:-1]["high"].max()
    if last["low"] < near_lo  and last["close"] > near_lo:  score += 1
    if last["high"] > near_hi and last["close"] < near_hi:  score -= 1

    # 4. H4 discount / premium  (+1 / -1)
    h4w  = h4p.iloc[-20:]
    h4eq = (h4w["high"].max() + h4w["low"].min()) / 2
    proxy = last["close"]
    if proxy < h4eq:   score += 1
    elif proxy > h4eq: score -= 1

    if score >= 3:  return  1
    if score <= -3: return -1
    return 0


def _ict_find_recent_sweep(window: pd.DataFrame, bias: int,
                           L: int) -> Tuple[int, float]:
    """Scan `window` for the MOST RECENT liquidity sweep matching bias.
    Swings are built from bars [L, n-6]; sweeps searched from n-6 backwards.
    Stopping 6 bars from the end guarantees ≥5 post-sweep bars for FVGs.
    Returns (sweep_offset_from_start, sweep_level) or (-1, 0.0)."""
    n = len(window)
    if n < L * 2 + 8:
        return -1, 0.0

    hi = window["high"].values
    lo = window["low"].values

    # Reserve last 5 bars for post-sweep FVG/displacement context
    swing_cap = n - 6

    if bias == 1:
        # Swing lows from the full window (excluding last 5 reserved bars)
        swings = [(i, lo[i]) for i in range(L, swing_cap)
                  if lo[i] == lo[max(0, i - L): i + L + 1].min()]
        # Search for the most recent sweep from (n-6) backwards
        for ci in range(swing_cap, L, -1):
            bar = window.iloc[ci]
            for sl_i, sl_p in reversed(swings):
                if sl_i >= ci:
                    continue
                if bar["low"] < sl_p and bar["close"] > sl_p:
                    return ci, sl_p
    else:
        swings = [(i, hi[i]) for i in range(L, swing_cap)
                  if hi[i] == hi[max(0, i - L): i + L + 1].max()]
        for ci in range(swing_cap, L, -1):
            bar = window.iloc[ci]
            for sh_i, sh_p in reversed(swings):
                if sh_i >= ci:
                    continue
                if bar["high"] > sh_p and bar["close"] < sh_p:
                    return ci, sh_p

    return -1, 0.0


def _ict_has_displacement(post_sweep: pd.DataFrame, bias: int) -> bool:
    """Check if any bar in post_sweep is a displacement candle
    (body/range >= 0.40) in the direction of bias.
    Displacement = momentum candle that drove price away from the sweep."""
    for _, bar in post_sweep.iterrows():
        rng = bar["high"] - bar["low"]
        if rng <= 0:
            continue
        if bias == 1 and (bar["close"] - bar["open"]) / rng >= 0.40:
            return True
        if bias == -1 and (bar["open"] - bar["close"]) / rng >= 0.40:
            return True
    return False


def _ict_detect_fvgs(window: pd.DataFrame, min_size: float,
                     bias: int) -> list:
    """Scan `window` (ascending time) for unmitigated FVGs matching bias.
    Center bar i: left=iloc[i-1] (older), right=iloc[i+1] (newer)."""
    n    = len(window)
    fvgs = []
    for i in range(1, n - 1):
        lft = window.iloc[i - 1]
        ctr = window.iloc[i]
        rgt = window.iloc[i + 1]

        if bias == 1:   # Bullish FVG: lft.high < rgt.low, center bullish
            if lft["high"] < rgt["low"] and ctr["close"] > ctr["open"]:
                top, bot = rgt["low"], lft["high"]
                if top - bot >= min_size:
                    # mitigated if any SUBSEQUENT bar's low <= bot
                    if not any(window.iloc[j]["low"] <= bot for j in range(i + 1, n)):
                        fvgs.append({"top": top, "bot": bot,
                                     "ce": (top + bot) / 2, "bullish": True})
        else:           # Bearish FVG: lft.low > rgt.high, center bearish
            if lft["low"] > rgt["high"] and ctr["close"] < ctr["open"]:
                top, bot = lft["low"], rgt["high"]
                if top - bot >= min_size:
                    if not any(window.iloc[j]["high"] >= top for j in range(i + 1, n)):
                        fvgs.append({"top": top, "bot": bot,
                                     "ce": (top + bot) / 2, "bullish": False})
    return fvgs


def _ict_ote_zone(m15_window: pd.DataFrame, bias: int,
                  ote_high: float, ote_low: float) -> Optional[dict]:
    """OTE band from M15 dealing range.
    Long : discount zone [low+0.214r … low+0.382r]  (0.618–0.786 retrace)
    Short: premium zone  [low+0.618r … low+0.786r]"""
    if len(m15_window) < 10:
        return None
    sh  = m15_window["high"].max()
    sl  = m15_window["low"].min()
    rng = sh - sl
    if rng <= 0:
        return None
    eq = sl + rng * 0.5
    if bias == 1:
        return {"eq": eq,
                "bot": sl + rng * (1.0 - ote_low),    # ~0.214
                "top": sl + rng * (1.0 - ote_high)}   # ~0.382
    return {"eq": eq,
            "bot": sl + rng * ote_high,                # ~0.618
            "top": sl + rng * ote_low}                 # ~0.786


def backtest_ict(
    data: dict,
    symbol:              str   = "XAUUSD",
    risk_pct:            float = 1.0,
    swing_len:           int   = 5,
    sweep_lookback:      int   = 40,
    bias_days:           int   = 5,
    ote_high:            float = 0.618,
    ote_low:             float = 0.786,
    min_fvg_pips:        float = 3.0,
    sl_buffer_pips:      float = 3.0,
    tp1_rr:              float = 1.5,
    tp2_rr:              float = 3.0,
    partial_pct:         float = 0.50,
    max_trades_day:      int   = 2,
    max_daily_dd:        float = 6.0,
    use_london_kz:       bool  = True,
    use_ny_kz:           bool  = True,
    require_ote:         bool  = True,
    require_displacement: bool = True,
) -> List[Trade]:
    m5  = data.get("m5",  pd.DataFrame())
    h4  = data.get("h4",  pd.DataFrame())
    d1  = data.get("d1",  pd.DataFrame())
    m15 = data.get("m15", pd.DataFrame())

    if m5.empty or d1.empty or h4.empty:
        print(f"  ICT [{symbol}]: missing data - need m5/h4/d1")
        return []

    pip     = pip_size(symbol)
    min_fvg = min_fvg_pips * pip
    sl_buf  = sl_buffer_pips * pip
    trades: List[Trade] = []
    balance = INIT_BALANCE

    last_day = None; daily_start = balance; daily_count = 0; cb = False

    in_trade = False
    t_dir = ""; t_entry = t_sl = t_tp1 = t_tp2 = t_lots = 0.0
    t_time: Optional[datetime] = None
    t_partial = False

    min_bars = sweep_lookback + swing_len + 10

    for i in range(min_bars, len(m5)):
        ts  = m5.index[i]
        bar = m5.iloc[i]

        # ── day reset ──────────────────────────────────────────────
        today = ts.date()
        if today != last_day:
            last_day    = today
            daily_start = balance
            daily_count = 0
            cb          = False

        # ── manage active trade ────────────────────────────────────
        if in_trade:
            if t_dir == "BUY":
                if bar["low"] <= t_sl:
                    pnl = _ict_pnl(symbol, t_lots, t_entry, t_sl, "BUY")
                    trades.append(Trade(t_time, ts, "BUY", t_entry, t_sl,
                                        t_lots, (t_sl - t_entry) / pip, pnl, "SL", "ICT2022"))
                    balance += pnl; in_trade = False
                    if (daily_start - balance) / daily_start * 100 >= max_daily_dd:
                        cb = True
                    continue
                if not t_partial and bar["high"] >= t_tp1:
                    cv = max(0.01, round(t_lots * partial_pct, 2))
                    if cv < t_lots:
                        balance += _ict_pnl(symbol, cv, t_entry, t_tp1, "BUY")
                        t_lots -= cv; t_sl = t_entry; t_partial = True
                if bar["high"] >= t_tp2:
                    pnl = _ict_pnl(symbol, t_lots, t_entry, t_tp2, "BUY")
                    trades.append(Trade(t_time, ts, "BUY", t_entry, t_tp2,
                                        t_lots, (t_tp2 - t_entry) / pip, pnl, "TP2", "ICT2022"))
                    balance += pnl; in_trade = False
            else:  # SELL
                if bar["high"] >= t_sl:
                    pnl = _ict_pnl(symbol, t_lots, t_entry, t_sl, "SELL")
                    trades.append(Trade(t_time, ts, "SELL", t_entry, t_sl,
                                        t_lots, (t_entry - t_sl) / pip, pnl, "SL", "ICT2022"))
                    balance += pnl; in_trade = False
                    if (daily_start - balance) / daily_start * 100 >= max_daily_dd:
                        cb = True
                    continue
                if not t_partial and bar["low"] <= t_tp1:
                    cv = max(0.01, round(t_lots * partial_pct, 2))
                    if cv < t_lots:
                        balance += _ict_pnl(symbol, cv, t_entry, t_tp1, "SELL")
                        t_lots -= cv; t_sl = t_entry; t_partial = True
                if bar["low"] <= t_tp2:
                    pnl = _ict_pnl(symbol, t_lots, t_entry, t_tp2, "SELL")
                    trades.append(Trade(t_time, ts, "SELL", t_entry, t_tp2,
                                        t_lots, (t_entry - t_tp2) / pip, pnl, "TP2", "ICT2022"))
                    balance += pnl; in_trade = False

        # ── gate checks ────────────────────────────────────────────
        if in_trade or cb or daily_count >= max_trades_day:
            continue

        # ── kill zone (m5 index is UTC) ────────────────────────────
        utc_h = ts.hour + ts.minute / 60.0
        in_kz = (use_london_kz and (7.0 <= utc_h < 10.0 or 15.0 <= utc_h < 17.0)) \
             or (use_ny_kz    and  12.0 <= utc_h < 15.0)
        if not in_kz:
            continue

        # ── daily bias ─────────────────────────────────────────────
        bias = _ict_daily_bias(d1, h4, ts, bias_days)
        if bias == 0:
            continue

        # ── find most-recent liquidity sweep in rolling window ──────
        # Window covers the last sweep_lookback bars (not the current bar)
        sweep_win = m5.iloc[i - sweep_lookback : i]
        sweep_idx, sweep_lvl = _ict_find_recent_sweep(sweep_win, bias, swing_len)
        if sweep_idx < 0:
            continue

        # Absolute bar index of sweep in m5
        abs_sweep = (i - sweep_lookback) + sweep_idx

        # bars that formed AFTER the sweep (where MSS/FVG must appear)
        post_sweep = m5.iloc[abs_sweep + 1 : i]
        if len(post_sweep) < 3:
            continue

        # ── optional displacement check (MSS) ─────────────────────
        if require_displacement and not _ict_has_displacement(post_sweep, bias):
            continue

        # ── FVG detection on post-sweep bars only ──────────────────
        fvgs = _ict_detect_fvgs(post_sweep, min_fvg, bias)
        if not fvgs:
            continue

        # ── OTE zone from M15 ──────────────────────────────────────
        ote = None
        if require_ote and not m15.empty:
            pos = m15.index.searchsorted(ts, side="right") - 1
            if pos >= 30:
                ote = _ict_ote_zone(m15.iloc[pos - 30 : pos], bias, ote_high, ote_low)

        # ── check if current bar taps a valid FVG ──────────────────
        # Rules:
        #   BUY : bar.low must land INSIDE [fvg.bot, fvg.top]  (not blow through)
        #         bar.close > fvg.bot  (gap not fully filled on this bar)
        #   SELL: bar.high must land INSIDE [fvg.bot, fvg.top]
        #         bar.close < fvg.top
        entry_p = None
        fvg_hit = None
        for fvg in reversed(fvgs):   # most recent FVG first
            if bias == 1:  # BUY — retrace into bullish FVG from above
                if not (fvg["bot"] <= bar["low"] <= fvg["top"]):
                    continue   # bar didn't tap inside zone (or blew through)
                if bar["close"] <= fvg["bot"]:
                    continue   # bar closed below FVG = gap filled = invalid
                if ote and not (fvg["ce"] < ote["eq"]
                                and ote["bot"] <= fvg["ce"] <= ote["top"]):
                    continue
                entry_p = fvg["bot"] + (fvg["top"] - fvg["bot"]) * 0.25
                fvg_hit = fvg
            else:  # SELL — retrace into bearish FVG from below
                if not (fvg["bot"] <= bar["high"] <= fvg["top"]):
                    continue
                if bar["close"] >= fvg["top"]:
                    continue   # bar closed above FVG = gap filled = invalid
                if ote and not (fvg["ce"] > ote["eq"]
                                and ote["bot"] <= fvg["ce"] <= ote["top"]):
                    continue
                entry_p = fvg["top"] - (fvg["top"] - fvg["bot"]) * 0.25
                fvg_hit = fvg
            break

        if entry_p is None or fvg_hit is None:
            continue

        # ── SL at FVG invalidation + TP levels ─────────────────────
        # SL just outside the FVG zone (tighter than sweep level on M5)
        # This gives realistic RR when sweep was many bars ago
        if bias == 1:
            sl    = fvg_hit["bot"] - sl_buf
            sld   = entry_p - sl
            if sld <= 0:
                continue
            tp1   = entry_p + sld * tp1_rr
            tp2   = entry_p + sld * tp2_rr
            direc = "BUY"
        else:
            sl    = fvg_hit["top"] + sl_buf
            sld   = sl - entry_p
            if sld <= 0:
                continue
            tp1   = entry_p - sld * tp1_rr
            tp2   = entry_p - sld * tp2_rr
            direc = "SELL"

        if sld <= 0 or abs(tp2 - entry_p) / sld < 1.9:
            continue

        # ── lot size ───────────────────────────────────────────────
        lots = calc_lot(balance, risk_pct, sld / pip, pip, symbol)
        if lots <= 0:
            continue

        # ── open position ──────────────────────────────────────────
        in_trade  = True
        t_dir     = direc
        t_entry   = entry_p
        t_sl      = sl
        t_tp1     = tp1
        t_tp2     = tp2
        t_lots    = lots
        t_time    = ts
        t_partial = False
        daily_count += 1

    # close any open position at end of data
    if in_trade and len(m5) > 0:
        ep  = m5.iloc[-1]["close"]
        pnl = _ict_pnl(symbol, t_lots, t_entry, ep, t_dir)
        pp  = (ep - t_entry) / pip if t_dir == "BUY" else (t_entry - ep) / pip
        trades.append(Trade(t_time, m5.index[-1], t_dir,
                            t_entry, ep, t_lots, pp, pnl, "EOD", "ICT2022"))
        balance += pnl

    print(f"  ICT 2022 [{symbol:8s}]: {len(trades):4d} trades")
    return trades


def run_ict_sweep(symbols: Optional[List[str]] = None):
    """Standalone ICT 2022 backtest across Stage-1 symbols."""
    if symbols is None:
        symbols = ["EURUSD", "GBPUSD", "XAUUSD"]

    if not mt5.initialize():
        print("ERROR: MT5 not running - start MT5 first.")
        return

    print("\n" + "=" * 60)
    print(" ICT 2022 Mentorship Model - Stage 1 Backtest")
    print(f" Symbols: {', '.join(symbols)}")
    print(f" Period : {FROM_DATE.date()} to {TO_DATE.date()}")
    print("=" * 60)

    # Per-symbol parameter overrides (pip sizes differ dramatically)
    # XAUUSD: locked PF 2.11 / DD 12.0% / WR 67.4% (2026-05-20)
    # GBPUSD: DD 15.2% → reduce max_daily_dd to 3% and risk to 0.7%
    # EURUSD: PF 0.97 → wider min_fvg_pips for more significant FVG structures
    _sym_cfg = {
        "EURUSD": dict(min_fvg_pips=2.5, sl_buffer_pips=2.5, risk_pct=0.8,
                       max_daily_dd=3.0),
        "GBPUSD": dict(min_fvg_pips=2.0, sl_buffer_pips=2.0, risk_pct=0.7,
                       max_daily_dd=3.0),
        "XAUUSD": dict(min_fvg_pips=6.0, sl_buffer_pips=6.0),
        "XAGUSD": dict(min_fvg_pips=8.0, sl_buffer_pips=8.0),
        "USDJPY": dict(min_fvg_pips=2.0, sl_buffer_pips=2.0),
    }

    per_symbol: Dict[str, List[Trade]] = {}
    for sym in symbols:
        print(f"\n  Downloading {sym}...")
        d = {
            "m5":  get_rates(sym, mt5.TIMEFRAME_M5,  days_back=900),
            "m15": get_rates(sym, mt5.TIMEFRAME_M15, days_back=900),
            "h4":  get_rates(sym, mt5.TIMEFRAME_H4,  days_back=900),
            "d1":  get_rates(sym, mt5.TIMEFRAME_D1,  days_back=900),
        }
        cfg = _sym_cfg.get(sym, {})
        per_symbol[sym] = backtest_ict(
            d, symbol=sym,
            sweep_lookback=60,      # wider window to find older sweeps
            require_ote=False,      # OTE band too tight on M5/M15 alone
            require_displacement=True,
            **cfg,
        )

    mt5.shutdown()

    print("\n  -- ICT 2022 RESULTS ------------------------------------------")
    hdr = f"  {'Symbol':<10} {'Trades':>7} {'WR':>7} {'PF':>7} {'Return':>9} {'DD':>7}"
    print(hdr); print("  " + "-" * 50)
    for sym, tr in per_symbol.items():
        st = compute_stats(tr, INIT_BALANCE, sym)
        if "error" in st:
            print(f"  {sym:<10} - no trades"); continue
        sign = "+" if st["net_profit"] >= 0 else ""
        print(f"  {sym:<10} {st['total_trades']:>7} "
              f"{st['win_rate']:>6.1f}% {st['profit_factor']:>7.2f} "
              f"{sign}{st['net_profit_pct']:>7.1f}% {st['max_drawdown']:>6.1f}%")

    print("\n  Generating HTML reports...")
    os.makedirs(REPORT_DIR, exist_ok=True)
    for sym, tr in per_symbol.items():
        st    = compute_stats(tr, INIT_BALANCE, sym)
        fname = f"ICT_2022_{sym}.html"
        fpath = os.path.join(REPORT_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(build_html(f"ICT 2022 — {sym}", st, tr))
        print(f"  Saved: {fpath}")

    print(f"\n  Open: {REPORT_DIR}\\ICT_2022_EURUSD.html")


def run_ict_walkforward(symbols: Optional[List[str]] = None,
                        split_date: str = "2025-01-01"):
    """Walk-forward validation for ICT 2022 EA.

    Splits data at split_date:
      In-sample    : FROM_DATE .. split_date   (parameter freeze on this)
      Out-of-sample: split_date .. TO_DATE     (blind forward test)

    Pass condition per symbol:
      - OOS PF >= 0.80 * in-sample PF
      - OOS PF >= 1.3
      - OOS DD <= 12%

    Passing symbols are promoted to mql5_experts/ready_ea/.
    Results saved to backtest_reports/ict_wf_results.json for dashboard.
    """
    import shutil

    if symbols is None:
        symbols = ["XAUUSD", "GBPUSD", "EURUSD"]

    split_dt = datetime.strptime(split_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if not mt5.initialize():
        print("ERROR: MT5 not running - start MT5 first.")
        return {}

    print("\n" + "=" * 62)
    print(" ICT 2022 Mentorship Model - Walk-Forward Validation")
    print(f" In-sample   : {FROM_DATE.date()} to {split_dt.date()}")
    print(f" Out-of-sample: {split_dt.date()} to {TO_DATE.date()}")
    print("=" * 62)

    _sym_cfg = {
        "EURUSD": dict(min_fvg_pips=2.5, sl_buffer_pips=2.5, risk_pct=0.8,
                       max_daily_dd=3.0),
        "GBPUSD": dict(min_fvg_pips=2.0, sl_buffer_pips=2.0, risk_pct=0.7,
                       max_daily_dd=3.0),
        "XAUUSD": dict(min_fvg_pips=6.0, sl_buffer_pips=6.0),
    }

    all_results = {}
    promoted    = []

    for sym in symbols:
        print(f"\n  Downloading {sym}...")
        d_full = {
            "m5":  get_rates(sym, mt5.TIMEFRAME_M5,  days_back=900),
            "m15": get_rates(sym, mt5.TIMEFRAME_M15, days_back=900),
            "h4":  get_rates(sym, mt5.TIMEFRAME_H4,  days_back=900),
            "d1":  get_rates(sym, mt5.TIMEFRAME_D1,  days_back=900),
        }

        def _split(df):
            # Date-based split; fall back to 40/60 fraction if in-sample
            # is empty (can happen when broker H4/D1 history is shallow)
            ins = df[df.index < split_dt]
            oos = df[df.index >= split_dt]
            if ins.empty and not df.empty:
                cut = int(len(df) * 0.40)
                ins, oos = df.iloc[:cut], df.iloc[cut:]
            return ins, oos

        d_in  = {k: _split(v)[0] for k, v in d_full.items()}
        d_oos = {k: _split(v)[1] for k, v in d_full.items()}

        cfg = _sym_cfg.get(sym, {})
        kwargs = dict(symbol=sym, sweep_lookback=60,
                      require_ote=False, require_displacement=True, **cfg)

        print(f"    Running in-sample  ({FROM_DATE.date()} - {split_dt.date()})...")
        tr_in  = backtest_ict(d_in,  **kwargs)
        print(f"    Running out-of-sample ({split_dt.date()} - {TO_DATE.date()})...")
        tr_oos = backtest_ict(d_oos, **kwargs)

        st_in  = compute_stats(tr_in,  INIT_BALANCE, sym)
        st_oos = compute_stats(tr_oos, INIT_BALANCE, sym)

        pf_in  = st_in.get("profit_factor",  0.0)
        pf_oos = st_oos.get("profit_factor", 0.0)
        dd_in  = st_in.get("max_drawdown",   999.0)
        dd_oos = st_oos.get("max_drawdown",  999.0)
        n_in   = st_in.get("total_trades",   0)
        n_oos  = st_oos.get("total_trades",  0)
        wr_in  = st_in.get("win_rate",       0.0)
        wr_oos = st_oos.get("win_rate",       0.0)
        ret_in  = st_in.get("net_profit_pct",  0.0)
        ret_oos = st_oos.get("net_profit_pct", 0.0)

        degrade = (pf_oos / pf_in) if pf_in > 0 else 0.0
        passed  = degrade >= 0.80 and pf_oos >= 1.3 and dd_oos <= 12.0

        all_results[sym] = {
            "in_sample":     {"pf": round(pf_in, 3),  "dd": round(dd_in, 2),
                              "wr": round(wr_in, 1),  "trades": n_in,
                              "ret_pct": round(ret_in, 1)},
            "out_of_sample": {"pf": round(pf_oos, 3), "dd": round(dd_oos, 2),
                              "wr": round(wr_oos, 1), "trades": n_oos,
                              "ret_pct": round(ret_oos, 1)},
            "degradation_pct": round(degrade * 100, 1),
            "passed":          passed,
        }

        if passed:
            promoted.append(sym)

    mt5.shutdown()

    # ── print results table ────────────────────────────────────────────
    print("\n  -- WALK-FORWARD RESULTS ----------------------------------------")
    print(f"  {'Symbol':<8} {'IS PF':>7} {'OOS PF':>7} {'Degrade':>8} "
          f"{'IS DD':>7} {'OOS DD':>7} {'Verdict':>8}")
    print("  " + "-" * 60)
    for sym, r in all_results.items():
        verdict = "PASS" if r["passed"] else "FAIL"
        print(f"  {sym:<8} "
              f"{r['in_sample']['pf']:>7.2f} "
              f"{r['out_of_sample']['pf']:>7.2f} "
              f"{r['degradation_pct']:>7.1f}% "
              f"{r['in_sample']['dd']:>6.1f}% "
              f"{r['out_of_sample']['dd']:>6.1f}% "
              f"{verdict:>8}")

    # ── promote to ready_ea ────────────────────────────────────────────
    src_ea = os.path.join(os.path.dirname(__file__),
                          "mql5_experts", "ict", "ICT_2022_EA.mq5")
    ready_dir = os.path.join(os.path.dirname(__file__),
                             "mql5_experts", "ready_ea")
    os.makedirs(ready_dir, exist_ok=True)
    print()
    for sym in promoted:
        dest = os.path.join(ready_dir, f"ICT_2022_{sym}.mq5")
        if os.path.exists(src_ea):
            shutil.copy2(src_ea, dest)
            print(f"  PROMOTED: mql5_experts/ready_ea/ICT_2022_{sym}.mq5")
        else:
            print(f"  WARNING: source EA not found at {src_ea}")

    if not promoted:
        print("  No symbols passed walk-forward — nothing promoted.")

    # ── save JSON for dashboard ────────────────────────────────────────
    os.makedirs(REPORT_DIR, exist_ok=True)
    payload = {
        "generated_at":  datetime.utcnow().isoformat() + "Z",
        "in_sample_end": split_date,
        "symbols":       all_results,
        "promoted":      promoted,
    }
    json_path = os.path.join(REPORT_DIR, "ict_wf_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  Results saved: {json_path}")
    print(f"  Dashboard API: GET /api/ict/results\n")

    return all_results


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
def main():
    if "--ict-only" in sys.argv:
        run_ict_sweep()
        return

    if "--ict-wf" in sys.argv:
        run_ict_walkforward()
        return

    if "--cpp-only" in sys.argv:
        run_cpp_sweep()
        return

    print("\n" + "="*60)
    print(" FxVault Backtest Runner — All 6 Strategies")
    print(" Period: 2024-01-01 to 2026-05-17")
    print("="*60)

    if not mt5.initialize():
        print("ERROR: MT5 not running. Start MT5 first.")
        sys.exit(1)

    print("\n[1/3] Downloading historical data...")
    xau_data = {
        "m1":  get_rates("XAUUSD", mt5.TIMEFRAME_M1),
        "m5":  get_rates("XAUUSD", mt5.TIMEFRAME_M5),
        "m15": get_rates("XAUUSD", mt5.TIMEFRAME_M15),
        "h1":  get_rates("XAUUSD", mt5.TIMEFRAME_H1),
        "h4":  get_rates("XAUUSD", mt5.TIMEFRAME_H4),
    }

    # S4 pairs
    multi_data = {"XAUUSD": xau_data}
    for sym in ["XAGUSD", "USDJPY", "GBPUSD", "EURUSD"]:
        multi_data[sym] = {
            "m1": get_rates(sym, mt5.TIMEFRAME_M1),
            "m5": get_rates(sym, mt5.TIMEFRAME_M5),
            "h1": get_rates(sym, mt5.TIMEFRAME_H1),
        }

    print("\n[2/3] Running backtests...")
    results = {
        "S1 — Swing Scalp":      backtest_s1(xau_data),
        "S2 — M5 Scalp":         backtest_s2(xau_data),
        "S3 — M1 HFT Sniper":    backtest_s3(xau_data),
        "S4 — Multi-Pair":       backtest_s4(multi_data),
        "S5 — News Spike":       backtest_s5(xau_data),
        "S6 — Asian Range":      backtest_s6(xau_data),
        # ── v2 improved ──────────────────────────────────────────────
        "S1v2 — Swing Scalp":    backtest_s1_v2(xau_data),
        "S2v2 — M5 Scalp":       backtest_s2_v2(xau_data),
        "S6v2 — Asian Range":    backtest_s6_v2(xau_data),
    }

    mt5.shutdown()

    print("\n[3/3] Generating HTML reports...")
    summary_rows = ""
    for name, trades in results.items():
        stats = compute_stats(trades, INIT_BALANCE)
        fname = name.split("—")[0].strip().replace(" ", "_") + ".html"
        fpath = os.path.join(REPORT_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(build_html(name, stats, trades))
        print(f"  Saved: {fpath}")

        if "error" not in stats:
            color = "green" if stats["net_profit"] >= 0 else "red"
            sign  = "+" if stats["net_profit"] >= 0 else ""
            summary_rows += f"""
            <tr>
              <td><a href="{fname}">{name}</a></td>
              <td>{stats['total_trades']}</td>
              <td>{stats['win_rate']:.1f}%</td>
              <td>{stats['profit_factor']:.2f}</td>
              <td style='color:{color}'>{sign}{stats['net_profit_pct']:.1f}%</td>
              <td style='color:red'>{stats['max_drawdown']:.1f}%</td>
              <td style='color:{color}'>${stats['net_profit']:+.2f}</td>
            </tr>"""

    # combined summary page
    idx_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FxVault Backtest Summary</title>
<style>
  body{{font-family:Arial,sans-serif;background:#f5f5f5;padding:30px}}
  h1{{color:#1a237e}} h2{{color:#283593}}
  .card{{background:#fff;border-radius:8px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
  table{{width:100%;border-collapse:collapse}}
  th{{background:#3949ab;color:#fff;padding:10px;text-align:left}}
  td{{padding:10px;border-bottom:1px solid #eee}} tr:hover{{background:#f0f4ff}}
  a{{color:#3949ab;text-decoration:none}} a:hover{{text-decoration:underline}}
</style></head><body>
<h1>FxVault — Backtest Summary Report</h1>
<p>Period: 2024-01-01 to 2026-05-17 &nbsp;|&nbsp; Initial Balance: $1,000 &nbsp;|&nbsp; Symbol: XAUUSD (+ 4 pairs for S4)</p>
<div class="card">
<table>
  <tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>Profit Factor</th><th>Return</th><th>Max DD</th><th>Net Profit</th></tr>
  {summary_rows}
</table>
</div>
</body></html>"""

    idx_path = os.path.join(REPORT_DIR, "index.html")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(idx_html)

    print(f"\n{'='*60}")
    print(f" All reports saved to: {REPORT_DIR}")
    print(f" Open: {idx_path}")
    print(f"{'='*60}\n")

    # print quick summary to console
    v1_names = ["S1 — Swing Scalp", "S2 — M5 Scalp", "S3 — M1 HFT Sniper",
                "S4 — Multi-Pair", "S5 — News Spike", "S6 — Asian Range"]
    v2_names = ["S1v2 — Swing Scalp", "S2v2 — M5 Scalp", "S6v2 — Asian Range"]
    pair_map = {"S1v2 — Swing Scalp": "S1 — Swing Scalp",
                "S2v2 — M5 Scalp":    "S2 — M5 Scalp",
                "S6v2 — Asian Range": "S6 — Asian Range"}

    print("\n  -- V1 BASELINE ----------------------------------------------")
    for name in v1_names:
        trades = results[name]
        stats  = compute_stats(trades, INIT_BALANCE)
        if "error" in stats:
            print(f"  {name:30s} - No trades")
        else:
            print(f"  {name:30s} | {stats['total_trades']:5d} trades | "
                  f"WR {stats['win_rate']:5.1f}% | PF {stats['profit_factor']:5.2f} | "
                  f"Return {stats['net_profit_pct']:+7.1f}% | DD {stats['max_drawdown']:5.1f}%")

    print("\n  -- V2 IMPROVED (S1, S2, S6) -- BEFORE vs AFTER ----------------")
    hdr = f"  {'Strategy':<22} {'Trades':>7} {'WR':>7} {'PF':>7} {'Return':>9} {'DD':>7}"
    print(hdr)
    print("  " + "-"*62)
    for v2n in v2_names:
        v1n = pair_map[v2n]
        s1  = compute_stats(results[v1n], INIT_BALANCE)
        s2  = compute_stats(results[v2n], INIT_BALANCE)
        tag = v2n.split(" — ")[0]
        def row(s, lbl):
            if "error" in s:
                return f"  {lbl:<22} {'N/A':>7}"
            ret_sign = "+" if s["net_profit"] >= 0 else ""
            return (f"  {lbl:<22} {s['total_trades']:>7} "
                    f"{s['win_rate']:>6.1f}% {s['profit_factor']:>7.2f} "
                    f"{ret_sign}{s['net_profit_pct']:>7.1f}% {s['max_drawdown']:>6.1f}%")
        print(row(s1, f"{tag} v1"))
        print(row(s2, f"{tag} v2  ^ improved"))
        delta_ret = s2.get("net_profit_pct", 0) - s1.get("net_profit_pct", 0)
        delta_pf  = s2.get("profit_factor",  0) - s1.get("profit_factor",  0)
        print(f"  {'':22} {'delta':>7} {'':>7} {delta_pf:>+7.2f} {delta_ret:>+8.1f}%")
        print("  " + "-"*62)


if __name__ == "__main__":
    main()
