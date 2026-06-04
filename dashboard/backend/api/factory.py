"""Strategy Factory API — job pipeline state, artifacts, and gate approvals.

Read endpoints mirror api/scalp.py. Write endpoints drive the same
trading_agents.factory.state functions the runner uses, so the dashboard is the
reliable approval channel (Telegram inbound is best-effort).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from trading_agents.factory import state as fst  # noqa: E402

_ARTIFACT_KEYS = {
    "plan": "build_plan", "spec": "merged_spec", "discovery": "discovery_qa",
    "deep": "deep_qa", "backtest": "backtest_report", "transcript": "transcript",
    "video_spec": "video_spec",
}


@router.get("/factory/jobs")
def list_jobs():
    """Lightweight job summaries (newest first) for the pipeline board."""
    return {"jobs": fst.list_jobs()}


@router.get("/factory/jobs/{job_id}")
def get_job(job_id: str):
    job = fst.load_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    # Flag which artifacts are actually present + which gate is awaiting.
    arts = job.get("artifacts", {})
    job["_artifacts_present"] = {name: bool(arts.get(key) and Path(arts[key]).exists())
                                 for name, key in _ARTIFACT_KEYS.items()}
    pending = [g for g, a in job.get("approvals", {}).items() if a.get("state") == "pending"]
    job["_pending_gate"] = pending[0] if pending else None
    return job


@router.get("/factory/jobs/{job_id}/artifact")
def get_artifact(job_id: str, name: str):
    job = fst.load_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    key = _ARTIFACT_KEYS.get(name)
    if not key:
        raise HTTPException(400, f"unknown artifact '{name}'")
    path = job.get("artifacts", {}).get(key)
    if not path or not Path(path).exists():
        raise HTTPException(404, f"artifact '{name}' not available")
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    return {"name": name, "path": path, "content": text[:200_000]}


@router.post("/factory/ingest")
def ingest(payload: dict = Body(...)):
    url = (payload.get("youtube_url") or "").strip()
    if not url:
        raise HTTPException(400, "youtube_url required")
    job = fst.new_job(url, chat_id="dashboard",
                      notebook_url=(payload.get("notebook_url") or "").strip(),
                      title=(payload.get("title") or "").strip())
    return {"ok": True, "job_id": job["job_id"], "job": job}


@router.post("/factory/jobs/{job_id}/approve")
def approve(job_id: str, payload: dict = Body(default={})):
    gate = payload.get("gate")
    if gate not in ("plan", "backtest", "live"):
        raise HTTPException(400, "gate must be plan|backtest|live")
    job = fst.record_approval(job_id, gate, approved=True,
                              by=payload.get("by", "dashboard"),
                              note=payload.get("note", ""))
    if job is None:
        raise HTTPException(404, "job not found")
    return {"ok": True, "stage": job["stage"], "status": job["status"]}


@router.post("/factory/jobs/{job_id}/reject")
def reject(job_id: str, payload: dict = Body(default={})):
    gate = payload.get("gate")
    if gate not in ("plan", "backtest", "live"):
        raise HTTPException(400, "gate must be plan|backtest|live")
    job = fst.record_approval(job_id, gate, approved=False,
                              by=payload.get("by", "dashboard"),
                              note=payload.get("note", ""))
    if job is None:
        raise HTTPException(404, "job not found")
    return {"ok": True, "status": job["status"]}


@router.post("/factory/jobs/{job_id}/requeue")
def requeue(job_id: str):
    job = fst.requeue(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {"ok": True, "stage": job["stage"], "status": job["status"]}
