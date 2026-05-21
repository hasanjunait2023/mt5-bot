"""Dev Agents status and trigger endpoints for the MT5 dashboard."""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import BASE_DIR

router = APIRouter()

MONITOR_STATE = BASE_DIR / "logs" / "dev_agents" / "_monitor_state.json"
REVIEW_LOG_DIR = BASE_DIR / "logs" / "dev_agents"
DEV_LEAD = BASE_DIR / "trading_agents" / "dev_agents" / "dev_lead.py"

# DevLead is an autonomous coding agent that edits the repo and spends API
# credits. It must NOT be reachable unauthenticated on a public deployment,
# so the trigger endpoint is opt-in via an explicit env flag.
TRIGGER_ENABLED = os.getenv("DASHBOARD_ENABLE_DEV_TRIGGER", "").lower() in ("1", "true", "yes")
TRIGGER_TIMEOUT_S = 300


class TriggerRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)


@router.get("/dev-agents/status")
def get_dev_agent_status():
    """Return latest MonitorAgent health state."""
    if not MONITOR_STATE.exists():
        return {"status": "no_data", "message": "MonitorAgent has not run yet"}
    try:
        return json.loads(MONITOR_STATE.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dev-agents/reviews")
def list_reviews():
    """List recent code review reports."""
    if not REVIEW_LOG_DIR.exists():
        return {"reviews": []}
    reports = sorted(
        REVIEW_LOG_DIR.glob("review_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:10]
    return {"reviews": [{"name": p.name, "modified": p.stat().st_mtime} for p in reports]}


@router.post("/dev-agents/trigger")
async def trigger_dev_agent(req: TriggerRequest):
    """Spawn DevLead with a task description. Returns the output.

    Disabled unless DASHBOARD_ENABLE_DEV_TRIGGER is set — see module note.
    """
    if not TRIGGER_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Dev trigger disabled. Set DASHBOARD_ENABLE_DEV_TRIGGER=1 to enable.",
        )
    if not DEV_LEAD.exists():
        raise HTTPException(status_code=503, detail="dev_lead.py not found")

    task = req.task.strip()
    if not task:
        raise HTTPException(status_code=422, detail="task must not be empty")

    try:
        # --task=<value> as a single argv token so a task starting with '-'
        # can't be reinterpreted as a flag by dev_lead.py's arg parser.
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(DEV_LEAD), f"--task={task}",
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TRIGGER_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise HTTPException(
                status_code=504,
                detail=f"DevLead timed out after {TRIGGER_TIMEOUT_S}s",
            )
        out = (stdout or stderr or b"").decode("utf-8", "replace")
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "output": out[:3000],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
