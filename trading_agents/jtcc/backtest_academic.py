"""Backtest the academic JTCC strategies on Junait's actual broker (Exness) data.

Walks forward through D1 bars, computes TSMOM + Pairs signals at each bar,
simulates trades with realistic spread costs, reports PF/WR/max DD per strategy.

Run:
  python -m trading_agents.jtcc.backtest_academic --years 3
  python -m trading_agents.jtcc.backtest_academic --symbol XAUUSD --years 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

from trading_agents.jtcc.analytics import tsmom, pairs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("jtcc.backtest")

BASE_DIR = Path(__file__).parent.parent.parent
REPORT_DIR = BASE_DIR / "logs" / "jtcc"
REPORT_FILE = REPORT_DIR / "_backtest_academic.json"

# Conservative spread assumption per symbol (price-units, applied each side)
# These match observed Exness demo spreads (×1.2 for safety margin)
TYPICAL_SPREADS = {
    "XAUUSD": 0.30,   # 30 cents
    "XAGUSD": 0.05,
    "BTCUSD": 12.0,
    "EURUSD": 0.00008,
    "GBPUSD": 0.0001,
    "USDJPY": 0.008,
}


def _fetch_d1(symbol: str, limit: int = 1500) -> dict | None:
    bridge_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{bridge_url}/bars/{symbol}",
                         params={"timeframe": "1day", "limit": limit}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("D1 fetch failed for %s: %s", symbol, e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# TSMOM Backtest (Moskowitz, Ooi, Pedersen 2012)
# ──────────────────────────────────────────────────────────────────────────────

def backtest_tsmom(symbol: str, bars: dict, lookback: int = 252,
                   vol_target: float = 0.40) -> dict:
    """Walk-forward TSMOM backtest. Each bar: enter long if past_N return > 0,
    short if < 0, hold until next bar (1-day holding = aggressive vs paper's monthly).
    Position size: vol-targeted per paper."""
    closes = bars.get("close", [])
    times = bars.get("time", [])
    if len(closes) < lookback + 30:
        return {"strategy": "TSMOM", "symbol": symbol, "status": "insufficient_data",
                "bars": len(closes)}

    spread = TYPICAL_SPREADS.get(symbol, 0.001)
    trades = []
    position = 0  # +1 long, -1 short, 0 flat
    entry_price = 0.0
    entry_lot = 1.0  # base unit; scalar applies on top

    for i in range(lookback, len(closes) - 1):
        # Compute signal at bar i using closes[:i+1]
        result = tsmom.compute(closes[:i + 1], lookback=lookback, vol_target=vol_target)
        signal = result["signal"]
        scalar = result["position_scalar"]

        # Walk forward: enter at next bar's open (closes[i+1] as proxy)
        next_close = closes[i + 1]

        # Position transition logic
        if signal != 0 and position == 0:
            # Enter
            entry_price = next_close + (spread if signal > 0 else -spread)
            position = signal
            entry_lot = scalar
            trades.append({
                "type": "open", "i": i + 1, "time": times[i + 1] if i + 1 < len(times) else 0,
                "side": "BUY" if signal > 0 else "SELL",
                "price": entry_price, "lot": scalar,
            })
        elif signal != position and position != 0:
            # Exit existing + reverse
            exit_price = next_close - (spread if position > 0 else -spread)
            pnl = (exit_price - entry_price) * position * entry_lot
            trades.append({
                "type": "close", "i": i + 1, "time": times[i + 1] if i + 1 < len(times) else 0,
                "exit_price": exit_price, "pnl": pnl,
            })
            # Reverse
            entry_price = next_close + (spread if signal > 0 else -spread)
            position = signal
            entry_lot = scalar
            trades.append({
                "type": "open", "i": i + 1, "time": times[i + 1] if i + 1 < len(times) else 0,
                "side": "BUY" if signal > 0 else "SELL",
                "price": entry_price, "lot": scalar,
            })

    # Close final position at last bar
    if position != 0 and trades:
        exit_price = closes[-1] - (spread if position > 0 else -spread)
        pnl = (exit_price - entry_price) * position * entry_lot
        trades.append({"type": "close", "i": len(closes) - 1,
                       "exit_price": exit_price, "pnl": pnl})

    return _summarize("TSMOM", symbol, trades, closes)


# ──────────────────────────────────────────────────────────────────────────────
# Pairs Backtest (Gatev, Goetzmann, Rouwenhorst 2006)
# ──────────────────────────────────────────────────────────────────────────────

def backtest_pairs(symbol_a: str, symbol_b: str, bars_a: dict, bars_b: dict,
                   formation_bars: int = 252, entry_z: float = 2.0,
                   exit_z: float = 0.0, max_hold_bars: int = 126) -> dict:
    """Walk-forward pairs backtest with dollar-neutral legs."""
    closes_a = bars_a.get("close", [])
    closes_b = bars_b.get("close", [])
    times = bars_a.get("time", [])
    n = min(len(closes_a), len(closes_b))
    if n < formation_bars + 30:
        return {"strategy": f"Pairs_{symbol_a}_{symbol_b}", "status": "insufficient_data",
                "bars": n}

    spread_a = TYPICAL_SPREADS.get(symbol_a, 0.001)
    spread_b = TYPICAL_SPREADS.get(symbol_b, 0.001)
    trades = []
    position = 0  # +1 = long A short B, -1 = short A long B, 0 = flat
    entry_a = 0.0
    entry_b = 0.0
    entry_i = 0

    for i in range(formation_bars, n - 1):
        # Use last formation_bars to compute spread σ
        result = pairs.compute_pair(
            closes_a[i - formation_bars + 1:i + 1],
            closes_b[i - formation_bars + 1:i + 1],
            formation_bars=formation_bars,
            entry_z=entry_z,
            exit_z=exit_z,
        )
        signal = result["signal"]
        zscore = result["zscore"]

        # Exit conditions
        if position != 0:
            held_for = i - entry_i
            should_exit = (
                signal == "EXIT"  # mean-reverted
                or held_for >= max_hold_bars  # max holding (paper: 6 months)
                or (position == 1 and zscore >= -exit_z)  # spread crossed exit threshold
                or (position == -1 and zscore <= exit_z)
            )
            if should_exit:
                # Close both legs
                exit_a = closes_a[i + 1] - (spread_a if position == 1 else -spread_a)
                exit_b = closes_b[i + 1] + (spread_b if position == 1 else -spread_b)
                # P&L: long A leg + short B leg (or reversed)
                if position == 1:  # was long A, short B
                    pnl_a = exit_a - entry_a
                    pnl_b = entry_b - exit_b
                else:  # was short A, long B
                    pnl_a = entry_a - exit_a
                    pnl_b = exit_b - entry_b
                # Normalize: P&L as % of entry prices (dollar-neutral simulation)
                pnl_pct = (pnl_a / entry_a + pnl_b / entry_b) * 100
                trades.append({
                    "type": "close", "i": i + 1, "time": times[i + 1] if i + 1 < len(times) else 0,
                    "pnl_pct": round(pnl_pct, 3), "held_bars": held_for,
                    "exit_zscore": zscore,
                })
                position = 0

        # Entry conditions
        if position == 0:
            if signal == "LONG_A_SHORT_B":
                entry_a = closes_a[i + 1] + spread_a
                entry_b = closes_b[i + 1] - spread_b
                position = 1
                entry_i = i + 1
                trades.append({"type": "open", "i": i + 1, "direction": "LONG_A_SHORT_B",
                               "zscore": zscore, "entry_a": entry_a, "entry_b": entry_b})
            elif signal == "SHORT_A_LONG_B":
                entry_a = closes_a[i + 1] - spread_a
                entry_b = closes_b[i + 1] + spread_b
                position = -1
                entry_i = i + 1
                trades.append({"type": "open", "i": i + 1, "direction": "SHORT_A_LONG_B",
                               "zscore": zscore, "entry_a": entry_a, "entry_b": entry_b})

    return _summarize_pairs(f"Pairs_{symbol_a}_{symbol_b}", trades)


# ──────────────────────────────────────────────────────────────────────────────
# Summary helpers
# ──────────────────────────────────────────────────────────────────────────────

def _summarize(strategy: str, symbol: str, trades: list, closes: list) -> dict:
    closes_only = [t for t in trades if t["type"] == "close"]
    pnls = [t["pnl"] for t in closes_only]
    if not pnls:
        return {"strategy": strategy, "symbol": symbol, "trades": 0,
                "verdict": "NO_TRADES"}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_profit / max(gross_loss, 1e-9), 2)
    win_rate = round(len(wins) / len(pnls) * 100, 1)

    # Max drawdown (cumulative P&L)
    cum_pnl, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        cum_pnl += p
        peak = max(peak, cum_pnl)
        max_dd = max(max_dd, peak - cum_pnl)

    # Verdict based on PF + trade count separately
    if len(pnls) < 5:
        verdict = "INSUFFICIENT_TRADES"
    elif profit_factor < 1.0:
        verdict = "UNPROFITABLE"
    elif profit_factor >= 2.0:
        verdict = "STRONG"
    elif profit_factor >= 1.3:
        verdict = "DECENT"
    else:
        verdict = "MARGINAL"

    return {
        "strategy": strategy,
        "symbol": symbol,
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": win_rate,
        "total_pnl_priceunits": round(total_pnl, 4),
        "profit_factor": profit_factor,
        "max_drawdown_priceunits": round(max_dd, 4),
        "avg_win": round(sum(wins) / max(len(wins), 1), 4),
        "avg_loss": round(sum(losses) / max(len(losses), 1), 4),
        "verdict": verdict,
        "bars_covered": len(closes),
    }


def _summarize_pairs(strategy: str, trades: list) -> dict:
    closes_only = [t for t in trades if t["type"] == "close"]
    pnls = [t["pnl_pct"] for t in closes_only]
    if not pnls:
        return {"strategy": strategy, "trades": 0, "verdict": "NO_TRADES"}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total = sum(pnls)
    pf = round(sum(wins) / max(abs(sum(losses)), 1e-9), 2)
    wr = round(len(wins) / len(pnls) * 100, 1)
    avg_hold = round(sum(t.get("held_bars", 0) for t in closes_only) / len(closes_only), 1)
    cum, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    if len(pnls) < 3:
        verdict = "INSUFFICIENT_TRADES"
    elif pf < 1.0:
        verdict = "UNPROFITABLE"
    elif pf >= 2.0:
        verdict = "STRONG"
    elif pf >= 1.3:
        verdict = "DECENT"
    else:
        verdict = "MARGINAL"
    return {
        "strategy": strategy,
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": wr,
        "total_return_pct": round(total, 3),
        "profit_factor": pf,
        "max_drawdown_pct": round(mdd, 3),
        "avg_hold_bars": avg_hold,
        "verdict": verdict,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="JTCC Academic Strategies Backtest")
    parser.add_argument("--years", type=int, default=3, help="Years of history (default 3)")
    parser.add_argument("--symbols", nargs="+",
                        default=["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"])
    args = parser.parse_args()

    bars_limit = args.years * 252 + 100  # ~252 trading days per year
    log.info("Backtest start — years=%d, bars=%d, symbols=%s",
             args.years, bars_limit, args.symbols)

    bars_by_symbol = {}
    for sym in args.symbols:
        d = _fetch_d1(sym, limit=bars_limit)
        if d and d.get("close"):
            bars_by_symbol[sym] = d
            log.info("  %s: %d D1 bars loaded", sym, len(d["close"]))

    report = {
        "generated_at": datetime.now().isoformat(),
        "years_covered": args.years,
        "tsmom_results": [],
        "pairs_results": [],
    }

    # TSMOM per symbol
    print()
    print("=" * 80)
    print("TSMOM RESULTS (Moskowitz, Ooi, Pedersen 2012)")
    print("=" * 80)
    for sym, bars in bars_by_symbol.items():
        lookback = 28 if sym == "BTCUSD" else 252
        result = backtest_tsmom(sym, bars, lookback=lookback)
        report["tsmom_results"].append(result)
        if result.get("trades", 0) > 0:
            print(f"  {sym:8s} | {result['trades']:3d} trades | "
                  f"WR {result['win_rate_pct']:5.1f}% | "
                  f"PF {result['profit_factor']:.2f} | "
                  f"MaxDD {result['max_drawdown_priceunits']:.2f} | "
                  f"VERDICT: {result['verdict']}")

    # Pairs
    print()
    print("=" * 80)
    print("PAIRS RESULTS (Gatev, Goetzmann, Rouwenhorst 2006)")
    print("=" * 80)
    pair_configs = [("XAUUSD", "XAGUSD"), ("EURUSD", "GBPUSD")]
    for a, b in pair_configs:
        if a in bars_by_symbol and b in bars_by_symbol:
            result = backtest_pairs(a, b, bars_by_symbol[a], bars_by_symbol[b])
            report["pairs_results"].append(result)
            if result.get("trades", 0) > 0:
                print(f"  {a}-{b}: {result['trades']} trades | "
                      f"WR {result['win_rate_pct']}% | "
                      f"PF {result['profit_factor']} | "
                      f"avg_hold {result['avg_hold_bars']}d | "
                      f"VERDICT: {result['verdict']}")
            else:
                print(f"  {a}-{b}: 0 trades (z-scores never crossed ±2σ) — VERDICT: NO_SIGNAL")

    # Save full report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"Full report: {REPORT_FILE}")

    # Promote-or-reject recommendation
    print()
    print("=" * 80)
    print("PROMOTION RECOMMENDATIONS")
    print("=" * 80)
    for r in report["tsmom_results"]:
        v = r.get("verdict", "")
        pf = r.get("profit_factor", 0)
        sym = r.get("symbol", "?")
        if v in ("STRONG", "DECENT"):
            print(f"  [PROMOTE]   TSMOM on {sym} -- PF {pf} -- {v}")
        elif v == "MARGINAL":
            print(f"  [KEEP-DEMO] TSMOM on {sym} -- PF {pf} -- {v}")
        elif v == "UNPROFITABLE":
            print(f"  [DISABLE]   TSMOM on {sym} -- PF {pf} -- {v}")
        elif v == "INSUFFICIENT_TRADES":
            print(f"  [SKIP]      TSMOM on {sym} -- {r.get('trades', 0)} trades -- need more data")
    for r in report["pairs_results"]:
        v = r.get("verdict", "")
        pf = r.get("profit_factor", 0)
        st = r.get("strategy", "?")
        if v in ("STRONG", "DECENT"):
            print(f"  [PROMOTE]   {st} -- PF {pf} -- {v}")
        elif v == "MARGINAL":
            print(f"  [KEEP-DEMO] {st} -- PF {pf} -- {v}")
        elif v == "UNPROFITABLE":
            print(f"  [DISABLE]   {st} -- PF {pf} -- {v}")
        elif v == "INSUFFICIENT_TRADES":
            print(f"  [SKIP]      {st} -- {r.get('trades', 0)} trades -- need more data")


if __name__ == "__main__":
    main()
