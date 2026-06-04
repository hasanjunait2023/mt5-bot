"""Command Hub API — aggregates all registered strategy systems."""
from __future__ import annotations

import sys
import logging
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
log = logging.getLogger("api.hub")

# Ensure project root is on path so registry can be imported
_BASE_DIR = Path(__file__).resolve().parents[3]
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))


def _load_registry():
    try:
        from trading_agents.registry.manifest import load_all, GLOBAL_RULES
        from trading_agents.registry.schema import normalize
        return load_all, normalize, GLOBAL_RULES
    except Exception as e:
        log.warning("Registry unavailable: %s", e)
        return None, None, {}


@router.get("/hub")
def get_hub():
    load_all, normalize, global_rules = _load_registry()
    if load_all is None:
        return {"systems": [], "summary": {}, "global_rules": {}, "error": "registry unavailable"}

    manifests = load_all()
    systems = []

    for m in manifests:
        try:
            entry = normalize(m, _BASE_DIR)
            systems.append(entry)
        except Exception as e:
            log.warning("Normalize failed for %s: %s", m.get("id"), e)
            systems.append({
                "name": m.get("name", "Unknown"),
                "id": m.get("id", "unknown"),
                "mode": m.get("mode", "unknown"),
                "status": "error",
                "color": "neutral",
                "group": "other",
                "description": str(e),
                "dashboard_page": "/",
                "symbols": [],
                "account": {"balance": None, "equity": None, "daily_pnl": None, "daily_dd_pct": None},
                "performance": {"total_trades": 0, "win_rate_pct": None, "profit_factor": None, "total_pnl": None},
                "health": {"stale": True, "mt5_connected": False, "open_positions": 0, "issues": [], "last_heartbeat": None},
                "paper_gate": None,
                "risk": {},
            })

    # Build summary
    running = [s for s in systems if s["status"] == "running"]
    halted  = [s for s in systems if s["status"] == "halted"]
    stale   = [s for s in systems if s["status"] in ("stale", "stopped", "error")]
    live    = [s for s in systems if s["mode"] == "live"]
    paper   = [s for s in systems if s["mode"] in ("paper", "dry-run")]

    combined_pnl = sum(
        s["account"]["daily_pnl"]
        for s in systems
        if s["account"].get("daily_pnl") is not None
    )

    max_dd = max(
        (s["account"]["daily_dd_pct"] or 0.0 for s in systems),
        default=0.0,
    )

    any_critical = max_dd >= global_rules.get("max_daily_dd_pct", 20.0) * 0.8

    return {
        "systems": systems,
        "summary": {
            "total_systems": len(systems),
            "running_count": len(running),
            "live_count": len(live),
            "paper_count": len(paper),
            "halted_count": len(halted),
            "stale_count": len(stale),
            "combined_daily_pnl": round(combined_pnl, 2),
            "max_daily_dd_pct": round(max_dd, 2),
            "any_critical": any_critical,
        },
        "global_rules": global_rules,
    }
