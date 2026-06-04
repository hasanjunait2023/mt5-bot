"""Board-level walk-forward backtest — validates the WHOLE-BOARD selection.

Unlike backtest_iconic.py (per-symbol), this simulates the board system as a
portfolio: at each H1 bar it computes board strength across all 28 pairs, runs
the leader + HARD group-roll-over selection (engine.evaluate leaders_only +
require_group_rollover), applies the live exposure cap (1/group, max 3), books
the leader at the next bar open with real spread cost, and exits on SL/TP_final.

This answers the open question: does leader+group-roll-over selection carry edge
over the (thin) per-pair results? Management (scale-out/stop-to-zero) is NOT
modelled here — this isolates the SELECTION edge. News/A-class is unavailable
historically, so everything is B-class (matches live: A-class is live-only).

Run (on VPS, bridge supplies bars):
  MT5_BRIDGE_URL=http://localhost:8090 python -m trading_agents.iconic.backtest_board
  ... --limit 5000 --walkforward
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.iconic import board as board_mod
from trading_agents.iconic.engine import IconicEngine
from trading_agents.iconic.correlation import split_pair

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("board.backtest")

REPORT = BASE_DIR / "logs" / "jtcc" / "_backtest_board.json"

WARMUP        = 300       # bars before trading (ema200 + pattern lookback)
WINDOW        = 300       # slice fed to the scorer/pattern each bar
EVAL_EVERY    = 3         # run the (heavy) board decision every Nth bar; exits
                          # are still checked every bar. The money-spot setup
                          # persists across bars, so sampling barely misses
                          # entries while cutting classify cost ~3x.
MAX_CONCURRENT = 3
MAX_HOLD_BARS = 120
WF_OOS_BARS   = 1500
WF_IS_BARS    = 2500

TYPICAL_SPREAD = {  # price units
    "EURUSD": 8e-5, "GBPUSD": 1e-4, "AUDUSD": 1e-4, "NZDUSD": 1e-4, "USDJPY": 8e-3,
    "USDCHF": 1e-4, "USDCAD": 1.2e-4, "EURGBP": 1e-4, "EURJPY": 1.2e-2,
    "EURCHF": 1e-4, "EURAUD": 1.5e-4, "EURNZD": 2e-4, "EURCAD": 1.5e-4,
    "GBPJPY": 1.5e-2, "GBPCHF": 1.5e-4, "GBPAUD": 2e-4, "GBPNZD": 2.5e-4,
    "GBPCAD": 2e-4, "AUDJPY": 1.2e-2, "AUDCHF": 1.5e-4, "AUDNZD": 1.5e-4,
    "AUDCAD": 1.5e-4, "NZDJPY": 1.2e-2, "NZDCHF": 1.5e-4, "NZDCAD": 1.5e-4,
    "CADJPY": 1.2e-2, "CADCHF": 1.5e-4, "CHFJPY": 1.2e-2,
}


def _fetch(symbol: str, limit: int) -> pd.DataFrame | None:
    url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{url}/bars/{symbol}",
                         params={"timeframe": "H1", "limit": limit}, timeout=60)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        log.warning("fetch %s failed: %s", symbol, e)
        return None
    df = pd.DataFrame({k: v for k, v in d.items() if isinstance(v, list)})
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            return None
    df["tick_volume"] = df.get("volume", df.get("tick_volume", 0.0))
    df["ema200"] = df["close"].ewm(alpha=1 / 200, adjust=False).mean()
    return df


def _load_board(limit: int) -> dict[str, pd.DataFrame]:
    out = {}
    for sym in board_mod.BOARD_PAIRS:
        df = _fetch(sym, limit)
        if df is not None and len(df) >= WARMUP + 50:
            out[sym] = df.reset_index(drop=True)
    log.info("loaded %d/%d pairs", len(out), len(board_mod.BOARD_PAIRS))
    return out


def _simulate(data: dict[str, pd.DataFrame], lo: int, hi: int) -> dict:
    """Walk bars [lo,hi); book leaders, exit on SL/tp_final. Returns stats."""
    engine = IconicEngine(setup_tf="H1", pullback_tf="M15")
    n = min(len(df) for df in data.values())
    hi = min(hi, n - 1)
    open_tr: dict[str, dict] = {}
    trades: list[dict] = []

    def dom_of(sym, sc):
        b, q = split_pair(sym)
        return b if abs(sc.base7) >= abs(sc.quote7) else q

    for t in range(max(lo, WARMUP), hi):
        # 1) manage open trades on bar t
        for sym in list(open_tr.keys()):
            tr = open_tr[sym]; bar = data[sym].iloc[t]
            hi_p, lo_p = float(bar["high"]), float(bar["low"])
            exit_px = None
            if tr["side"] == "BUY":
                if lo_p <= tr["sl"]: exit_px = tr["sl"]
                elif hi_p >= tr["tp"]: exit_px = tr["tp"]
            else:
                if hi_p >= tr["sl"]: exit_px = tr["sl"]
                elif lo_p <= tr["tp"]: exit_px = tr["tp"]
            if exit_px is None and t - tr["entry_bar"] >= MAX_HOLD_BARS:
                exit_px = float(bar["close"])
            if exit_px is not None:
                pnl = (exit_px - tr["entry"]) if tr["side"] == "BUY" else (tr["entry"] - exit_px)
                pnl -= tr["spread"]
                r = pnl / tr["risk"] if tr["risk"] > 0 else 0.0
                trades.append({"symbol": sym, "side": tr["side"], "klass": tr["klass"],
                               "pnl": pnl, "r": r, "bars": t - tr["entry_bar"],
                               "exit": "TP" if r > 0 else "SL"})
                del open_tr[sym]

        # decision sampling: only run the board every EVAL_EVERY bars
        if (t - WARMUP) % EVAL_EVERY != 0:
            continue

        # 2) build snapshots from the window up to bar t (closed)
        snaps = {}
        for sym, df in data.items():
            win = df.iloc[max(0, t - WINDOW):t + 1]
            if len(win) < 50:
                continue
            last = win.iloc[-1]
            align = ("bull" if last["close"] > last["ema200"]
                     else "bear" if last["close"] < last["ema200"] else "none")
            snaps[sym] = {"align": align, "tfs": {"H1": win}}

        strength = board_mod.compute_strength(snaps, setup_tf="H1")
        # classify the board ONCE, then select leaders + hard roll-over inline,
        # running the (heavy) pattern detector only on leaders.
        try:
            scores = engine.scorer.classify_group(snaps, strength)
        except Exception:
            continue
        ab_by_dom: dict[str, list[str]] = {}
        for s, sc in scores.items():
            if sc.klass in ("A", "B"):
                d = dom_of(s, sc)
                if d:
                    ab_by_dom.setdefault(d, []).append(s)
        sigs = []
        for s, sc in scores.items():
            if sc.klass not in ("A", "B") or not sc.is_leader:
                continue
            d = dom_of(s, sc)
            if not d or len(ab_by_dom.get(d, [])) < 2:      # hard group roll-over
                continue
            try:
                sig = engine._build(s, snaps[s], sc)
            except Exception:
                sig = None
            if sig is not None:
                sigs.append(sig)

        # 3) book at next bar open with exposure cap
        if not sigs or t + 1 >= len(next(iter(data.values()))):
            continue
        open_doms = {dom_of(s, scores[s]) for s in open_tr if s in scores}
        for sig in sigs:
            sym = sig.symbol
            if sym in open_tr or len(open_tr) >= MAX_CONCURRENT:
                continue
            sc = scores.get(sym)
            dom = dom_of(sym, sc) if sc else None
            if dom and dom in open_doms:
                continue
            nb = data[sym].iloc[t + 1]
            spread = TYPICAL_SPREAD.get(sym, 1e-4)
            entry = float(nb["open"]) + (spread if sig.side == "BUY" else 0.0)
            risk = abs(entry - sig.stop)
            if risk <= 0:
                continue
            open_tr[sym] = {"side": sig.side, "entry": entry, "sl": sig.stop,
                            "tp": sig.tp_final, "risk": risk, "spread": spread,
                            "klass": sig.klass, "entry_bar": t + 1}
            if dom:
                open_doms.add(dom)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_w = sum(t["pnl"] for t in wins)
    gross_l = abs(sum(t["pnl"] for t in losses))
    pf = round(gross_w / gross_l, 3) if gross_l > 0 else (99.0 if gross_w > 0 else 0.0)
    total_r = round(sum(t["r"] for t in trades), 2)
    return {"trades": len(trades), "wins": len(wins),
            "win_rate": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
            "profit_factor": pf, "total_R": total_r,
            "avg_bars": round(sum(t["bars"] for t in trades) / len(trades), 1) if trades else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--walkforward", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    data = _load_board(args.limit)
    if len(data) < 10:
        log.error("not enough pairs (%d) — bridge/bars issue", len(data))
        sys.exit(1)
    n = min(len(df) for df in data.values())
    log.info("aligned bars: %d", n)

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "pairs": len(data),
              "bars": n, "gates": {"pf": 1.3, "min_trades": 15}}
    if args.walkforward and n > WF_IS_BARS + WF_OOS_BARS:
        is_lo, is_hi = n - WF_IS_BARS - WF_OOS_BARS, n - WF_OOS_BARS
        log.info("IS  bars [%d,%d)", is_lo, is_hi)
        report["IS"] = _simulate(data, is_lo, is_hi)
        log.info("IS  -> %s", report["IS"])
        log.info("OOS bars [%d,%d)", is_hi, n)
        report["OOS"] = _simulate(data, is_hi, n)
        log.info("OOS -> %s", report["OOS"])
    else:
        report["FULL"] = _simulate(data, WARMUP, n)
        log.info("FULL -> %s", report["FULL"])

    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("wrote %s", REPORT)


if __name__ == "__main__":
    main()
