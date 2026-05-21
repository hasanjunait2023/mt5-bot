"""JTCC Guardian — watchdog for the JTCC signal engine.

Polls _jtcc_state.json + _jtcc_latency.json every 60s. Escalates issues to
existing incident_pipeline (which routes to dev_team via Telegram).

Run alongside JTCC:
  python -m trading_agents.jtcc.guardian
  python -m trading_agents.jtcc.guardian --once
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent.parent.parent
STATE = BASE_DIR / "logs" / "jtcc" / "_jtcc_state.json"
LATENCY = BASE_DIR / "logs" / "jtcc" / "_jtcc_latency.json"
GUARDIAN_STATE = BASE_DIR / "logs" / "jtcc" / "_guardian_state.json"
BD_TZ = ZoneInfo("Asia/Dhaka")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("jtcc.guardian")

THRESHOLDS = {
    "state_stale_minutes": 5,       # state file not updated in 5min = dead
    "fmp_error_rate_pct": 50,       # FMP API failing >50% = problem
    "claude_error_rate_pct": 30,    # Claude API failing >30% = problem
    "master_block_rate_pct": 95,    # Master blocking >95% candidates = config issue
    "l1_latency_p95_ms": 2000,      # L1 pure-python; 2s = genuinely slow
    "l3_latency_p95_ms": 200000,    # L3 LLM: NVIDIA fallback runs 20-170s, only flag >200s
}


def _read_json(path: Path) -> dict | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Read %s failed: %s", path.name, e)
    return None


def _save_guardian_state(state: dict) -> None:
    try:
        GUARDIAN_STATE.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(tz=BD_TZ).isoformat()
        GUARDIAN_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _escalate(severity: str, description: str, component: str = "jtcc") -> None:
    """Route through existing incident_pipeline."""
    log.warning("[%s] %s — %s", severity, component, description)
    try:
        from trading_agents.incident_pipeline import report
        # Map our severity to incident_pipeline values
        sev_map = {"CRITICAL": "HIGH", "ERROR": "HIGH", "WARNING": "MEDIUM"}
        report(
            source_agent="jtcc_guardian",
            component=component,
            symptom=description,
            severity=sev_map.get(severity, "MEDIUM"),
            detail={"raw_severity": severity},
        )
    except Exception as e:
        log.error("Incident pipeline call failed: %s", e)
        # Fallback: Telegram directly
        try:
            from trading_agents.telegram_hq import send as tg_send
            tg_send("critical" if severity == "CRITICAL" else "dev_team",
                    f"JTCC GUARDIAN [{severity}] {component}: {description}",
                    level="CRITICAL" if severity == "CRITICAL" else "WARNING",
                    title=f"JTCC {severity}")
        except Exception:
            pass


def _jtcc_process_alive() -> bool:
    """Check if jtcc.main process is actually running (cross-platform)."""
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                if "trading_agents.jtcc.main" in cmd:
                    return True
            except Exception:
                continue
        return False
    except ImportError:
        # psutil not available — fall back to mtime check only
        return True  # assume alive, defer to mtime check


def _check_alive(state: dict | None) -> list[dict]:
    """Check if JTCC process is alive. Combines process-level + state-level checks."""
    issues = []
    if not state:
        issues.append({"severity": "CRITICAL", "msg": "_jtcc_state.json missing — JTCC never started or crashed"})
        return issues

    status = state.get("status", "unknown")
    if status != "running":
        issues.append({"severity": "WARNING", "msg": f"JTCC status: {status} (not 'running')"})

    process_alive = _jtcc_process_alive()

    # File freshness check — only flag as CRITICAL if process is ALSO dead
    if STATE.exists():
        mtime = datetime.fromtimestamp(STATE.stat().st_mtime, tz=BD_TZ)
        age_mins = (datetime.now(tz=BD_TZ) - mtime).total_seconds() / 60
        if age_mins > THRESHOLDS["state_stale_minutes"]:
            if not process_alive:
                issues.append({
                    "severity": "CRITICAL",
                    "msg": f"State file stale ({age_mins:.1f}min) AND process DEAD — JTCC crashed",
                })
            else:
                # Process alive but state stale — likely just waiting for bar close (informational)
                issues.append({
                    "severity": "INFO",
                    "msg": f"State file mtime stale ({age_mins:.1f}min) but process alive — waiting for next bar close",
                })

    return issues


def _check_latency(latency: dict | None) -> list[dict]:
    """Check L1/L3 latencies and error rates."""
    issues = []
    if not latency or "stats" not in latency:
        return issues

    stats = latency["stats"]

    # FMP errors
    fmp = stats.get("fmp_fetch", {})
    if fmp.get("calls", 0) > 10 and fmp.get("error_rate_pct", 0) > THRESHOLDS["fmp_error_rate_pct"]:
        issues.append({
            "severity": "ERROR",
            "msg": f"FMP API error rate {fmp['error_rate_pct']}% over {fmp['calls']} calls — bars not flowing",
        })

    # Claude errors
    claude = stats.get("l3_master", {})
    if claude.get("calls", 0) > 5 and claude.get("error_rate_pct", 0) > THRESHOLDS["claude_error_rate_pct"]:
        issues.append({
            "severity": "ERROR",
            "msg": f"Claude API error rate {claude['error_rate_pct']}% over {claude['calls']} calls",
        })
    # Latency = INFO only (logged, NOT escalated to incident_pipeline).
    # Slow LLM is not a failure — NVIDIA fallback is inherently slow.
    if claude.get("p95_ms", 0) > THRESHOLDS["l3_latency_p95_ms"]:
        issues.append({
            "severity": "INFO",
            "msg": f"Master Agent p95 latency {claude['p95_ms']}ms (LLM fallback slow)",
        })

    # L1 slowness (INFO only)
    for label in ("l1_momentum", "l1_market_structure", "l1_smc"):
        ag = stats.get(label, {})
        if ag.get("p95_ms", 0) > THRESHOLDS["l1_latency_p95_ms"]:
            issues.append({
                "severity": "INFO",
                "msg": f"{label} p95 {ag['p95_ms']}ms slow",
            })

    return issues


def _check_signal_health(state: dict | None) -> list[dict]:
    """Detect if Master Agent is blocking too many candidates (suggests config issue)."""
    issues = []
    if not state:
        return issues
    api_calls = state.get("daily_api_calls", 0)
    confluence = state.get("confluence", {})
    total_candidates = sum(
        max(c.get("buy_count", 0), c.get("sell_count", 0)) >= 3
        for c in confluence.values()
    )
    if total_candidates > 20 and api_calls == 0:
        issues.append({
            "severity": "WARNING",
            "msg": f"{total_candidates} signal candidates seen but 0 Master Agent calls — gates may be too strict",
        })
    return issues


def run_check() -> dict:
    """One audit cycle. Returns summary dict."""
    state = _read_json(STATE)
    latency = _read_json(LATENCY)

    issues = []
    issues.extend(_check_alive(state))
    issues.extend(_check_latency(latency))
    issues.extend(_check_signal_health(state))

    summary = {
        "checked_at": datetime.now(tz=BD_TZ).isoformat(),
        "issues_count": len(issues),
        "issues": issues,
        "state_present": state is not None,
        "latency_present": latency is not None,
    }

    if issues:
        log.warning("Found %d issues", len(issues))
        # Group by severity. Only ESCALATE non-INFO (INFO = log only, no incident pipeline)
        by_sev: dict[str, list] = {}
        for i in issues:
            by_sev.setdefault(i["severity"], []).append(i["msg"])
        for sev, msgs in by_sev.items():
            if sev == "INFO":
                log.info("[INFO] %s", "; ".join(msgs))
                continue
            _escalate(sev, "; ".join(msgs[:3]), component="jtcc")
    else:
        log.info("All checks passed")

    _save_guardian_state(summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="JTCC Guardian watchdog")
    parser.add_argument("--once", action="store_true", help="Run one check then exit")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default 60)")
    args = parser.parse_args()

    log.info("JTCC Guardian started — interval %ds", args.interval)
    if args.once:
        result = run_check()
        print(json.dumps(result, indent=2))
        return

    while True:
        try:
            run_check()
        except Exception as e:
            log.error("Guardian cycle error: %s", e)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
