"""Iconic Trader Phase 3 backtest — walk-forward H1 validation with real spread costs.

Proves (or disproves) the tick-volume edge in spot FX before any EA is built.
Go/no-go gate: PF >= 1.3 and >= 10 trades per symbol.

Run:
  python -m trading_agents.jtcc.backtest_iconic
  python -m trading_agents.jtcc.backtest_iconic --symbols EURUSD GBPUSD
  python -m trading_agents.jtcc.backtest_iconic --no-volume   # ablation: volume always present
  python -m trading_agents.jtcc.backtest_iconic --limit 2000  # faster / fewer years
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
log = logging.getLogger("iconic.backtest")

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
REPORT_FILE = BASE_DIR / "logs" / "jtcc" / "_backtest_iconic.json"

# ── symbols ───────────────────────────────────────────────────────────────────
DEFAULT_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD",
    "USDCAD", "USDCHF", "GBPJPY", "EURJPY",
]

TYPICAL_SPREADS = {
    "EURUSD": 0.00008, "GBPUSD": 0.0001,  "USDJPY": 0.008,
    "AUDUSD": 0.00010, "NZDUSD": 0.00010, "USDCAD": 0.00012,
    "USDCHF": 0.00010, "GBPJPY": 0.015,   "EURJPY": 0.012,
    "GBPAUD": 0.00015, "EURAUD": 0.00015,
}

SIGNAL_EXPIRY_BARS = 5    # cancel unfilled entry order after this many H1 bars
MAX_HOLD_BARS      = 120  # force-close after 5 calendar days (safety net)
GO_MIN_PF          = 1.3
GO_MIN_TRADES      = 10


# ── MT5 bridge ────────────────────────────────────────────────────────────────
def _fetch_bars(symbol: str, tf: str, limit: int = 5000) -> Optional[dict]:
    url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{url}/bars/{symbol}",
                         params={"timeframe": tf, "limit": limit}, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("Fetch %s %s failed: %s", symbol, tf, e)
        return None


# ── DataFrame helpers ─────────────────────────────────────────────────────────
def _to_df(bars: dict) -> Optional[pd.DataFrame]:
    if not bars or not bars.get("close"):
        return None
    df = pd.DataFrame({k: v for k, v in bars.items() if isinstance(v, list)})
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            return None
    if "tick_volume" not in df.columns:
        df["tick_volume"] = 0.0
    if "time" in df.columns:
        df["time"] = pd.to_numeric(df["time"])
    # EMA-200 for alignment
    df["ema200"] = df["close"].ewm(alpha=1 / 200, adjust=False).mean()
    return df


def _align_h1(df: pd.DataFrame) -> str:
    if len(df) < 200:
        return "none"
    row = df.iloc[-1]
    if row["close"] > row["ema200"]:
        return "bull"
    if row["close"] < row["ema200"]:
        return "bear"
    return "none"


def _find_idx(times: list, target) -> int:
    """Last index where times[idx] <= target. Returns -1 if none."""
    lo, hi = 0, len(times)
    while lo < hi:
        m = (lo + hi) // 2
        if times[m] <= target:
            lo = m + 1
        else:
            hi = m
    return lo - 1


def _slice_m15(m15_full: pd.DataFrame, t_h1) -> Optional[pd.DataFrame]:
    if "time" not in m15_full.columns:
        return m15_full
    idx = _find_idx(m15_full["time"].tolist(), t_h1)
    if idx < 0:
        return None
    return m15_full.iloc[:idx + 1]


# ── currency strength (mirrors SignalEngine._currency_strength) ───────────────
_SPECIAL_PAIRS = {"XAUUSD": ("XAU", "USD"), "XAGUSD": ("XAG", "USD"),
                  "BTCUSD": ("BTC", "USD")}


def _split(sym: str) -> tuple[str, str]:
    if sym in _SPECIAL_PAIRS:
        return _SPECIAL_PAIRS[sym]
    if len(sym) == 6 and sym.isalpha():
        return sym[:3], sym[3:]
    return "", ""


def _currency_strength(align_map: dict[str, str]) -> dict[str, float]:
    """align_map = {symbol: 'bull'|'bear'|'none'}. Returns 0..10 per currency."""
    raw: dict[str, list[int]] = {}
    for sym, align in align_map.items():
        base, quote = _split(sym)
        if not base:
            continue
        b, q = (1, -1) if align == "bull" else ((-1, 1) if align == "bear" else (0, 0))
        raw.setdefault(base,  []).append(b)
        raw.setdefault(quote, []).append(q)
    return {ccy: round((sum(v) / len(v) + 1) * 5, 1) for ccy, v in raw.items() if v}


# ── single-symbol walk-forward ────────────────────────────────────────────────
def backtest_one(symbol: str, h1_full: pd.DataFrame, m15_full: pd.DataFrame,
                 all_h1: dict[str, pd.DataFrame], no_volume: bool) -> dict:
    from trading_agents.iconic.engine import IconicEngine
    engine = IconicEngine()

    spread = TYPICAL_SPREADS.get(symbol, 0.0001)
    times  = h1_full["time"].tolist()
    highs  = h1_full["high"].tolist()
    lows   = h1_full["low"].tolist()
    closes = h1_full["close"].tolist()
    n = len(times)

    # Pre-cache other symbols' time arrays for O(log n) alignment lookup per bar
    other_times: dict[str, list] = {
        s: df["time"].tolist() for s, df in all_h1.items() if s != symbol and "time" in df.columns
    }

    start_i = max(250, n - 3000)
    trades: list[dict] = []
    position: Optional[dict] = None
    pending:  Optional[dict] = None

    for i in range(start_i, n - 1):
        t = times[i]
        nh, nl = highs[i], lows[i]

        # 1 ── manage open position ────────────────────────────────────────
        if position is not None:
            side = position["side"]
            hit_sl = (nl <= position["sl"]) if side == "BUY" else (nh >= position["sl"])
            hit_tp = (nh >= position["tp"]) if side == "BUY" else (nl <= position["tp"])
            timeout = (i - position["bar_i"]) >= MAX_HOLD_BARS

            if hit_sl or hit_tp or timeout:
                if hit_sl:
                    raw_pnl = position["sl"] - position["entry"] if side == "BUY" \
                              else position["entry"] - position["sl"]
                    exit_tag = "SL"
                elif hit_tp:
                    raw_pnl = position["tp"] - position["entry"] if side == "BUY" \
                              else position["entry"] - position["tp"]
                    exit_tag = "TP"
                else:
                    raw_pnl = closes[i] - position["entry"] if side == "BUY" \
                              else position["entry"] - closes[i]
                    exit_tag = "TIMEOUT"
                trades.append({
                    "pnl":       round(raw_pnl - spread, 8),
                    "exit":      exit_tag,
                    "bars_held": i - position["bar_i"],
                    "klass":     position["klass"],
                })
                position = None

        # 2 ── try to fill pending order ───────────────────────────────────
        if pending is not None and position is None:
            age = i - pending["signal_bar"]
            if age > SIGNAL_EXPIRY_BARS:
                pending = None
            else:
                sig = pending["signal"]
                if sig.side == "BUY" and nh >= sig.entry:
                    position = {"side": "BUY",  "entry": sig.entry + spread,
                                "sl": sig.stop, "tp": sig.tp_final,
                                "bar_i": i, "klass": sig.klass}
                    pending = None
                elif sig.side == "SELL" and nl <= sig.entry:
                    position = {"side": "SELL", "entry": sig.entry - spread,
                                "sl": sig.stop, "tp": sig.tp_final,
                                "bar_i": i, "klass": sig.klass}
                    pending = None

        # 3 ── scan for new signal ─────────────────────────────────────────
        if position is None and pending is None:
            h1_slice  = h1_full.iloc[:i + 1]
            m15_slice = _slice_m15(m15_full, t)
            if m15_slice is None or len(m15_slice) < 50:
                continue

            # Volume ablation: force every bar to look like a pop
            if no_volume:
                h1_slice = h1_slice.copy()
                avg = float(h1_slice["tick_volume"].mean()) or 100.0
                h1_slice["tick_volume"] = avg * 2.0

            align = _align_h1(h1_slice)
            snap = {"align": align, "tfs": {"H1": h1_slice, "M15": m15_slice}}

            # Group alignment map for currency strength
            align_map: dict[str, str] = {symbol: align}
            for other_sym, ot in other_times.items():
                oi = _find_idx(ot, t)
                if oi >= 200:
                    align_map[other_sym] = _align_h1(all_h1[other_sym].iloc[:oi + 1])

            strength = _currency_strength(align_map)

            try:
                now_dt = datetime.fromtimestamp(float(t), tz=timezone.utc)
                sigs = engine.evaluate({symbol: snap}, strength, now=now_dt)
            except Exception as e:
                log.debug("evaluate error %s bar %d: %s", symbol, i, e)
                continue

            if sigs:
                pending = {"signal": sigs[0], "signal_bar": i}

    return _summarize(symbol, trades, n - start_i)


# ── summary ───────────────────────────────────────────────────────────────────
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
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    tp_exits = sum(1 for t in trades if t["exit"] == "TP")
    if len(pnls) < GO_MIN_TRADES:
        verdict = "INSUFFICIENT"
    elif pf >= GO_MIN_PF:
        verdict = "GO"
    elif pf >= 1.0:
        verdict = "MARGINAL"
    else:
        verdict = "NO_GO"
    return {
        "symbol":         symbol,
        "trades":         len(pnls),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate_pct":   wr,
        "profit_factor":  pf,
        "total_pnl":      round(sum(pnls), 8),
        "max_drawdown":   round(mdd, 8),
        "avg_hold_bars":  round(sum(t.get("bars_held", 0) for t in trades) / len(trades), 1),
        "class_A_trades": sum(1 for t in trades if t.get("klass") == "A"),
        "class_B_trades": sum(1 for t in trades if t.get("klass") == "B"),
        "tp_exits":       tp_exits,
        "sl_exits":       sum(1 for t in trades if t["exit"] == "SL"),
        "timeout_exits":  sum(1 for t in trades if t["exit"] == "TIMEOUT"),
        "tp_rate_pct":    round(tp_exits / len(pnls) * 100, 1),
        "bars_tested":    bars_tested,
        "verdict":        verdict,
    }


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iconic Trader Phase 3 backtest — H1 walk-forward with spread costs")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--limit", type=int, default=5000,
                        help="Max H1 bars per symbol (default 5000 ≈ ~3 years)")
    parser.add_argument("--no-volume", action="store_true",
                        help="Ablation: bypass volume gate (always assume pop present)")
    args = parser.parse_args()

    label = "NO-VOLUME ABLATION" if args.no_volume else "FULL (with volume gate)"
    log.info("Iconic Trader Phase 3 backtest [%s] — %d symbols, limit=%d",
             label, len(args.symbols), args.limit)

    # Fetch bars for all symbols
    h1_data:  dict[str, pd.DataFrame] = {}
    m15_data: dict[str, pd.DataFrame] = {}
    for sym in args.symbols:
        log.info("Fetching %s...", sym)
        h1_raw  = _fetch_bars(sym, "H1",  args.limit)
        m15_raw = _fetch_bars(sym, "M15", args.limit * 4)
        h1_df   = _to_df(h1_raw)  if h1_raw  else None
        m15_df  = _to_df(m15_raw) if m15_raw else None
        if h1_df is not None and len(h1_df) >= 250:
            h1_data[sym]  = h1_df
            m15_data[sym] = m15_df if (m15_df is not None and len(m15_df) >= 50) else h1_df
            log.info("  H1: %d bars  M15: %d bars", len(h1_df), len(m15_data[sym]))
        else:
            log.warning("  %s: insufficient data — skipping", sym)

    if not h1_data:
        log.error("No usable symbols. Is the MT5 bridge running on port 8090?")
        sys.exit(1)

    # Walk-forward per symbol
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode":         "no_volume_ablation" if args.no_volume else "full",
        "go_pf_gate":   GO_MIN_PF,
        "go_trade_gate": GO_MIN_TRADES,
        "results":      [],
    }

    print()
    print(f"Iconic Trader Phase 3 [{label}]")
    print("=" * 105)
    print(f"{'Symbol':<10s} {'Trades':>7s} {'WR%':>6s} {'PF':>6s} "
          f"{'MaxDD':>12s} {'A-cls':>6s} {'B-cls':>6s} {'TP%':>6s} "
          f"{'AvgHold':>8s} {'Verdict':>12s}")
    print("-" * 105)

    for sym in sorted(h1_data):
        t0 = _time.time()
        result = backtest_one(sym, h1_data[sym], m15_data[sym], h1_data, args.no_volume)
        result["runtime_s"] = round(_time.time() - t0, 1)
        report["results"].append(result)

        tr = result.get("trades", 0)
        if tr == 0:
            print(f"{sym:<10s} {'0':>7s} {'-':>6s} {'-':>6s} "
                  f"{'-':>12s} {'-':>6s} {'-':>6s} {'-':>6s} "
                  f"{'-':>8s} {result.get('verdict','?'):>12s}")
        else:
            print(f"{sym:<10s} {tr:>7d} {result['win_rate_pct']:>6.1f} "
                  f"{result['profit_factor']:>6.2f} "
                  f"{result['max_drawdown']:>12.6f} "
                  f"{result['class_A_trades']:>6d} {result['class_B_trades']:>6d} "
                  f"{result['tp_rate_pct']:>5.1f}% "
                  f"{result['avg_hold_bars']:>8.1f} "
                  f"{result['verdict']:>12s}")

    # Final verdict summary
    print()
    print("=" * 105)
    go    = [r["symbol"] for r in report["results"] if r["verdict"] == "GO"]
    nogo  = [r["symbol"] for r in report["results"] if r["verdict"] == "NO_GO"]
    marg  = [r["symbol"] for r in report["results"] if r["verdict"] == "MARGINAL"]
    insuf = [r["symbol"] for r in report["results"]
             if r["verdict"] in ("INSUFFICIENT", "NO_TRADES")]

    if go:
        print(f"GO       ({len(go):2d}): {go}")
    if marg:
        print(f"MARGINAL ({len(marg):2d}): {marg}  ← tune thresholds before EA")
    if nogo:
        print(f"NO_GO    ({len(nogo):2d}): {nogo}")
    if insuf:
        print(f"INSUF    ({len(insuf):2d}): {insuf}  ← too few signals, check filters")

    if go:
        print(f"\n→ Proceed to Phase 4 EA for: {go}")
        print(f"  Tune thresholds for MARGINAL before including them.")
    else:
        print("\n→ Volume edge NOT confirmed. Tune POP_FACTOR/DEAD_FACTOR before EA.")
        print("  Re-run with --no-volume to check if pattern layer has standalone edge.")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Full report: %s", REPORT_FILE)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
