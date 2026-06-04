"""Generic walk-forward optimizer for factory strategies.

Generalizes scalp/optimize_gs12.py: grid-search a strategy's tunable params on the
in-sample slice (first 65%), validate the top-K out-of-sample (last 35%), keep
only robust configs (no OOS collapse), pick the weakest-link-best, and write
configs/ea_params_<SID>_<date>.json + a markdown report.

Works on ANY registered strategy (hand-written or generated) by mutating the
strategy module's *_PARAMS dict in place via fn.__globals__.
"""
from __future__ import annotations

import itertools
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from trading_agents.scalp import backtest as bt

log = logging.getLogger("factory.optimize")

REPORT_DIR = bt.BASE_DIR / "backtest_reports"
CONFIG_DIR = bt.BASE_DIR / "configs"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

MIN_IS_TRADES = 10
MIN_OOS_TRADES = 6
TOP_K = 10
OVERFIT_RETENTION = 0.60
MAX_GRID_KEYS = 4
MAX_GRID_VALUES = 4


def _params_dict(strategy_id: str) -> Optional[dict]:
    """The mutable *_PARAMS dict in the strategy's module namespace, or None."""
    fn = bt.STRATEGIES.get(strategy_id, (None, None))[1]
    if fn is None:
        return None
    g = getattr(fn, "__globals__", {})
    if f"{strategy_id}_PARAMS" in g and isinstance(g[f"{strategy_id}_PARAMS"], dict):
        return g[f"{strategy_id}_PARAMS"]
    for k, v in g.items():
        if k.endswith("_PARAMS") and isinstance(v, dict):
            return v
    return None


def _slice(bars: dict, lo: int, hi: int) -> dict:
    return {k: (v[lo:hi] if isinstance(v, list) else v) for k, v in bars.items()}


def _build_grid(spec: dict, params: dict) -> dict:
    """Grid = spec.tunable_params restricted to keys that exist in the strategy's
    params dict, capped for a bounded combo count."""
    raw = spec.get("tunable_params") or {}
    grid: dict = {}
    for k, vals in raw.items():
        if k in params and isinstance(vals, list) and len(vals) > 1:
            grid[k] = vals[:MAX_GRID_VALUES]
        if len(grid) >= MAX_GRID_KEYS:
            break
    return grid


def optimize_generic(strategy_id: str, spec: dict, *, bars_n: int = 5000) -> dict:
    """Run the walk-forward optimization. Returns a result dict with full-sample
    metrics, best params, and the saved config path (or a no-op note)."""
    tf = bt.STRATEGIES[strategy_id][0]
    symbol = (spec.get("symbols") or ["XAUUSD"])[0]
    params = _params_dict(strategy_id)
    bars = bt._fetch_bars(symbol, tf, bars_n)
    if not bars or not bars.get("close"):
        return {"ok": False, "reason": f"no bars for {symbol} {tf}"}

    n = len(bars["close"])
    grid = _build_grid(spec, params) if params else {}

    if not grid:
        # Nothing to sweep — just record the full-sample backtest of current params.
        full = bt.backtest_one(strategy_id, symbol, bars)
        cfg_path = _save_config(strategy_id, symbol, tf, dict(params or {}), full, None)
        log.info("[optimize] %s no tunable grid — full PF=%s", strategy_id,
                 full.get("profit_factor"))
        return {"ok": True, "full": full, "best_params": dict(params or {}),
                "oos_pf": None, "config_path": str(cfg_path), "grid": 0}

    split = int(n * 0.65)
    is_bars, oos_bars = _slice(bars, 0, split), _slice(bars, split, n)
    keys = list(grid.keys())
    base = dict(params)  # restore-able baseline

    scored = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        cand = dict(zip(keys, combo))
        params.clear(); params.update(base); params.update(cand)
        r = bt.backtest_one(strategy_id, symbol, is_bars)
        if r.get("trades", 0) >= MIN_IS_TRADES:
            scored.append((r.get("profit_factor", 0.0), cand, r))
    scored.sort(key=lambda x: x[0], reverse=True)

    robust = []
    for is_pf, cand, r_is in scored[:TOP_K]:
        params.clear(); params.update(base); params.update(cand)
        r_oos = bt.backtest_one(strategy_id, symbol, oos_bars)
        oos_pf = r_oos.get("profit_factor", 0.0)
        oos_tr = r_oos.get("trades", 0)
        overfit = (oos_pf < 1.0) or (is_pf < 1.0) \
            or (oos_pf < is_pf * OVERFIT_RETENTION) or (oos_tr < MIN_OOS_TRADES)
        robust.append({"params": cand, "is_pf": is_pf, "is_trades": r_is.get("trades", 0),
                       "oos_pf": oos_pf, "oos_trades": oos_tr,
                       "oos_wr": r_oos.get("win_rate_pct", 0), "overfit": overfit})

    clean = sorted([c for c in robust if not c["overfit"]],
                   key=lambda c: min(c["is_pf"], c["oos_pf"]), reverse=True)
    best = clean[0] if clean else (sorted(robust, key=lambda c: c["oos_pf"], reverse=True)[0]
                                   if robust else None)

    best_params = {**base, **best["params"]} if best else dict(base)
    params.clear(); params.update(best_params)
    full = bt.backtest_one(strategy_id, symbol, bars)
    cfg_path = _save_config(strategy_id, symbol, tf, best_params, full, best)
    report = _write_report(strategy_id, symbol, tf, robust, best, full)
    log.info("[optimize] %s best full PF=%s OOS=%s (%d robust/%d)", strategy_id,
             full.get("profit_factor"), best["oos_pf"] if best else None,
             len(clean), len(robust))
    return {"ok": True, "full": full, "best_params": best_params,
            "oos_pf": best["oos_pf"] if best else None,
            "config_path": str(cfg_path), "report_path": str(report),
            "grid": len(robust)}


def _save_config(sid: str, symbol: str, tf: str, params: dict,
                 full: dict, best: Optional[dict]) -> Path:
    cfg = {
        "strategy": sid, "symbol": symbol, "timeframe": tf, "params": params,
        "validation": {
            "full_pf": full.get("profit_factor"),
            "full_trades": full.get("trades"),
            "full_win_rate": full.get("win_rate_pct"),
            "full_max_dd": full.get("max_drawdown"),
            "oos_pf": best["oos_pf"] if best else None,
            "oos_trades": best["oos_trades"] if best else None,
            "is_pf": best["is_pf"] if best else None,
        },
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    path = CONFIG_DIR / f"ea_params_{sid}_{datetime.now():%Y%m%d}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _write_report(sid: str, symbol: str, tf: str, robust: list,
                  best: Optional[dict], full: dict) -> Path:
    lines = [f"# {sid} Optimization — {symbol} {tf}",
             f"\nGenerated {datetime.now().isoformat(timespec='seconds')} | real spread | "
             f"overfit guard OOS>=IS*{OVERFIT_RETENTION}, OOS PF>=1.0, OOS trades>={MIN_OOS_TRADES}\n"]
    if best:
        lines.append(f"\n**Best robust:** OOS PF **{best['oos_pf']}** (IS {best['is_pf']}, "
                     f"OOS trades {best['oos_trades']})  \nFull-sample: PF "
                     f"**{full.get('profit_factor')}**, WR {full.get('win_rate_pct')}%, "
                     f"trades {full.get('trades')}, maxDD {full.get('max_drawdown')}  \n"
                     f"Params: `{best['params']}`\n")
    else:
        lines.append("\nNo robust config survived OOS validation.\n")
    lines.append("\n| IS PF | IS tr | OOS PF | OOS tr | OOS WR | overfit | params |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in robust:
        lines.append(f"| {c['is_pf']} | {c['is_trades']} | {c['oos_pf']} | {c['oos_trades']} | "
                     f"{c['oos_wr']} | {'YES' if c['overfit'] else 'no'} | `{c['params']}` |")
    out = REPORT_DIR / f"analysis_{sid}_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
