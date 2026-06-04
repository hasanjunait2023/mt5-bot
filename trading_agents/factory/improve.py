"""Improvement thresholds + bounded "learn from mistakes" code patching.

Two levers (params handled by optimize.py):
  - should_soak / ready_for_live: the metric gates.
  - improve_via_code: feed a backtest-failure diagnosis back to codegen and
    regenerate the strategy. Bounded by job.retries['improve_code'] (<=2).
"""
from __future__ import annotations

import json
import logging

from trading_agents.factory import codegen as cg

log = logging.getLogger("factory.improve")

# Auto-proceed-to-soak gate (after optimize).
SOAK_PF = 1.5
SOAK_TRADES = 30
SOAK_OOS_PF = 1.3
SOAK_OOS_TRADES = 6
# Minimum to bother soaking at all.
MIN_DEPLOY_PF = 1.0
# Ready-for-real-money gate (human + promotion_gate also required).
LIVE_PF = 1.4
LIVE_TRADES = 40
LIVE_DAYS = 5

MAX_CODE_ROUNDS = 2


def should_soak(full: dict, oos_pf) -> bool:
    pf = full.get("profit_factor", 0) or 0
    tr = full.get("trades", 0) or 0
    if pf >= SOAK_PF and tr >= SOAK_TRADES:
        if oos_pf is None or oos_pf >= SOAK_OOS_PF:
            return True
    return False


def deployable(full: dict) -> bool:
    """At least break-even-ish and trades — worth a paper soak even if below the
    auto-soak bar (soak + GATE_LIVE protect real money)."""
    return (full.get("profit_factor", 0) or 0) >= MIN_DEPLOY_PF and (full.get("trades", 0) or 0) >= 10


def ready_for_live(soak: dict) -> tuple[bool, list[str]]:
    reasons = []
    pf = soak.get("pf", 0) or 0
    tr = soak.get("trades", 0) or 0
    days = soak.get("days", 0) or 0
    if pf < LIVE_PF:
        reasons.append(f"soak PF {pf} < {LIVE_PF}")
    if tr < LIVE_TRADES:
        reasons.append(f"soak trades {tr} < {LIVE_TRADES}")
    if days < LIVE_DAYS:
        reasons.append(f"soak days {days} < {LIVE_DAYS}")
    return (not reasons), reasons


def _diagnose(full: dict) -> str:
    bits = [f"verdict={full.get('verdict')}", f"PF={full.get('profit_factor')}",
            f"WR={full.get('win_rate_pct')}%", f"trades={full.get('trades')}",
            f"maxDD={full.get('max_drawdown')}",
            f"avg_win={full.get('avg_win')}", f"avg_loss={full.get('avg_loss')}"]
    rej = full.get("rejections")
    if rej:
        bits.append(f"rejections={rej}")
    hints = []
    pf = full.get("profit_factor", 0) or 0
    wr = full.get("win_rate_pct", 0) or 0
    tr = full.get("trades", 0) or 0
    if tr < 15:
        hints.append("Too few trades — loosen the entry filter or widen the session window.")
    if wr and wr < 35:
        hints.append("Low win-rate — entry likely too early; add a confirmation candle/indicator.")
    if pf and pf < 1.0:
        hints.append("Unprofitable — tighten entries, improve SL placement, or raise RR.")
    if (full.get("avg_loss") or 0) and abs(full.get("avg_loss")) > (full.get("avg_win") or 0):
        hints.append("Losses bigger than wins — SL too wide or TP too far; rebalance RR.")
    return "; ".join(bits) + "\nFix hints: " + (" ".join(hints) or "make entries more selective.")


def improve_via_code(job: dict, spec: dict, full: dict) -> dict:
    """Regenerate the strategy with a failure diagnosis appended to the spec.
    Bounded by MAX_CODE_ROUNDS. Returns the codegen result (or skipped)."""
    rounds = job["retries"].get("improve_code", 0)
    if rounds >= MAX_CODE_ROUNDS:
        return {"ok": False, "reason": "code-improve budget exhausted", "skipped": True}
    job["retries"]["improve_code"] = rounds + 1

    diagnosis = _diagnose(full)
    log.info("[improve] %s code round %d: %s", job.get("strategy_id"), rounds + 1, diagnosis)
    spec2 = dict(spec)
    spec2["notes"] = (spec.get("notes", "") +
                      f"\n\nPREVIOUS BACKTEST FELL SHORT — improve it. Diagnosis: {diagnosis}")
    spec2["_improve_round"] = rounds + 1
    # Force a fresh code file name so a stale broken one isn't reused.
    return cg.generate_strategy(job, spec=spec2)
