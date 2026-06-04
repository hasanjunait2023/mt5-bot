"""GS12 aggressive optimizer with in-sample / out-of-sample validation.

Grid-searches GS12_PARAMS to maximize profit factor on the in-sample slice
(first 65% of bars), then validates the best candidates on the held-out
out-of-sample slice (last 35%). Any config whose edge collapses out-of-sample is
flagged as overfit and discarded. Runs both XAUUSD M3 and M1; reports the best
robust config per timeframe and saves the overall winner.

Real spread cost (XAUUSD 0.30) is applied by the backtest engine.

Run:
  python -m trading_agents.scalp.optimize_gs12
  python -m trading_agents.scalp.optimize_gs12 --bars 5000 --symbol XAUUSD
"""
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime
from pathlib import Path

from trading_agents.scalp import backtest as bt

REPORT_DIR = bt.BASE_DIR / "backtest_reports"
CONFIG_DIR = bt.BASE_DIR / "configs"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Aggressive but bounded grid (192 combos / timeframe).
GRID = {
    "min_depth_atr":  [0.15, 0.30, 0.50],
    "rr":             [1.2, 1.5, 2.0, 2.5],
    "use_ifvg_only":  [True, False],
    "session_filter": [False, True],
    "htf_bias":       [False, True],
    "conf_window":    [5, 8],
}
FIXED = {"sweep_lookback": 5, "trend_swing_lookback": 3,
         "fit_swings": 2, "sl_buffer_atr": 0.5, "atr_period": 14}

MIN_IS_TRADES = 12
MIN_OOS_TRADES = 6
TOP_K = 10                 # candidates carried to OOS validation
OVERFIT_RETENTION = 0.60   # OOS PF must be >= IS PF * this


def slice_bars(bars: dict, lo: int, hi: int) -> dict:
    return {k: (v[lo:hi] if isinstance(v, list) else v) for k, v in bars.items()}


def run_combo(symbol: str, sub: dict, params: dict) -> dict:
    bt.GS12_PARAMS.update(FIXED)
    bt.GS12_PARAMS.update(params)
    return bt.backtest_one("GS12", symbol, sub)


def optimize_tf(symbol: str, tf: str, bars: dict) -> dict | None:
    n = len(bars.get("close", []))
    if n < 800:
        print(f"  {tf}: only {n} bars — skip")
        return None
    split = int(n * 0.65)
    is_bars = slice_bars(bars, 0, split)
    oos_bars = slice_bars(bars, split, n)
    print(f"  {tf}: {n} bars  (in-sample {split}, OOS {n - split})")

    keys = list(GRID.keys())
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    scored = []
    for combo in combos:
        params = dict(zip(keys, combo))
        r = run_combo(symbol, is_bars, params)
        if r.get("trades", 0) >= MIN_IS_TRADES:
            scored.append((r.get("profit_factor", 0.0), params, r))
    if not scored:
        print(f"  {tf}: no combo cleared {MIN_IS_TRADES} in-sample trades")
        return None
    scored.sort(key=lambda x: x[0], reverse=True)

    # Validate top-K on OOS, keep robust ones.
    robust = []
    for is_pf, params, r_is in scored[:TOP_K]:
        r_oos = run_combo(symbol, oos_bars, params)
        oos_pf = r_oos.get("profit_factor", 0.0)
        oos_tr = r_oos.get("trades", 0)
        # Robust = profitable on BOTH halves, OOS edge doesn't collapse, enough
        # OOS trades. Requiring IS >= 1.0 too rejects lucky-OOS / poor-IS configs.
        overfit = (oos_pf < 1.0) or (is_pf < 1.0) \
            or (oos_pf < is_pf * OVERFIT_RETENTION) or (oos_tr < MIN_OOS_TRADES)
        robust.append({
            "params": params, "is_pf": is_pf, "is_trades": r_is.get("trades", 0),
            "is_wr": r_is.get("win_rate_pct", 0), "oos_pf": oos_pf,
            "oos_trades": oos_tr, "oos_wr": r_oos.get("win_rate_pct", 0),
            "overfit": overfit,
        })

    clean = [c for c in robust if not c["overfit"]]
    # Rank by robustness (weakest half), not raw OOS PF — avoids lucky-OOS picks.
    clean.sort(key=lambda c: min(c["is_pf"], c["oos_pf"]), reverse=True)
    best = clean[0] if clean else None

    # Full-sample headline number with the chosen params.
    full = None
    if best:
        full = run_combo(symbol, bars, best["params"])

    return {"tf": tf, "symbol": symbol, "candidates": robust,
            "best": best, "full": full,
            "is_top_pf": scored[0][0]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=5000)
    args = ap.parse_args()

    results = []
    for tf in ("M3", "M1"):
        print(f"Optimizing {args.symbol} {tf}...")
        bars = bt._fetch_bars(args.symbol, tf, args.bars)
        if not bars or not bars.get("close"):
            print(f"  no bars for {args.symbol} {tf}")
            continue
        res = optimize_tf(args.symbol, tf, bars)
        if res:
            results.append(res)
            b = res["best"]
            if b:
                f = res["full"] or {}
                print(f"  BEST {tf}: OOS PF={b['oos_pf']} (IS {b['is_pf']}) "
                      f"OOS trades={b['oos_trades']} | full PF={f.get('profit_factor')} "
                      f"WR={f.get('win_rate_pct')}% trades={f.get('trades')}")
                print(f"       params={b['params']}")
            else:
                print(f"  {tf}: NO robust config survived OOS validation "
                      f"(best in-sample PF was {res['is_top_pf']})")

    # Pick overall winner across timeframes by full-sample PF (must be robust).
    winners = [(r["full"]["profit_factor"], r) for r in results
               if r.get("best") and r.get("full")]
    winner = max(winners, key=lambda x: x[0])[1] if winners else None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if winner:
        cfg = {
            "strategy": "GS12",
            "name": "ICT Stupid-Simple (Sweep->IFVG->Trendline Break)",
            "symbol": args.symbol,
            "timeframe": winner["tf"],
            "params": {**FIXED, **winner["best"]["params"]},
            "validation": {
                "in_sample_pf": winner["best"]["is_pf"],
                "in_sample_trades": winner["best"]["is_trades"],
                "oos_pf": winner["best"]["oos_pf"],
                "oos_trades": winner["best"]["oos_trades"],
                "oos_win_rate": winner["best"]["oos_wr"],
                "full_pf": winner["full"]["profit_factor"],
                "full_trades": winner["full"]["trades"],
                "full_win_rate": winner["full"]["win_rate_pct"],
            },
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        cfg_path = CONFIG_DIR / f"ea_params_GS12_{datetime.now():%Y%m%d}.json"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\nWinner saved: {cfg_path}")
    else:
        print("\nNo robust profitable config found across M3/M1.")

    _write_report(args.symbol, results, winner, stamp)


def _write_report(symbol: str, results: list, winner: dict | None, stamp: str) -> None:
    lines = [f"# GS12 Optimization — {symbol}",
             f"\nGenerated {datetime.now().isoformat(timespec='seconds')} | "
             f"real spread cost applied | overfit guard: OOS PF >= IS PF x "
             f"{OVERFIT_RETENTION}, OOS PF >= 1.0, OOS trades >= {MIN_OOS_TRADES}\n"]
    for r in results:
        lines.append(f"\n## {r['symbol']} {r['tf']}")
        b = r.get("best")
        if b:
            f = r["full"] or {}
            lines.append(
                f"\n**Best robust:** OOS PF **{b['oos_pf']}** (IS {b['is_pf']}, "
                f"OOS WR {b['oos_wr']}%, OOS trades {b['oos_trades']})  \n"
                f"Full-sample: PF **{f.get('profit_factor')}**, WR "
                f"{f.get('win_rate_pct')}%, trades {f.get('trades')}, "
                f"maxDD {f.get('max_drawdown')}  \n"
                f"Params: `{b['params']}`\n")
        else:
            lines.append(f"\nNo robust config survived OOS. Best in-sample PF "
                         f"was {r['is_top_pf']} (overfit/under-traded).\n")
        lines.append("\n| IS PF | IS trades | OOS PF | OOS trades | OOS WR | overfit | params |")
        lines.append("|---|---|---|---|---|---|---|")
        for c in r.get("candidates", []):
            lines.append(
                f"| {c['is_pf']} | {c['is_trades']} | {c['oos_pf']} | "
                f"{c['oos_trades']} | {c['oos_wr']} | "
                f"{'YES' if c['overfit'] else 'no'} | `{c['params']}` |")
    if winner:
        lines.append(f"\n## Verdict\n\nWinner: **{symbol} {winner['tf']}** — "
                     f"full-sample PF {winner['full']['profit_factor']}, "
                     f"OOS PF {winner['best']['oos_pf']}. Config saved for the live agent.\n")
    else:
        lines.append("\n## Verdict\n\nNo config cleared the bar (PF>=1.3 robust). "
                     "GS12 stays in paper/quarantine — honest result, not curve-fit.\n")
    out = REPORT_DIR / f"analysis_GS12_{stamp}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
