"""
System Agents API — surfaces every agent system on the dashboard.

Reads the runtime state files written by the Dev team, EA lifecycle team,
Supervisor, and Strategy Scout so the frontend can show their activity and
reports in one place.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from core.config import BASE_DIR

router = APIRouter()

# ── State file locations ──────────────────────────────────────────────────────
DEV_MONITOR     = BASE_DIR / "logs" / "dev_agents" / "_monitor_state.json"
DEV_LOG_DIR     = BASE_DIR / "logs" / "dev_agents"
EA_GUARDIAN     = BASE_DIR / "logs" / "ea_agents" / "_guardian_state.json"
EA_COACH        = BASE_DIR / "logs" / "ea_agents" / "_coach_state.json"
EA_VALIDATOR    = BASE_DIR / "logs" / "ea_agents" / "_validator_results.json"
SUPERVISOR_RPT  = BASE_DIR / "logs" / "supervisor_report.json"
SUPERVISOR_HIST = BASE_DIR / "logs" / "supervisor_history.json"
SCOUT_STATE     = BASE_DIR / "trading_agents" / "strategy_scout" / "_scout_state.json"
LLM_METRICS     = BASE_DIR / "logs" / "agent_metrics.jsonl"
INCIDENTS       = BASE_DIR / "logs" / "_incidents.json"
KILL_FLAG       = BASE_DIR / "mt5_bridge" / "_kill_switch.json"
STALLED_JSON    = BASE_DIR / "logs" / "_stalled_agents.json"
PENDING_MD      = BASE_DIR / "PENDING.md"

# Overview hits a dozen files + two globs; the frontend polls it every 10s per
# open tab. A short TTL cache keeps repeated polls off the disk.
_CACHE_TTL_S = 3.0
_cache_lock = threading.Lock()
_cache: dict | None = None
_cache_at = 0.0


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _age_minutes(path: Path) -> float | None:
    if not path.exists():
        return None
    return round((time.time() - path.stat().st_mtime) / 60, 1)


def _status(age_min: float | None, stale_after_min: float) -> str:
    """running = fresh, warning = stale, offline = never ran."""
    if age_min is None:
        return "offline"
    if age_min <= stale_after_min:
        return "running"
    return "warning"


def _build_overview() -> dict:
    # ── Dev team ──────────────────────────────────────────────────────────────
    dev_monitor = _read(DEV_MONITOR) or {}
    dev_age = _age_minutes(DEV_MONITOR)
    reviews, debugs = [], []
    if DEV_LOG_DIR.exists():
        for p in sorted(DEV_LOG_DIR.glob("review_*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:8]:
            reviews.append({"name": p.name, "modified": p.stat().st_mtime})
        for p in sorted(DEV_LOG_DIR.glob("debug_*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:8]:
            debugs.append({"name": p.name, "modified": p.stat().st_mtime})

    dev = {
        "status": _status(dev_age, 720),  # dev monitor is on-demand; 12h tolerance
        "last_run_minutes_ago": dev_age,
        "monitor_summary": dev_monitor.get("summary", "No monitor run yet"),
        "monitor_anomaly": dev_monitor.get("anomaly", False),
        "monitor_level": dev_monitor.get("level", "INFO"),
        "recent_reviews": reviews,
        "recent_debug_reports": debugs,
    }

    # ── EA lifecycle team ─────────────────────────────────────────────────────
    guardian = _read(EA_GUARDIAN) or {}
    coach = _read(EA_COACH) or {}
    validator = _read(EA_VALIDATOR) or {}
    g_age = _age_minutes(EA_GUARDIAN)

    ea_stages, pending = {}, []
    for ea_name, ea_data in (coach.get("eas", {}) or {}).items():
        ea_stages[ea_name] = ea_data.get("lifecycle_stage", "unknown")
        if ea_data.get("pending_question"):
            pending.append({
                "ea": ea_name,
                "question": ea_data["pending_question"].get("question", ""),
                "asked_at": ea_data["pending_question"].get("asked_at", ""),
            })

    ea = {
        "guardian": {
            "status": _status(g_age, 10),  # guardian polls every 60s
            "last_check_minutes_ago": g_age,
            "anomalies_found": guardian.get("anomalies_found", 0),
            "details": guardian.get("details", {}),
            "account": guardian.get("account", {}),
        },
        "coach": {
            "ea_stages": ea_stages,
            "pending_decisions": pending,
            "last_updated": coach.get("updated_at"),
        },
        "validator": {
            "ea": validator.get("ea"),
            "overall_verdict": validator.get("overall_verdict"),
            "compatible_pairs": validator.get("compatible_pairs", []),
            "incompatible_pairs": validator.get("incompatible_pairs", []),
            "recommendation": validator.get("recommendation", ""),
            "tested_at": validator.get("tested_at"),
        },
    }

    # ── Supervisor ────────────────────────────────────────────────────────────
    sup = _read(SUPERVISOR_RPT) or {}
    sup_hist = _read(SUPERVISOR_HIST) or []
    sup_age = _age_minutes(SUPERVISOR_RPT)
    supervisor = {
        "status": _status(sup_age, 720),  # runs every 10h
        "last_audit_minutes_ago": sup_age,
        "overall_status": sup.get("overall_status", "UNKNOWN"),
        "summary": sup.get("summary", "No audit run yet"),
        "issues_found": sup.get("issues_found", 0),
        "issues": sup.get("issues", []),
        "resolved": sup.get("resolved", []),
        "unresolved": sup.get("unresolved", []),
        "next_action": sup.get("next_action", ""),
        "history": sup_hist[-10:] if isinstance(sup_hist, list) else [],
    }

    # ── Strategy Scout ────────────────────────────────────────────────────────
    scout_state = _read(SCOUT_STATE) or {}
    scout_age = _age_minutes(SCOUT_STATE)
    ideas = scout_state.get("ideas", {}) or {}
    stage_counts: dict[str, int] = {}
    for rec in ideas.values():
        st = rec.get("stage", "UNKNOWN")
        stage_counts[st] = stage_counts.get(st, 0) + 1
    recent_ideas = sorted(
        ideas.values(), key=lambda r: r.get("last_update", ""), reverse=True
    )[:10]

    scout = {
        "status": _status(scout_age, 600),  # runs every 8h
        "last_cycle_minutes_ago": scout_age,
        "cycles": scout_state.get("cycles", 0),
        "scorecard": scout_state.get("scorecard", {}),
        "stage_counts": stage_counts,
        "total_ideas": len(ideas),
        "recent_ideas": recent_ideas,
    }

    return {"dev": dev, "ea": ea, "supervisor": supervisor, "scout": scout}


@router.get("/system-agents/overview")
def system_agents_overview():
    """Unified snapshot of every agent system for the dashboard (3s cached)."""
    global _cache, _cache_at
    now = time.time()
    with _cache_lock:
        if _cache is not None and (now - _cache_at) < _CACHE_TTL_S:
            return _cache
    fresh = _build_overview()
    with _cache_lock:
        _cache = fresh
        _cache_at = time.time()
    return fresh


@router.get("/system-agents/report")
def get_report(name: str = Query(..., min_length=1, max_length=128)):
    """Read a single dev-team report markdown file by name (safe-listed dir)."""
    # prevent path traversal — only allow files directly inside the dev log dir
    target = DEV_LOG_DIR / Path(name).name
    if not target.exists() or target.suffix != ".md":
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        return {"name": target.name, "content": target.read_text(encoding="utf-8")[:20000]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system-agents/llm")
def system_agents_llm():
    """Per-agent LLM telemetry: which model/backend served, fallback rate,
    error rate, latency, recency. Surfaces silent degradation (NVIDIA
    fallback creeping up = Claude flaking) before it fails loudly."""
    agents: dict = {}
    try:
        if LLM_METRICS.exists():
            lines = LLM_METRICS.read_text(encoding="utf-8").splitlines()[-3000:]
            for ln in lines:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                a = e.get("agent", "?")
                g = agents.setdefault(a, {
                    "agent": a, "calls": 0, "nvidia": 0, "errors": 0,
                    "lat_sum": 0, "last_ts": None, "last_model": None,
                    "last_backend": None,
                })
                g["calls"] += 1
                if e.get("backend") == "nvidia":
                    g["nvidia"] += 1
                if not e.get("ok", True):
                    g["errors"] += 1
                g["lat_sum"] += e.get("latency_ms", 0)
                g["last_ts"] = e.get("ts")
                g["last_model"] = e.get("model")
                g["last_backend"] = e.get("backend")
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    out = []
    for g in agents.values():
        c = g["calls"] or 1
        last_min = None
        if g["last_ts"]:
            try:
                last_min = round(
                    (now - datetime.fromisoformat(g["last_ts"])).total_seconds() / 60, 1)
            except Exception:
                pass
        out.append({
            "agent": g["agent"],
            "calls": g["calls"],
            "last_model": g["last_model"],
            "last_backend": g["last_backend"],
            "fallback_pct": round(g["nvidia"] / c * 100, 1),
            "error_pct": round(g["errors"] / c * 100, 1),
            "avg_latency_ms": round(g["lat_sum"] / c),
            "last_run_minutes_ago": last_min,
        })
    out.sort(key=lambda x: (-x["fallback_pct"], -x["calls"]))
    return {"agents": out, "total_calls": sum(a["calls"] for a in out)}


@router.get("/system-agents/pending")
def system_agents_pending():
    """Pending board for the dashboard: auto-detected stalled agents
    (logs/_stalled_agents.json, written by scripts/pending_tracker.py) plus the
    hand-curated 'Pending tasks' table parsed out of PENDING.md."""
    stalled = _read(STALLED_JSON) or {}

    tasks = []
    try:
        if PENDING_MD.exists():
            in_section = False
            for ln in PENDING_MD.read_text(encoding="utf-8").splitlines():
                if ln.startswith("## Pending tasks"):
                    in_section = True
                    continue
                if in_section and ln.startswith("## "):
                    break
                if in_section and ln.lstrip().startswith("|"):
                    cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                    if len(cells) >= 4 and cells[0].isdigit():
                        tasks.append({"id": cells[0], "task": cells[1],
                                      "deferred": cells[2], "note": cells[3]})
    except Exception:
        pass

    return {
        "stalled": stalled.get("stalled", []),
        "stalled_count": stalled.get("count", 0),
        "scanned_at": stalled.get("scanned_at"),
        "scan_age_minutes": _age_minutes(STALLED_JSON),
        "pending_tasks": tasks,
    }


@router.get("/system-agents/incidents")
def system_agents_incidents(limit: int = Query(50, ge=1, le=300)):
    """Autonomous incident pipeline: CEO-routed problems, fixes, circuit
    breakers, and the kill-switch state. Written by
    trading_agents/incident_pipeline.py."""
    hist = _read(INCIDENTS) or []
    if isinstance(hist, dict):
        hist = hist.get("incidents", [])
    hist = sorted(hist, key=lambda h: h.get("opened_at", ""), reverse=True)[:limit]

    kill = _read(KILL_FLAG) or {}
    by_status: dict = {}
    for h in hist:
        by_status[h.get("status", "open")] = by_status.get(h.get("status", "open"), 0) + 1

    return {
        "kill_switch": {
            "halted": bool(kill.get("halt")),
            "reason": kill.get("reason"),
            "ts":     kill.get("ts"),
        },
        "summary": {
            "total":      len(hist),
            "by_status":  by_status,
            "open_or_failed": sum(1 for h in hist
                                  if h.get("status") in ("open", "fixing", "failed")),
        },
        "incidents": hist,
    }
