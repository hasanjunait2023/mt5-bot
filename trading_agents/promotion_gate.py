"""
Non-bypassable demo→LIVE promotion gate.

This is the single source of truth for "is an EA allowed to trade real
money". It is FAIL-CLOSED: missing or insufficient evidence => NOT allowed.
A human "YES" is necessary but NOT sufficient — the evidence below is
mandatory and cannot be routed around. Every code path that would flip an
EA to `live` MUST call can_go_live() first.

Evidence required (ALL must hold):
  1. Demo soak time   — days_on_demo        >= graduation_criteria.min_days_on_demo
  2. Demo sample size  — total_trades_on_demo >= graduation_criteria.min_trades
  3. Independent validation — latest EAValidator verdict == "PASS"
     (CONDITIONAL_PASS / FAIL / UNKNOWN / missing all block)
  4. Validation freshness — validator ran for THIS ea and has a tested_at
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("PromotionGate")

_BASE = Path(__file__).resolve().parent.parent          # repo root
_CONFIG   = Path(__file__).resolve().parent / "ea_agents" / "ea_agents_config.json"
_COACH    = _BASE / "logs" / "ea_agents" / "_coach_state.json"
_VALIDATOR = _BASE / "logs" / "ea_agents" / "_validator_results.json"

# Conservative defaults if config is missing — err toward blocking.
_DEFAULTS = {
    "min_days_on_demo": 5,
    "min_trades": 40,
    "min_win_rate_pct": 55,
    "min_profit_factor": 1.4,
    "max_daily_dd_pct": 3.0,
}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _criteria() -> dict:
    cfg = _read(_CONFIG).get("graduation_criteria", {})
    return {**_DEFAULTS, **cfg}


def can_go_live(ea_name: str) -> tuple[bool, list[str]]:
    """
    Return (allowed, reasons). `allowed` is True only if EVERY evidence
    check passes. `reasons` lists each failed (or, if allowed, each passed)
    check so the decision is auditable in the Telegram notice.
    """
    crit = _criteria()
    reasons: list[str] = []
    ok = True

    # ── 1 & 2: demo soak + sample size (from coach state) ────────────────
    coach = _read(_COACH).get("eas", {}).get(ea_name)
    if not coach:
        return False, [f"No demo track record for {ea_name} "
                       f"(coach state missing) — cannot prove safety"]

    days = coach.get("days_on_demo", 0)
    trades = coach.get("total_trades_on_demo", 0)
    if days < crit["min_days_on_demo"]:
        ok = False
        reasons.append(f"Demo soak too short: {days}d < "
                        f"{crit['min_days_on_demo']}d required")
    else:
        reasons.append(f"Demo soak OK: {days}d")

    if trades < crit["min_trades"]:
        ok = False
        reasons.append(f"Too few demo trades: {trades} < "
                        f"{crit['min_trades']} required")
    else:
        reasons.append(f"Demo sample OK: {trades} trades")

    # ── 3 & 4: independent validator verdict, for THIS ea, fresh ─────────
    val = _read(_VALIDATOR)
    if val.get("ea") != ea_name or not val.get("tested_at"):
        ok = False
        reasons.append(f"No fresh EAValidator result for {ea_name} — "
                        f"run full validation before promotion")
    else:
        verdict = str(val.get("overall_verdict", "UNKNOWN")).upper()
        if verdict != "PASS":
            ok = False
            reasons.append(f"Validator verdict is {verdict} "
                           f"(must be PASS, not CONDITIONAL_PASS/FAIL)")
        else:
            reasons.append(f"Validator PASS ({val.get('tested_at')})")

    if ok:
        log.info("can_go_live(%s) = ALLOWED", ea_name)
    else:
        log.warning("can_go_live(%s) = BLOCKED: %s", ea_name, reasons)
    return ok, reasons
