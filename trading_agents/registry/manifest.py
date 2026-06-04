"""Universal strategy registry — loads and validates manifest YAMLs.

Drop a new <name>.yaml into registry/strategies/ and it auto-registers.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("registry.manifest")

STRATEGIES_DIR = Path(__file__).parent / "strategies"
BASE_DIR = Path(__file__).parents[2]  # project root

# ── Global rules — NO strategy may exceed these ────────────────────────────
GLOBAL_RULES: dict[str, Any] = {
    "max_daily_dd_pct": 20.0,       # demo/paper limit; tighten for live
    "min_paper_trades": 20,
    "min_paper_pf": 1.3,
    "max_risk_pct_per_trade": 2.0,
    "no_trade_during_news": True,
    "max_concurrent_trades_total": 8,
}

_REQUIRED = {"name", "id", "mode", "state_file"}


def _validate(m: dict) -> list[str]:
    errors = []
    missing = _REQUIRED - set(m.keys())
    if missing:
        errors.append(f"Missing required fields: {missing}")
    if "risk" in m:
        dd = m["risk"].get("daily_dd_pct", 0)
        if dd > GLOBAL_RULES["max_daily_dd_pct"]:
            errors.append(
                f"daily_dd_pct {dd} exceeds global max {GLOBAL_RULES['max_daily_dd_pct']}"
            )
        rpt = m["risk"].get("pct_per_trade", 0)
        if rpt > GLOBAL_RULES["max_risk_pct_per_trade"]:
            errors.append(
                f"pct_per_trade {rpt} exceeds global max {GLOBAL_RULES['max_risk_pct_per_trade']}"
            )
    return errors


def load_all() -> list[dict]:
    """Load + validate all manifests from strategies/. Invalid ones are skipped."""
    manifests = []
    if not STRATEGIES_DIR.exists():
        log.warning("strategies dir not found: %s", STRATEGIES_DIR)
        return manifests

    for path in sorted(STRATEGIES_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("Failed to parse %s: %s", path.name, e)
            continue

        if not raw or not isinstance(raw, dict):
            continue

        errors = _validate(raw)
        if errors:
            log.warning("Manifest %s invalid: %s", path.name, errors)
            continue

        # Resolve state_file relative to project root
        raw["_state_path"] = BASE_DIR / raw["state_file"]
        raw["_source_file"] = str(path)
        manifests.append(raw)

    return manifests


def get(agent_id: str) -> dict | None:
    for m in load_all():
        if m.get("id") == agent_id:
            return m
    return None
