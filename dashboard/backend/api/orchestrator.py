"""Control-plane API — exposes the orchestrator's supervised process state.

Reads logs/_orchestrator_state.json (written by trading_agents/orchestrator.py)
so the dashboard can show what the single supervisor is running, how healthy each
process is, and how many times it has been auto-restarted.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
log = logging.getLogger("api.orchestrator")

_BASE_DIR = Path(__file__).resolve().parents[3]
_STATE = _BASE_DIR / "logs" / "_orchestrator_state.json"

# How stale the orchestrator's own heartbeat can be before we call it down.
# It writes every health_interval (~30s); allow 3x.
_ORCH_STALE = 100


@router.get("/orchestrator")
def get_orchestrator():
    if not _STATE.exists():
        return {
            "running": False,
            "reason": "no orchestrator state file — supervisor not started",
            "services": [],
            "summary": {"total": 0, "running": 0, "restarting": 0, "failed": 0},
        }

    try:
        data = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("orchestrator state unreadable: %s", e)
        return {"running": False, "reason": f"state unreadable: {e}",
                "services": [], "summary": {}}

    age = time.time() - _STATE.stat().st_mtime
    running = age < _ORCH_STALE
    services = data.get("services", [])

    summary = {
        "total": len(services),
        "running": sum(1 for s in services if s.get("status") == "running"),
        "starting": sum(1 for s in services if s.get("status") == "starting"),
        "restarting": sum(1 for s in services if s.get("status") in ("dead", "unhealthy")),
        "failed": sum(1 for s in services if s.get("status") == "failed"),
        "total_restarts": sum(int(s.get("restarts", 0)) for s in services),
    }

    return {
        "running": running,
        "orchestrator_pid": data.get("orchestrator_pid"),
        "state_age_seconds": round(age, 1),
        "updated_at": data.get("ts"),
        "services": services,
        "summary": summary,
    }
