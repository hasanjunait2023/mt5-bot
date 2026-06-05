"""Strategy Factory job state — the single owner of the job JSON schema.

One job = one strategy candidate, persisted as logs/factory/<job_id>.json with a
per-job artifact dir logs/factory/<job_id>/. The runner re-dispatches by `stage`
each tick, so every field here must be enough to resume a multi-day job after a
restart. All writes are atomic (temp + os.replace).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
FACTORY_DIR = BASE_DIR / "logs" / "factory"
INDEX_PATH = FACTORY_DIR / "_index.json"

SCHEMA_VERSION = "factory_v1"

# ── Pipeline stages (ordered, strategy path) ──────────────────────────────────
INGEST = "INGEST"
CLASSIFY = "CLASSIFY"
NON_STRATEGY_PLAN = "NON_STRATEGY_PLAN"
RESEARCH_NB = "RESEARCH_NB"
RESEARCH_VIDEO = "RESEARCH_VIDEO"
MERGE_SPEC = "MERGE_SPEC"
BUILD_PLAN = "BUILD_PLAN"
GATE_PLAN = "GATE_PLAN"
CODEGEN = "CODEGEN"
BACKTEST = "BACKTEST"
GATE_BACKTEST = "GATE_BACKTEST"
OPTIMIZE = "OPTIMIZE"
DEMO_DEPLOY = "DEMO_DEPLOY"
SOAK = "SOAK"
GATE_LIVE = "GATE_LIVE"
DONE = "DONE"
REJECTED = "REJECTED"
FAILED = "FAILED"

# Stage that follows each stage on success (strategy path). Gates and terminal
# stages are NOT in here — they are advanced by the dashboard/handlers explicitly.
NEXT_STAGE = {
    INGEST: CLASSIFY,
    RESEARCH_NB: RESEARCH_VIDEO,
    RESEARCH_VIDEO: MERGE_SPEC,
    MERGE_SPEC: BUILD_PLAN,
    BUILD_PLAN: GATE_PLAN,
    CODEGEN: BACKTEST,
    BACKTEST: GATE_BACKTEST,
    OPTIMIZE: DEMO_DEPLOY,
    DEMO_DEPLOY: SOAK,
}

# Gate name -> the stage to resume at once approved.
GATE_RESUME = {
    "plan": CODEGEN,            # after GATE_PLAN, strategy jobs build code
    "backtest": OPTIMIZE,       # after GATE_BACKTEST, optimize then deploy
    "live": GATE_LIVE,          # GATE_LIVE handler runs promotion_gate then DONE
}

# Status values
RUNNING = "RUNNING"
WAITING_APPROVAL = "WAITING_APPROVAL"
# plus FAILED / DONE / REJECTED (reuse the stage constants as status too)

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(3)}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def job_path(job_id: str) -> Path:
    return FACTORY_DIR / f"{job_id}.json"


def artifact_dir(job_id: str) -> Path:
    d = FACTORY_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── CRUD ──────────────────────────────────────────────────────────────────────

def new_job(youtube_url: str, *, chat_id: str = "", notebook_url: str = "",
            title: str = "") -> dict:
    """Create a fresh job at INGEST and persist it. Returns the job dict."""
    job_id = "SF-" + datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3)
    job = {
        "job_id": job_id,
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "updated_at": _now(),
        "source": {
            "youtube_url": youtube_url,
            "notebook_url": notebook_url,
            "video_id": "",
            "title": title,
            "channel": "",
            "description": "",
            "duration_s": 0,
        },
        "chat_id": chat_id,
        "stage": INGEST,
        "prev_stage": "",
        "status": RUNNING,
        "strategy_id": None,
        "is_strategy": None,
        "classification_reason": "",
        "retries": {"codegen": 0, "optimize_rounds": 0, "improve_code": 0},
        "approvals": {
            "plan": {"state": "none", "by": None, "at": None, "note": ""},
            "backtest": {"state": "none", "by": None, "at": None, "note": ""},
            "live": {"state": "none", "by": None, "at": None, "note": ""},
        },
        "artifacts": {},
        "metrics": {"backtest": {}, "optimize": {}, "soak": {}},
        "history": [],
        "error": None,
    }
    append_history(job, INGEST, "job created")
    save_job(job)
    return job


def new_job_from_text(research_text: str, *, title: str = "", source_kind: str = "text",
                      source_ref: str = "", symbols: Optional[list[str]] = None,
                      chat_id: str = "") -> dict:
    """Create a spec-first job for sources that have no YouTube URL (LLM-generated
    ideas, research papers, web/blog articles).

    The raw research text is written to the job's `transcript` artifact so the
    normal MERGE_SPEC stage synthesizes a canonical spec from it. The job starts
    at MERGE_SPEC — INGEST/CLASSIFY/RESEARCH are skipped (already a known strategy).
    """
    job_id = "SF-" + datetime.now().strftime("%Y%m%d") + "-" + secrets.token_hex(3)
    job = {
        "job_id": job_id,
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "updated_at": _now(),
        "source": {
            "youtube_url": "",
            "notebook_url": "",
            "video_id": "",
            "title": title or "Strategy idea",
            "channel": source_kind,
            "description": research_text[:1500],
            "duration_s": 0,
            "kind": source_kind,
            "ref": source_ref,
        },
        "chat_id": chat_id,
        "stage": MERGE_SPEC,
        "prev_stage": "",
        "status": RUNNING,
        "strategy_id": None,
        "is_strategy": True,
        "classification_reason": f"spec-first ({source_kind})",
        "retries": {"codegen": 0, "optimize_rounds": 0, "improve_code": 0},
        "approvals": {
            "plan": {"state": "none", "by": None, "at": None, "note": ""},
            "backtest": {"state": "none", "by": None, "at": None, "note": ""},
            "live": {"state": "none", "by": None, "at": None, "note": ""},
        },
        "artifacts": {},
        "metrics": {"backtest": {}, "optimize": {}, "soak": {}},
        "history": [],
        "error": None,
    }
    if symbols:
        job["source"]["symbols_hint"] = symbols
    # Stash the research text where merge_spec reads it.
    art = artifact_dir(job_id)
    tpath = art / "transcript.txt"
    tpath.write_text(research_text, encoding="utf-8")
    job["artifacts"]["transcript"] = str(tpath)
    append_history(job, MERGE_SPEC, f"spec-first job created ({source_kind})")
    save_job(job)
    return job


def load_job(job_id: str) -> Optional[dict]:
    p = job_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_job(job: dict) -> None:
    job["updated_at"] = _now()
    _atomic_write(job_path(job["job_id"]), job)
    _update_index(job)


def list_jobs() -> list[dict]:
    """Lightweight job summaries for the dashboard, newest first."""
    idx = _read_index()
    return sorted(idx.values(), key=lambda j: j.get("created_at", ""), reverse=True)


# ── Transitions ───────────────────────────────────────────────────────────────

def append_history(job: dict, stage: str, msg: str) -> None:
    job.setdefault("history", []).append({"at": _now(), "stage": stage, "msg": msg})
    # keep history bounded
    if len(job["history"]) > 200:
        job["history"] = job["history"][-200:]


def advance(job: dict, stage: str, msg: str = "") -> None:
    """Move job to `stage` (RUNNING) and persist."""
    job["prev_stage"] = job.get("stage")
    job["stage"] = stage
    job["status"] = RUNNING
    append_history(job, stage, msg or f"-> {stage}")
    save_job(job)


def set_status(job: dict, status: str, msg: str = "") -> None:
    job["status"] = status
    if status in (FAILED, REJECTED, DONE):
        job["stage"] = status
    append_history(job, job.get("stage", "?"), msg or f"status={status}")
    save_job(job)


def fail(job: dict, error: str) -> None:
    job["error"] = error
    set_status(job, FAILED, f"FAILED: {error[:200]}")


def wait_for_gate(job: dict, gate: str, msg: str = "") -> None:
    """Pause the job at a gate; the dashboard/Telegram advances it."""
    job["approvals"][gate]["state"] = "pending"
    job["status"] = WAITING_APPROVAL
    append_history(job, job.get("stage", "?"), msg or f"awaiting approval: {gate}")
    save_job(job)


def record_approval(job_id: str, gate: str, *, approved: bool,
                    by: str = "", note: str = "") -> Optional[dict]:
    """Approve/reject a gate. On approve, resume at the gate's next stage; on
    reject, mark the job REJECTED. Returns the updated job (or None if missing).
    """
    with _LOCK:
        job = load_job(job_id)
        if job is None:
            return None
        if gate not in job["approvals"]:
            return job
        ap = job["approvals"][gate]
        ap["state"] = "approved" if approved else "rejected"
        ap["by"] = by
        ap["at"] = _now()
        ap["note"] = note
        if approved:
            resume = GATE_RESUME.get(gate, job.get("stage"))
            advance(job, resume, f"gate '{gate}' approved by {by or '?'}")
        else:
            set_status(job, REJECTED, f"gate '{gate}' rejected by {by or '?'}")
        return job


def requeue(job_id: str) -> Optional[dict]:
    """Re-arm a FAILED job to retry its current (failed) stage."""
    with _LOCK:
        job = load_job(job_id)
        if job is None:
            return None
        if job.get("status") != FAILED and job.get("stage") != FAILED:
            return job
        job["error"] = None
        stage = job.get("prev_stage") or CLASSIFY
        advance(job, stage, "requeued")
        return job


# ── Strategy ID allocation (factory reserves GS50+) ──────────────────────────

def alloc_strategy_id() -> str:
    """Return the next free GS id >= 50, considering hand-written strategies,
    generated modules, and ids already claimed by other jobs. Single-process
    (runner) caller — guarded by the module lock.
    """
    with _LOCK:
        used: set[int] = set()
        # hand-written + already-loaded strategies
        try:
            from trading_agents.scalp import backtest as _bt
            for k in _bt.STRATEGIES:
                if k.startswith("GS") and k[2:].isdigit():
                    used.add(int(k[2:]))
        except Exception:
            pass
        # generated module files
        gen = BASE_DIR / "trading_agents" / "scalp" / "generated"
        if gen.exists():
            for f in gen.glob("gs*_*.py"):
                head = f.stem.split("_")[0]  # gs50
                if head[2:].isdigit():
                    used.add(int(head[2:]))
        # ids claimed by other jobs
        for j in _read_index().values():
            sid = j.get("strategy_id")
            if sid and sid.startswith("GS") and sid[2:].isdigit():
                used.add(int(sid[2:]))
        n = 50
        while n in used:
            n += 1
        return f"GS{n}"


# ── Index (cheap dashboard listing) ───────────────────────────────────────────

def _read_index() -> dict:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _update_index(job: dict) -> None:
    idx = _read_index()
    idx[job["job_id"]] = {
        "job_id": job["job_id"],
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "stage": job.get("stage"),
        "status": job.get("status"),
        "is_strategy": job.get("is_strategy"),
        "strategy_id": job.get("strategy_id"),
        "title": job.get("source", {}).get("title") or job.get("source", {}).get("youtube_url", ""),
        "youtube_url": job.get("source", {}).get("youtube_url", ""),
        "verdict": job.get("metrics", {}).get("backtest", {}).get("verdict", ""),
    }
    _atomic_write(INDEX_PATH, idx)
