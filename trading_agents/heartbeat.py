"""
Heartbeat helper — for components that don't already write a _state.json.

Trading agents (MTF/JTCC/Iconic/Scalp) already persist a state file with a fresh
timestamp every loop; the orchestrator uses that file's mtime as their liveness
signal, so they need no change. Use this only for the management/dev agents
(scout, coach, supervisor, …) so the orchestrator can tell they're alive.

    from trading_agents.heartbeat import beat
    beat("strategy_scout", status="scanning")
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_HB_DIR = Path(__file__).resolve().parents[1] / "logs" / "heartbeats"


def beat(component_id: str, status: str = "ok", extra: dict | None = None) -> None:
    """Write/refresh logs/heartbeats/<id>.json. Never raises."""
    try:
        _HB_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": component_id,
            "pid": os.getpid(),
            "status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            payload["extra"] = extra
        (_HB_DIR / f"{component_id}.json").write_text(
            json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def path_for(component_id: str) -> Path:
    return _HB_DIR / f"{component_id}.json"
