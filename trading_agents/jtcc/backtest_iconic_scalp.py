"""Iconic Scalp Backtest — M15 setup TF, 2R/3R targets.

Improvements over v1:
  - Partial exit at 1R (50% close, stop → breakeven) — reduces SL rate effect
  - Compact-spot filter (risk > 1.5×ATR → skip) — kills wide-zone bad-RR setups
  - Purpose window widened to 90 min (engine_scalp.py) — +30-40% more signals
  - NZDUSD added; USDCAD removed (NO_GO on M15 scalp)
  - --type1-only flag (Type 1 setups only — cleaner directional break)
  - --compact flag (max 1.5×ATR risk filter)

Run:
  python -m trading_agents.jtcc.backtest_iconic_scalp
  python -m trading_agents.jtcc.backtest_iconic_scalp --symbols EURUSD GBPUSD
  python -m trading_agents.jtcc.backtest_iconic_scalp --no-volume
  python -m trading_agents.jtcc.backtest_iconic_scalp --compact --type1-only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("iconic.scalp_backtest")

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
REPORT_FILE = BASE_DIR / "logs" / "jtcc" / "_backtest_iconic_scalp.json"

DEFAULT_SYMBOLS = [
    "EURUSD",   # GO  — M15 scalp PF 1.80
    "GBPUSD",   # GO  — M15 scalp PF 1.57
    "USDCHF",   # GO  — M15 scalp PF 1.45
    "AUDUSD",   # MARGINAL — include for re-test with improvements
    "NZDUSD",   # NEW — NZD tends to move with AUD; test independently
    # USDCAD removed: NO_GO on M15 (16.7% WR) — works on H1 swing only
]

TYPICAL_SPREADS = {
    "EURUSD": 0.00008, "GBPUSD": 0.0001,  "USDJPY": 0.008,
    "AUDUSD": 0.0001,  "NZDUSD": 0.0001,  "USDCAD": 0.00012,
    "USDCHF": 0.0001,
}

SIGNAL_EXPIRY_BARS  = 8      # M15 bars before cancelling unfilled entry (~2 hours)
MAX_HOLD_BARS       = 64     # force-close after ~16 hours (safety)
GO_MIN_PF           = 1.3
GO_MIN_TRADES       = 10
MAX_SPOT_ATR_MULT   = 1.5    # compact filter: skip signals where risk > this × ATR
# Partial exit: beneficial when many trades reach 1R then reverse; hurts clean TP trades.
# Use --partial flag to enable; off by default for clean baseline.


# ── MT5 fetch ─────────────────────────────────────────────────────────────────
def _init_mt5():
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        return mt5
    except Exception:
        return None

_mt5 = _init_mt5()
_TF  = {}
if _mt5:
    _TF = {
        "M1":  _mt5.TIMEFRAME_M1,  "M3":  _mt5.TIMEFRAME_M3,
        "M5":  _mt5.TIMEFRAME_M5,  "M15": _mt5.TIMEFRAME_M15,
        "H1":  _mt5.TIMEFRAME_H1,  "H4":  _mt5.TIMEFRAME_H4,
    }


def _fetch(symbol: str, tf: str, limit: int) -> Optional[pd.DataFrame]:
    if _mt5 and _TF.get(tf):
        rates = _mt5.copy_rates_from_pos(symbol, _TF[tf], 0, limit)
        if rates is not None and len(rates):
            df = pd.DataFrame(rates)
            if "tick_volume" not in df.columns and "volume" in df.columns:
                df["tick_volume"] = df["volume"]
            df["ema200"] = df["close"].ewm(alpha=1/200, adjust=False).mean()
            return df
    url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{url}/bars/{symbol}",
                         params={"timeframe": tf, "limit": limit}, timeout=60)
        r.raise_for_status()
        d = r.json()
        df = pd.DataFrame({k: v for k, v in d.items() if isinstance(v, list)})
        if "tick_volume" not in df.columns and "volume" in df.columns:
            df["tick_volume"] = df["volume"]
        if df.empty or "close" not in df.columns:
            return None
        df["ema200"] = df["close"].ewm(alpha=1/200, adjust=False).mean()
        return df
    except Exception as e:
        log.warning("fetch %s %s: %s", symbol, tf, e)
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _align(df: pd.DataFrame) -> str:
    if len(df) < 200:
        return "none"
    r = df.iloc[-1]
    if r["close"] > r["ema200"]: return "bull"
    if r["close"] < r["ema200"]: return "bear"
    return "none"


def _find_idx(times: list, target) -> int:
    lo, hi = 0, len(times)
    while lo < hi:
        m = (lo + hi) // 2
        if times[m] <= target: lo = m + 1
        else: hi = m
    return lo - 1


def _currency_strength(align_map: dict) -> dict:
    raw: dict = {}
    for sym, al in align_map.items():
        s = sym.upper().replace("/", "")
        if len(s) == 6 and s.isalpha():
            base, quote = s[:3], s[3:]
        else:
            continue
        b, q = (1, -1) if al == "bull" else ((-1, 1) if al == "bear" else (0, 0))
        raw.setdefault(base, []).append(b)
        raw.setdefault(quote, []).append(q)
    return {c: round((sum(v)/len(v)+1)*5, 1) for c, v in raw.items() if v}


# ── Single-symbol backtest ────────────────────────────────────────────────────
def backtest_scalp(symbol: str, m15: pd.DataFrame, h1: pd.DataFrame,
                   all_h1: dict, no_volume: bool,
                   compact: bool = False, type1_only: bool = False,
                   partial: bool = False) -> dict:
    from trading_agents.iconic.engine_scalp import IconicScalpEngine, SCALP_SETUP_TF
    from trading_agents.iconic.engine_scalp import SCALP_RR_B, SCALP_MIN_RR
    from trading_agents.iconic.pattern import detect_setup, atr as _compute_atr
    from trading_agents.iconic.engine import IconicTradeSignal

    engine = IconicScalpEngine()
    spread = TYPICAL_SPREADS.get(symbol, 0.0001)

    times  = m15["time"].tolist()
    highs  = m15["high"].tolist()
    lows   = m15["low"].tolist()
    closes = m15["close"].tolist()
    n      = len(times)

    h1_times = h1["time"].tolist() if h1 is not None and "time" in h1.columns else []
    other_h1_times = {s: df["time"].tolist()
                      for s, df in all_h1.items()
                      if s != symbol and "time" in df.columns}

    start_i = 250
    end_i   = n - 1

    trades: list[dict] = []
    position: Optional[dict] = None
    pending:  Optional[dict] = None

    for i in range(start_i, end_i):
        t  = times[i]
        nh = highs[i]
        nl = lows[i]

        # 1. Manage open position
        if position is not None:
            side   = position["side"]
            entry  = position["entry"]
            risk_d = position["risk_dist"]

            # Partial exit at 1R: close 50%, move stop to breakeven
            if partial and not position["partial_done"]:
                if side == "BUY"  and nh >= entry + risk_d:
                    position["partial_done"] = True
                    position["partial_pnl"]  = risk_d - spread
                    position["sl"]           = entry        # breakeven
                elif side == "SELL" and nl <= entry - risk_d:
                    position["partial_done"] = True
                    position["partial_pnl"]  = risk_d - spread
                    position["sl"]           = entry        # breakeven

            hit_sl  = (nl <= position["sl"])  if side == "BUY"  else (nh >= position["sl"])
            hit_tp  = (nh >= position["tp"])  if side == "BUY"  else (nl <= position["tp"])
            timeout = (i - position["bar_i"]) >= MAX_HOLD_BARS

            if hit_sl or hit_tp or timeout:
                if hit_sl:
                    raw_pnl = position["sl"] - entry if side == "BUY" \
                              else entry - position["sl"]
                    tag = "SL"
                elif hit_tp:
                    raw_pnl = position["tp"] - entry if side == "BUY" \
                              else entry - position["tp"]
                    tag = "TP"
                else:
                    raw_pnl = closes[i] - entry if side == "BUY" \
                              else entry - closes[i]
                    tag = "TIMEOUT"

                partial_pnl = position["partial_pnl"]
                if partial_pnl:
                    # 50% closed at 1R already; 50% closes now
                    full_pnl = 0.5 * partial_pnl + 0.5 * (raw_pnl - spread)
                else:
                    full_pnl = raw_pnl - spread

                trades.append({
                    "pnl":       round(full_pnl, 8),
                    "exit":      tag,
                    "bars_held": i - position["bar_i"],
                    "klass":     position["klass"],
                    "partial":   bool(partial_pnl),
                })
                position = None

        # 2. Try fill pending
        if pending is not None and position is None:
            if i - pending["signal_bar"] > SIGNAL_EXPIRY_BARS:
                pending = None
            else:
                sig = pending["signal"]
                if sig.side == "BUY" and nh >= sig.entry:
                    position = {
                        "side": "BUY", "entry": sig.entry + spread,
                        "sl": sig.stop, "tp": sig.tp_final,
                        "risk_dist": sig.risk, "bar_i": i,
                        "klass": sig.klass,
                        "partial_done": False, "partial_pnl": 0.0,
                    }
                    pending = None
                elif sig.side == "SELL" and nl <= sig.entry:
                    position = {
                        "side": "SELL", "entry": sig.entry - spread,
                        "sl": sig.stop, "tp": sig.tp_final,
                        "risk_dist": sig.risk, "bar_i": i,
                        "klass": sig.klass,
                        "partial_done": False, "partial_pnl": 0.0,
                    }
                    pending = None

        # 3. Scan for signal
        if position is None and pending is None:
            m15_sl = m15.iloc[:i + 1]

            # H1 context for alignment
            h1_align = "none"
            if h1_times:
                hi1 = _find_idx(h1_times, t)
                if hi1 >= 200:
                    h1_align = _align(h1.iloc[:hi1 + 1])

            align = _align(m15_sl)
            if h1_align != "none":
                align = h1_align

            align_map = {symbol: align}
            for s2, ot in other_h1_times.items():
                oi = _find_idx(ot, t)
                if oi >= 200:
                    align_map[s2] = _align(all_h1[s2].iloc[:oi + 1])
            strength = _currency_strength(align_map)

            snap = {"align": align, "tfs": {
                SCALP_SETUP_TF: m15_sl,
                "M3": m15_sl,
                "H1": h1.iloc[:_find_idx(h1_times, t)+1]
                      if h1_times and _find_idx(h1_times, t) >= 50 else m15_sl,
            }}

            try:
                now_dt = datetime.fromtimestamp(float(t), tz=timezone.utc)

                if no_volume:
                    side = "BUY" if align == "bull" else ("SELL" if align == "bear" else None)
                    if side is None:
                        continue
                    setup = detect_setup(m15_sl, side, symbol=symbol)
                    if not setup.valid or setup.entry is None or setup.stop is None:
                        continue
                    entry, stop = float(setup.entry), float(setup.stop)
                    risk = abs(entry - stop)
                    if risk <= 0:
                        continue
                    tp_final = (entry + SCALP_RR_B * risk) if side == "BUY" \
                               else (entry - SCALP_RR_B * risk)
                    if abs(tp_final - entry) / risk < SCALP_MIN_RR:
                        continue
                    sigs = [IconicTradeSignal(
                        symbol=symbol, side=side, klass="B", type=setup.type or "type1",
                        entry=round(entry, 6), stop=round(stop, 6),
                        tp_final=round(tp_final, 6), tp_scale=[], risk=round(risk, 6),
                        rr_final=round(abs(tp_final-entry)/risk, 2),
                        score=50.0, is_leader=False, volume_dead=False,
                        reasons=["[ablation] pattern-only scalp"],
                    )]
                else:
                    sigs = engine.evaluate({symbol: snap}, strength, now=now_dt)

            except Exception as e:
                log.debug("evaluate %s bar %d: %s", symbol, i, e)
                continue

            if sigs:
                sig = sigs[0]

                # Type 1 only filter: skip messier Type 2 setups
                if type1_only and sig.type != "type1":
                    continue

                # Compact filter: skip if risk > MAX_SPOT_ATR_MULT × current ATR
                if compact:
                    cur_atr = _compute_atr(m15_sl)
                    if cur_atr > 0 and sig.risk > MAX_SPOT_ATR_MULT * cur_atr:
                        continue

                pending = {"signal": sig, "signal_bar": i}

    return _summarize(symbol, trades, end_i - start_i)


# ── Summary ───────────────────────────────────────────────────────────────────
def _summarize(symbol: str, trades: list[dict], bars_tested: int) -> dict:
    if not trades:
        return {"symbol": symbol, "trades": 0, "bars_tested": bars_tested,
                "verdict": "NO_TRADES"}
    pnls   = [t["pnl"] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses)) if losses else 1e-9
    pf = round(gp / gl, 2)
    wr = round(len(wins) / len(pnls) * 100, 1)
    cum, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    tp_exits      = sum(1 for t in trades if t["exit"] == "TP")
    sl_exits      = sum(1 for t in trades if t["exit"] == "SL")
    timeout_exits = sum(1 for t in trades if t["exit"] == "TIMEOUT")
    partial_count = sum(1 for t in trades if t.get("partial"))
    if len(pnls) < GO_MIN_TRADES: verdict = "INSUFFICIENT"
    elif pf >= GO_MIN_PF:         verdict = "GO"
    elif pf >= 1.0:               verdict = "MARGINAL"
    else:                         verdict = "NO_GO"
    return {
        "symbol": symbol, "trades": len(pnls), "wins": len(wins),
        "win_rate_pct": wr, "profit_factor": pf,
        "total_pnl": round(sum(pnls), 8),
        "max_drawdown": round(mdd, 8),
        "tp_exits": tp_exits, "sl_exits": sl_exits,
        "timeout_exits": timeout_exits,
        "partial_exits_triggered": partial_count,
        "tp_rate_pct": round(tp_exits / len(pnls) * 100, 1),
        "avg_hold_bars": round(sum(t.get("bars_held", 0) for t in trades) / len(trades), 1),
        "bars_tested": bars_tested, "verdict": verdict,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols",    nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--limit",      type=int,  default=5000)
    ap.add_argument("--no-volume",  action="store_true")
    ap.add_argument("--compact",    action="store_true",
                    help=f"Skip signals where risk > {MAX_SPOT_ATR_MULT}x ATR")
    ap.add_argument("--type1-only", action="store_true",
                    help="Only take Type 1 setups (cleaner directional break)")
    ap.add_argument("--partial",    action="store_true",
                    help="50pct close at 1R + move stop to breakeven (good for high-reversal symbols)")
    args = ap.parse_args()

    flags = []
    if args.no_volume:  flags.append("NO-VOLUME ABLATION")
    if args.compact:    flags.append(f"compact<={MAX_SPOT_ATR_MULT}xATR")
    if args.type1_only: flags.append("type1-only")
    if args.partial:    flags.append("partial@1R")
    mode = " | ".join(flags) if flags else "FULL (with volume gate)"

    log.info("Iconic Scalp backtest [%s] — %d symbols, M15 limit=%d",
             mode, len(args.symbols), args.limit)

    m15_data: dict[str, pd.DataFrame] = {}
    h1_data:  dict[str, pd.DataFrame] = {}

    for sym in args.symbols:
        log.info("Fetching %s...", sym)
        m15 = _fetch(sym, "M15", args.limit)
        h1  = _fetch(sym, "H1",  args.limit)
        if m15 is None or len(m15) < 300:
            log.info("  %s: insufficient M15 data — skipping", sym)
            continue
        if h1 is None or len(h1) < 200:
            h1 = m15
        m15_data[sym] = m15
        h1_data[sym]  = h1
        log.info("  M15: %d bars  H1: %d bars", len(m15), len(h1))

    if not m15_data:
        log.error("No usable symbols.")
        sys.exit(1)

    report = {"mode": mode, "results": []}
    W = 115
    print(f"\nIconic Scalp Backtest [{mode}]")
    print("=" * W)
    print(f"{'Symbol':<10s} {'Trades':>7s} {'WR%':>6s} {'PF':>6s} "
          f"{'MaxDD':>12s} {'TP%':>6s} {'Partial':>8s} {'AvgHold':>8s} {'Verdict':>12s}")
    print("-" * W)

    for sym in sorted(m15_data):
        t0 = _time.time()
        r = backtest_scalp(
            sym, m15_data[sym], h1_data.get(sym, m15_data[sym]),
            h1_data, args.no_volume,
            compact=args.compact, type1_only=args.type1_only,
            partial=args.partial,
        )
        r["runtime_s"] = round(_time.time() - t0, 1)
        report["results"].append(r)
        tr = r.get("trades", 0)
        if tr == 0:
            print(f"{sym:<10s} {'0':>7s} {'-':>6s} {'-':>6s} {'-':>12s} "
                  f"{'-':>6s} {'-':>8s} {'-':>8s} {r.get('verdict','?'):>12s}")
        else:
            partial_pct = round(r.get("partial_exits_triggered", 0) / tr * 100, 0)
            print(f"{sym:<10s} {tr:>7d} {r['win_rate_pct']:>6.1f} "
                  f"{r['profit_factor']:>6.2f} {r['max_drawdown']:>12.6f} "
                  f"{r['tp_rate_pct']:>5.1f}% {partial_pct:>7.0f}% "
                  f"{r['avg_hold_bars']:>8.1f} {r.get('verdict','?'):>12s}")

    print("\n" + "=" * W)
    go   = [r["symbol"] for r in report["results"] if r.get("verdict") == "GO"]
    marg = [r["symbol"] for r in report["results"] if r.get("verdict") == "MARGINAL"]
    nogo = [r["symbol"] for r in report["results"] if r.get("verdict") == "NO_GO"]
    insuf= [r["symbol"] for r in report["results"]
            if r.get("verdict") in ("INSUFFICIENT", "NO_TRADES")]
    if go:   print(f"GO       ({len(go):2d}): {go}")
    if marg: print(f"MARGINAL ({len(marg):2d}): {marg}")
    if nogo: print(f"NO_GO    ({len(nogo):2d}): {nogo}")
    if insuf:print(f"INSUF    ({len(insuf):2d}): {insuf}")
    if go:   print(f"\n-> Scalp agent ready for: {go}")
    else:    print("\n-> No scalp GO. Try --no-volume for pattern-only baseline.")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    log.info("Report: %s", REPORT_FILE)


if __name__ == "__main__":
    main()
