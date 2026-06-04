"""GS12 calibration — understand the ICT triad from real XAUUSD candles.

Pulls XAUUSD M3 + M1 bars from the MT5 bridge and measures how often each
component of the "stupid-simple" ICT model actually fires:
  - liquidity sweeps (at several depths),
  - FVGs / inverse FVGs,
  - trendline / structure breaks,
  - triple-confluence (all three within a rolling window) = the real signal supply.

Writes a markdown report to backtest_reports/ and prints a summary so we can pick
sane default thresholds before optimizing GS12.

Run:
  python scripts/gs12_calibrate.py
  python scripts/gs12_calibrate.py --bars 5000 --symbol XAUUSD
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.scalp.indicators import (  # noqa: E402
    atr, detect_liquidity_sweep, find_fvg_zones, find_inverse_fvg,
    detect_trendline_break,
)

REPORT_DIR = BASE_DIR / "backtest_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_bars(symbol: str, tf: str, limit: int) -> dict | None:
    url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{url}/bars/{symbol}",
                         params={"timeframe": tf, "limit": limit}, timeout=90)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"  fetch failed {symbol} {tf}: {e}")
        return None


def calibrate_tf(symbol: str, tf: str, bars: dict, conf_window: int = 10) -> dict:
    o, h, l, c = (bars.get("open", []), bars.get("high", []),
                  bars.get("low", []), bars.get("close", []))
    n = len(c)
    depths = [0.10, 0.15, 0.20, 0.30]
    sweep_counts = {d: 0 for d in depths}
    sweep_depth_samples: list[float] = []
    fvg = ifvg = tline = triple = 0
    sweep_sides = Counter()
    # rolling memory of recent event bar-indices for confluence
    last_sweep = last_fvg = last_break = -999

    start = 60
    for i in range(start, n):
        cl, hl, ll, ol = c[: i + 1], h[: i + 1], l[: i + 1], o[: i + 1]
        a = atr(hl, ll, cl, 14)
        if a <= 0:
            continue
        # sweeps at multiple depth thresholds (count the loosest for samples)
        sw = detect_liquidity_sweep(hl, ll, cl, lookback=5,
                                    min_depth_atr=min(depths), atr_val=a)
        if sw:
            sweep_sides[sw["side"]] += 1
            sweep_depth_samples.append(sw["depth_atr"])
            for d in depths:
                if sw["depth_atr"] >= d:
                    sweep_counts[d] += 1
            last_sweep = i
        zones = find_fvg_zones(ol, hl, ll, cl, lookback=12)
        if zones:
            fvg += 1
            last_fvg = i
        inv = find_inverse_fvg(ol, hl, ll, cl, lookback=16, active_within=6)
        if inv:
            ifvg += 1
        tb = detect_trendline_break(hl, ll, cl, swing_lookback=3, fit_swings=2)
        if tb != 0:
            tline += 1
            last_break = i
        # triple-confluence: sweep + (fvg or ifvg) + break all seen within window
        if (i - last_sweep <= conf_window and i - last_fvg <= conf_window
                and i - last_break <= conf_window):
            triple += 1

    bars_tested = max(1, n - start)
    avg_depth = round(sum(sweep_depth_samples) / len(sweep_depth_samples), 3) \
        if sweep_depth_samples else 0.0
    return {
        "symbol": symbol, "tf": tf, "bars": n, "bars_tested": bars_tested,
        "sweep_counts": sweep_counts, "avg_sweep_depth_atr": avg_depth,
        "sweep_sides": dict(sweep_sides),
        "fvg_bars": fvg, "ifvg_bars": ifvg, "trendline_break_bars": tline,
        "triple_confluence_bars": triple,
        "triple_per_1000": round(triple / bars_tested * 1000, 2),
    }


def fmt(r: dict) -> str:
    sc = " ".join(f"{d}atr={r['sweep_counts'][d]}" for d in r["sweep_counts"])
    return (
        f"### {r['symbol']} {r['tf']} ({r['bars']} bars, {r['bars_tested']} tested)\n\n"
        f"- Sweeps by depth: {sc}\n"
        f"- Avg sweep depth: {r['avg_sweep_depth_atr']} ATR  |  sides: {r['sweep_sides']}\n"
        f"- FVG bars: {r['fvg_bars']}  |  Inverse-FVG bars: {r['ifvg_bars']}\n"
        f"- Trendline/structure breaks: {r['trendline_break_bars']}\n"
        f"- **Triple-confluence bars: {r['triple_confluence_bars']} "
        f"({r['triple_per_1000']} per 1000 bars)**\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--window", type=int, default=10)
    args = ap.parse_args()

    results = []
    for tf in ("M3", "M1"):
        print(f"Fetching {args.symbol} {tf} ({args.bars} bars)...")
        b = fetch_bars(args.symbol, tf, args.bars)
        if not b or not b.get("close"):
            print(f"  no bars for {args.symbol} {tf}")
            continue
        r = calibrate_tf(args.symbol, tf, b, args.window)
        results.append(r)
        print(fmt(r))

    if not results:
        print("No data — is the MT5 bridge running on :8090?")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORT_DIR / f"analysis_GS12_calib_{stamp}.md"
    body = (
        f"# GS12 Calibration — {args.symbol} ICT triad supply\n\n"
        f"Generated {datetime.now().isoformat(timespec='seconds')}  |  "
        f"confluence window = {args.window} bars\n\n"
        + "\n".join(fmt(r) for r in results)
        + "\n## Reading\n\n"
        "Triple-confluence per-1000-bars is the upper bound on trade frequency "
        "before directional/RR/session filters. If it is near zero on a timeframe, "
        "the strategy will starve there; widen the confluence window or loosen "
        "sweep depth. Use avg sweep depth to seed the optimizer's min_depth_atr grid.\n"
    )
    out.write_text(body, encoding="utf-8")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
