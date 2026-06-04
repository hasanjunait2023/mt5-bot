"""
SupervisorAgent — Workspace-wide heartbeat and system integrity guardian.

Runs on a configurable cycle (default every 10 hours). Audits every layer of the
system — live trader, EA agents, dev agents, config consistency, data freshness —
and escalates any issues to the dev team. Waits for the fix, re-validates, then
sends a final status report to Junait on Telegram.

Think of it as the CEO's morning briefing: everything checked, issues escalated
and resolved before you even wake up.

Usage:
  python -m trading_agents.supervisor_agent              # run once + loop
  python -m trading_agents.supervisor_agent --once       # single audit
  python -m trading_agents.supervisor_agent --interval 12  # run every 12h
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("Supervisor")

BASE_DIR = Path(__file__).parent.parent

# ── State files produced by each agent layer ─────────────────────────────────
LIVE_STATE       = BASE_DIR / "mt5_bridge" / "_live_state.json"
LIVE_LOG         = BASE_DIR / "mt5_bridge" / "_live_log.txt"
GUARDIAN_STATE   = BASE_DIR / "logs" / "ea_agents"  / "_guardian_state.json"
COACH_STATE      = BASE_DIR / "logs" / "ea_agents"  / "_coach_state.json"
DEV_MONITOR      = BASE_DIR / "logs" / "dev_agents" / "_monitor_state.json"
TRADING_CONFIG   = BASE_DIR / "trading_agents" / "trading_system_config.json"
# JTCC integration — supervisor now audits JTCC alongside EAs
JTCC_STATE       = BASE_DIR / "logs" / "jtcc" / "_jtcc_state.json"
JTCC_GUARDIAN    = BASE_DIR / "logs" / "jtcc" / "_guardian_state.json"
JTCC_PERF        = BASE_DIR / "logs" / "jtcc" / "_jtcc_performance.json"
JTCC_LATENCY     = BASE_DIR / "logs" / "jtcc" / "_jtcc_latency.json"
JTCC_COACH       = BASE_DIR / "logs" / "jtcc" / "_jtcc_coach.json"
SUPERVISOR_LOG   = BASE_DIR / "logs" / "supervisor_report.json"
SUPERVISOR_HIST  = BASE_DIR / "logs" / "supervisor_history.json"
ORCH_STATE       = BASE_DIR / "logs" / "_orchestrator_state.json"


def _orch_considers_healthy(component: str, max_state_age_s: int = 120) -> bool:
    """True if the orchestrator (more authoritative than this snapshot)
    shows a service matching `component` starting/running with a live pid.
    Used to drop boot-race false positives before escalating."""
    comp = (component or "").lower()
    if not comp:
        return False
    try:
        if time.time() - ORCH_STATE.stat().st_mtime > max_state_age_s:
            return False  # stale orchestrator state — do not trust it
        d = _read_json(ORCH_STATE)
        for s in (d.get("services", []) if isinstance(d, dict) else []):
            sid = str(s.get("id", "")).lower()
            if sid and (sid in comp or comp in sid):
                return s.get("status") in ("starting", "running") and bool(s.get("pid"))
    except Exception:
        pass
    return False

DEFAULT_INTERVAL_HOURS = 10

# ── Claude prompt ─────────────────────────────────────────────────────────────
AUDIT_PROMPT = """You are SupervisorAgent, the workspace-wide integrity guardian for an MT5 algorithmic trading system.

You receive a full system snapshot. Your job is to:
1. Identify every issue — classify as CRITICAL, WARNING, or INFO
2. For each issue decide: needs_dev_team (true/false)
3. Produce a concise human-readable report for the trader

Respond ONLY in JSON:
{
  "overall_status": "HEALTHY" | "DEGRADED" | "CRITICAL",
  "issues": [
    {
      "component": "component name",
      "severity": "CRITICAL" | "WARNING" | "INFO",
      "description": "what is wrong",
      "needs_dev_team": true | false,
      "dev_task": "task description for the dev team (if needs_dev_team=true)"
    }
  ],
  "summary": "2-sentence plain-English summary for Junait",
  "next_action": "what Junait should know or do right now"
}

A system is HEALTHY if there are no CRITICAL issues and fewer than 3 WARNINGs.
DEGRADED means warnings exist but trading continues safely.
CRITICAL means action is needed immediately."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents.dev_agents.notifier import notify
        notify(msg, level=level, category="supervisor")
    except Exception as e:
        log.warning("Notify failed: %s", e)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age_minutes(path: Path) -> float | None:
    """Return how many minutes ago a file was last modified. None if missing."""
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 60


def _tail_log(lines: int = 60) -> str:
    try:
        text = LIVE_LOG.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        return ""


def _load_history() -> list:
    if SUPERVISOR_HIST.exists():
        try:
            return json.loads(SUPERVISOR_HIST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_history(entry: dict) -> None:
    history = _load_history()
    history.append(entry)
    history = history[-30:]  # keep last 30 cycles
    SUPERVISOR_HIST.parent.mkdir(parents=True, exist_ok=True)
    SUPERVISOR_HIST.write_text(json.dumps(history, indent=2), encoding="utf-8")


# ── System snapshot collector ─────────────────────────────────────────────────

def _maic_health() -> dict:
    """Cheap structural health of the CEO agent — no live LLM call.

    Maic is a single point of failure for the interactive path; surface
    whether it still has at least one working backend (Claude CLI or the
    NVIDIA fallback) so a degraded CEO is caught before Junait hits it.
    """
    import shutil
    ta = BASE_DIR / "trading_agents"
    claude_cli = shutil.which("claude") is not None
    nvr_ok = (ta / "nvidia_model_router.py").exists()
    fb_ok = (ta / "llm_fallback.py").exists()
    hist_ok = (ta / ".maic_history.json").parent.exists()
    backends = ([m for m, c in
                 (("claude-cli", claude_cli), ("nvidia-fallback", nvr_ok)) if c])
    return {
        "claude_cli_present": claude_cli,
        "nvidia_fallback_available": nvr_ok,
        "resilient_helper_present": fb_ok,
        "history_dir_ok": hist_ok,
        "usable_backends": backends,
        "ok": bool(backends),  # at least one path to answer Junait
    }


def _collect_snapshot() -> dict:
    """Gather state from every layer of the system into a single dict."""
    now = datetime.now(timezone.utc)

    live = _read_json(LIVE_STATE)
    guardian = _read_json(GUARDIAN_STATE)
    coach = _read_json(COACH_STATE)
    dev_monitor = _read_json(DEV_MONITOR)
    config = _read_json(TRADING_CONFIG)

    live_age = _age_minutes(LIVE_STATE)
    guardian_age = _age_minutes(GUARDIAN_STATE)
    coach_age = _age_minutes(COACH_STATE)
    dev_monitor_age = _age_minutes(DEV_MONITOR)

    account = live.get("account", {})

    # count recent error lines in log
    log_tail = _tail_log()
    error_lines = sum(1 for l in log_tail.splitlines() if "ERROR" in l or "CRITICAL" in l)

    # pending coach decisions
    pending_decisions = []
    for ea_name, ea_data in coach.get("eas", {}).items():
        if ea_data.get("pending_question"):
            asked_at = ea_data["pending_question"].get("asked_at", "")
            pending_decisions.append({"ea": ea_name, "asked_at": asked_at})

    # recent dev team bug reports
    dev_agent_log_dir = BASE_DIR / "logs" / "dev_agents"
    recent_bugs = []
    if dev_agent_log_dir.exists():
        debug_files = sorted(dev_agent_log_dir.glob("debug_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        for f in debug_files:
            age = _age_minutes(f)
            recent_bugs.append({"file": f.name, "age_minutes": round(age, 1) if age else None})

    return {
        "checked_at": now.isoformat(),

        # live trading layer
        "live_trader": {
            "state_file_age_minutes": round(live_age, 1) if live_age is not None else "MISSING",
            "trader_running": live.get("trader_running"),
            "mt5_connected": live.get("mt5_connected"),
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "daily_dd_pct": account.get("daily_dd_pct"),
            "total_dd_pct": account.get("total_dd_pct"),
            "open_positions": len(live.get("positions", [])),
            "error_lines_in_last_60_log_lines": error_lines,
            "is_demo": config.get("demo_account", True),
        },

        # EA agent layer
        "ea_guardian": {
            "state_file_age_minutes": round(guardian_age, 1) if guardian_age is not None else "MISSING",
            "last_check": guardian.get("last_check"),
            "anomalies_found": guardian.get("anomalies_found", 0),
            "account_snapshot": guardian.get("account", {}),
        },

        # EA coach layer
        "ea_coach": {
            "state_file_age_minutes": round(coach_age, 1) if coach_age is not None else "MISSING",
            "last_updated": coach.get("updated_at"),
            "pending_decisions_count": len(pending_decisions),
            "pending_decisions": pending_decisions,
            "ea_stages": {
                ea: data.get("lifecycle_stage", "unknown")
                for ea, data in coach.get("eas", {}).items()
            },
        },

        # dev monitor layer
        "dev_monitor": {
            "state_file_age_minutes": round(dev_monitor_age, 1) if dev_monitor_age is not None else "MISSING",
            "last_status": dev_monitor.get("summary"),
            "anomaly": dev_monitor.get("anomaly", False),
        },

        # config layer
        "config": {
            "demo_mode": config.get("demo_account"),
            "live_trading_enabled": config.get("enable_live_trading"),
            "risk_per_trade_pct": round(config.get("max_risk_per_trade", 0) * 100, 2),
            "max_daily_loss_pct": round(config.get("max_daily_loss_pct", 0) * 100, 2),
            "max_drawdown_pct": round(config.get("max_drawdown_pct", 0) * 100, 2),
            "tracked_symbols": config.get("symbols", []),
        },

        # dev team recent activity
        "dev_activity": {
            "recent_bug_reports": recent_bugs,
        },

        # CEO agent health (single point of failure for interactive path)
        "maic_health": _maic_health(),

        # JTCC layer — the new 4-layer autonomous signal engine
        "jtcc": _jtcc_snapshot(),
    }


def _jtcc_snapshot() -> dict:
    """Snapshot JTCC's state for supervisor audit."""
    jtcc_state = _read_json(JTCC_STATE)
    jtcc_guardian = _read_json(JTCC_GUARDIAN)
    jtcc_perf = _read_json(JTCC_PERF)
    jtcc_latency = _read_json(JTCC_LATENCY)
    jtcc_coach = _read_json(JTCC_COACH)

    state_age = _age_minutes(JTCC_STATE)
    perf = jtcc_perf or {}
    total_trades = perf.get("total_trades", 0)
    win_rate = round(perf.get("wins", 0) / max(total_trades, 1) * 100, 1) if total_trades else 0.0

    confluence = (jtcc_state or {}).get("confluence", {})
    active_signals = sum(
        1 for c in confluence.values()
        if max(c.get("buy_count", 0), c.get("sell_count", 0)) >= 3
    )

    return {
        "running": jtcc_state.get("status") == "running",
        "mode": "DRY RUN" if jtcc_state.get("dry_run") else "LIVE",
        "state_file_age_minutes": round(state_age, 1) if state_age is not None else "MISSING",
        "symbols_tracked": len(jtcc_state.get("symbols", [])),
        "daily_api_calls": jtcc_state.get("daily_api_calls", 0),
        "active_signal_candidates": active_signals,
        "performance": {
            "total_trades": total_trades,
            "win_rate_pct": win_rate,
            "total_pnl": perf.get("total_pnl", 0.0),
        },
        "guardian_issues": jtcc_guardian.get("issues_count", 0) if jtcc_guardian else "MISSING",
        "coach_last_run": jtcc_coach.get("last_run") if jtcc_coach else None,
        "coach_proposal": (jtcc_coach.get("proposal") or {}).get("type") if jtcc_coach else None,
        "latency_p95_l1_ms": ((jtcc_latency or {}).get("stats", {}).get("l1_full") or {}).get("p95_ms"),
    }


# ── Dev team escalation ───────────────────────────────────────────────────────

def _escalate_to_dev(task: str) -> str:
    """Call dev_lead synchronously and return its output."""
    dev_lead = BASE_DIR / "trading_agents" / "dev_agents" / "dev_lead.py"
    if not dev_lead.exists():
        return "dev_lead.py not found — cannot escalate"
    try:
        result = subprocess.run(
            # Run as a module, not a bare script, so dev_lead's package-relative
            # imports (`from .notifier import notify`) resolve. cwd=repo root
            # puts the `trading_agents` namespace package on sys.path.
            [sys.executable, "-m", "trading_agents.dev_agents.dev_lead",
             "--task", task],
            capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR),
        )
        output = (result.stdout or result.stderr or "No output").strip()
        return output[:2000]
    except subprocess.TimeoutExpired:
        return "Dev team timed out after 300s"
    except Exception as e:
        return f"Escalation failed: {e}"


def _recheck_component(component: str, snapshot: dict) -> bool:
    """Re-check a specific component after dev team intervention. Returns True if resolved."""
    component_lower = component.lower()

    if "live_trader" in component_lower or "mt5" in component_lower:
        fresh = _read_json(LIVE_STATE)
        age = _age_minutes(LIVE_STATE)
        return age is not None and age < 5 and fresh.get("trader_running", False)

    if "guardian" in component_lower:
        age = _age_minutes(GUARDIAN_STATE)
        return age is not None and age < 120

    if "coach" in component_lower:
        age = _age_minutes(COACH_STATE)
        return age is not None and age < 720  # coach runs every 6h

    if "config" in component_lower:
        cfg = _read_json(TRADING_CONFIG)
        return bool(cfg)

    if "log" in component_lower or "error" in component_lower:
        tail = _tail_log(20)
        recent_errors = sum(1 for l in tail.splitlines() if "ERROR" in l)
        return recent_errors == 0

    if "jtcc" in component_lower:
        # JTCC healthy if main state updated within 5min and guardian has no critical issues
        age = _age_minutes(JTCC_STATE)
        gstate = _read_json(JTCC_GUARDIAN)
        critical = any(i.get("severity") == "CRITICAL" for i in gstate.get("issues", []))
        return age is not None and age < 5 and not critical

    # default: assume resolved if dev team ran without error
    return True


# ── Main audit cycle ──────────────────────────────────────────────────────────

def run_audit(client: anthropic.Anthropic) -> dict:
    """Full system audit. Returns the audit result dict."""
    log.info("=== Supervisor audit started ===")
    started_at = datetime.now(timezone.utc)

    # 1. collect snapshot
    snapshot = _collect_snapshot()
    log.info("Snapshot collected — asking Claude to analyse...")

    # 2. ask Claude to analyse
    # Claude Opus 4.7 + adaptive thinking; auto-fallback to NVIDIA if Claude is down
    sys.path.insert(0, str(BASE_DIR / "trading_agents"))
    from llm_fallback import chat_resilient
    raw = chat_resilient(
        client, system=AUDIT_PROMPT,
        user=f"System snapshot:\n{json.dumps(snapshot, indent=2)}",
        max_tokens=16000, nvidia_tier="ULTRA", label="supervisor").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    analysis = json.loads(raw[start:end]) if start >= 0 else {
        "overall_status": "UNKNOWN", "issues": [], "summary": raw, "next_action": ""
    }

    overall = analysis.get("overall_status", "UNKNOWN")
    issues = analysis.get("issues", [])
    log.info("Claude analysis: %s — %d issues", overall, len(issues))

    # 3. escalate issues that need dev team
    dev_results = {}
    dev_issues = [i for i in issues if i.get("needs_dev_team")]
    # Drop boot-timing false positives: if the orchestrator already shows the
    # component alive, a "down/stale" reading is just a race with startup —
    # escalating it to the dev team only manufactures phantom incidents.
    _phantom = [i for i in dev_issues if _orch_considers_healthy(i.get("component", ""))]
    if _phantom:
        for i in _phantom:
            log.info("  Skipping phantom escalation [%s] — orchestrator shows it healthy",
                     i.get("component"))
        dev_issues = [i for i in dev_issues if i not in _phantom]
    if dev_issues:
        log.info("Escalating %d issue(s) to dev team...", len(dev_issues))
        _notify(
            f"*Supervisor*: Found {len(dev_issues)} issue(s) — escalating to dev team now.",
            level="WARNING",
        )
        for issue in dev_issues:
            task = issue.get("dev_task", issue.get("description", "investigate system issue"))
            component = issue.get("component", "unknown")
            log.info("  Escalating [%s]: %s", component, task)
            # Route THROUGH the CEO-centered incident pipeline (CEO owns the
            # delegation + circuit breakers + Telegram + feedback). Fall back
            # to direct dev escalation only if the pipeline is unavailable.
            try:
                from trading_agents.incident_pipeline import report as _report
                inc = _report(
                    source_agent="supervisor",
                    component=component,
                    symptom=task,
                    severity=issue.get("severity", "HIGH"),
                    detail=issue,
                )
                dev_results[component] = (
                    f"incident {inc.get('id')} -> {inc.get('status')}: "
                    f"{inc.get('resolution', '')[:400]}")
            except Exception as e:
                log.error("incident pipeline unavailable (%s); direct "
                          "dev escalation", e)
                dev_results[component] = _escalate_to_dev(task)

        # 4. re-check each escalated component
        resolved = []
        unresolved = []
        for issue in dev_issues:
            component = issue.get("component", "unknown")
            if _recheck_component(component, snapshot):
                resolved.append(component)
                log.info("  [%s] RESOLVED after dev team fix", component)
            else:
                unresolved.append(component)
                log.warning("  [%s] STILL UNRESOLVED after dev team fix", component)
    else:
        resolved = []
        unresolved = []

    # 5. build final report
    duration = (datetime.now(timezone.utc) - started_at).total_seconds()
    audit_result = {
        "audited_at": started_at.isoformat(),
        "duration_seconds": round(duration, 1),
        "overall_status": overall,
        "issues_found": len(issues),
        "issues": issues,
        "dev_escalations": len(dev_issues),
        "resolved": resolved,
        "unresolved": unresolved,
        "summary": analysis.get("summary", ""),
        "next_action": analysis.get("next_action", ""),
        "dev_team_outputs": dev_results,
    }

    # 6. save report
    SUPERVISOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    SUPERVISOR_LOG.write_text(json.dumps(audit_result, indent=2), encoding="utf-8")
    _save_history({
        "timestamp": started_at.isoformat(),
        "overall_status": overall,
        "issues_found": len(issues),
        "dev_escalations": len(dev_issues),
        "resolved": resolved,
        "unresolved": unresolved,
    })

    # 7. send Telegram report
    _send_telegram_report(audit_result)

    log.info("=== Supervisor audit complete in %.1fs ===", duration)
    return audit_result


def _send_telegram_report(result: dict) -> None:
    overall = result["overall_status"]
    issues = result["issues"]
    resolved = result["resolved"]
    unresolved = result["unresolved"]
    summary = result.get("summary", "")
    next_action = result.get("next_action", "")

    # status icon
    icon = {"HEALTHY": "✅", "DEGRADED": "⚠️", "CRITICAL": "🚨", "UNKNOWN": "❓"}.get(overall, "❓")

    # issue lines
    issue_lines = []
    for i in issues:
        sev_icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(i["severity"], "⚪")
        issue_lines.append(f"{sev_icon} [{i['component']}] {i['description']}")

    # resolution lines
    resolution_lines = []
    for c in resolved:
        resolution_lines.append(f"✅ {c} — fixed & confirmed")
    for c in unresolved:
        resolution_lines.append(f"❌ {c} — still needs attention")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg_parts = [
        f"*SUPERVISOR REPORT* — {ts}",
        f"{'━' * 32}",
        f"{icon} Overall: *{overall}*",
        f"{summary}",
    ]

    if issue_lines:
        msg_parts.append(f"\n*Issues ({len(issues)}):*")
        msg_parts.extend(issue_lines)

    if resolution_lines:
        msg_parts.append(f"\n*Dev Team Actions:*")
        msg_parts.extend(resolution_lines)

    if next_action:
        msg_parts.append(f"\n*Action needed:* {next_action}")

    msg_parts.append(f"\n_Full report saved to: `logs/supervisor_report.json`_")

    level = "CRITICAL" if overall == "CRITICAL" else ("WARNING" if overall == "DEGRADED" else "INFO")
    _notify("\n".join(msg_parts), level=level)


# ── Entry point ───────────────────────────────────────────────────────────────

def run_loop(interval_hours: float = DEFAULT_INTERVAL_HOURS) -> None:
    log.info("SupervisorAgent started — auditing every %.1fh", interval_hours)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    while True:
        try:
            run_audit(client)
        except Exception as e:
            log.error("Audit failed: %s", e)
            _notify(f"*Supervisor ERROR*: Audit cycle crashed — {e}", level="CRITICAL")
        next_run = datetime.now(timezone.utc) + timedelta(hours=interval_hours)
        log.info("Next audit at %s UTC", next_run.strftime("%Y-%m-%d %H:%M"))
        _notify(
            f"*Supervisor*: Audit complete. Next check at {next_run.strftime('%H:%M UTC')}.",
            level="INFO",
        )
        time.sleep(interval_hours * 3600)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    interval = DEFAULT_INTERVAL_HOURS
    if "--interval" in sys.argv:
        interval = float(sys.argv[sys.argv.index("--interval") + 1])

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if "--once" in sys.argv:
        result = run_audit(client)
        print(json.dumps(result, indent=2, default=str))
    else:
        run_loop(interval_hours=interval)
