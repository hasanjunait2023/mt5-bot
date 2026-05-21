"""
EA Lifecycle Manager — Orchestrator for the EA Guardian/Coach/Validator team.

Wired into Maic via script_map so Junait can trigger the team from Telegram.
Also handles routing user replies (YES/NO/TEST MORE) back to EACoach.

Usage (via Maic delegation):
  [DELEGATE: ea_team | task="check S6 health"]
  [DELEGATE: ea_team | task="is S6 ready for live?"]
  [DELEGATE: ea_team | task="test S6 on GBPUSD"]
  [DELEGATE: ea_team | task="S6 answer YES"]        ← user replying to a pending question
  [DELEGATE: ea_team | task="weekly EA report"]

Standalone:
  python -m trading_agents.ea_agents.ea_lifecycle_manager --task "check S6 health"
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("EALifecycleManager")

BASE_DIR = Path(__file__).parent.parent.parent

ROUTER_PROMPT = """You are the EA Lifecycle Manager. Route tasks to the right agent.

Available agents:
- guardian: check live EA health, detect anomalies (needs: ea name)
- coach: analyze EA performance, run improvement cycle (needs: ea name)
- validator: test EA compatibility across pairs/sessions (needs: ea name, optional: proposed change)
- answer: pass a user's YES/NO/TEST MORE answer to EACoach (needs: ea name + answer)
- report: weekly summary of all tracked EAs

Respond ONLY in JSON:
{
  "agent": "guardian" | "coach" | "validator" | "answer" | "report",
  "ea_name": "S6" or null,
  "proposed_change": "description or null",
  "user_answer": "YES" | "NO" | "TEST MORE" | null,
  "reason": "why this agent"
}"""


def _route(task: str, client: anthropic.Anthropic) -> dict:
    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Haiku router (unchanged, no thinking) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=ROUTER_PROMPT, user=f"Task: {task}", max_tokens=256,
        model="claude-haiku-4-5-20251001", thinking=False,
        nvidia_tier="MEDIUM", label="ea_lifecycle_mgr")
    start = raw.find("{")
    end = raw.rfind("}") + 1
    return json.loads(raw[start:end]) if start >= 0 else {"agent": "report", "ea_name": None}


def _run_guardian(ea_name: str | None) -> str:
    from trading_agents.ea_agents.ea_guardian import run_once
    results = run_once(ea_name)
    if not results:
        return f"EAGuardian: All EAs healthy — no anomalies detected."
    lines = []
    for ea, anomalies in results.items():
        for a in anomalies:
            lines.append(f"[{ea}] {a['severity']}: {a['detail']}")
    return "EAGuardian:\n" + "\n".join(lines)


def _run_coach(ea_name: str | None) -> str:
    from trading_agents.ea_agents.ea_coach import run_cycle
    run_cycle(ea_name)
    return f"EACoach: Analysis cycle complete for {'all EAs' if not ea_name else ea_name}. Check Telegram for questions."


def _run_validator(ea_name: str, proposed_change: str, client: anthropic.Anthropic) -> str:
    from trading_agents.ea_agents.ea_validator import run_full_validation
    result = run_full_validation(ea_name, proposed_change=proposed_change, client=client)
    verdict = result.get("overall_verdict", "UNKNOWN")
    rec = result.get("recommendation", "")
    compat = ", ".join(result.get("compatible_pairs", [])) or "none"
    return f"EAValidator [{ea_name}]: {verdict}\nWorks on: {compat}\n{rec}"


def _run_answer(ea_name: str, answer: str) -> str:
    from trading_agents.ea_agents.ea_coach import record_user_answer
    return record_user_answer(ea_name, answer)


def _run_weekly_report(client: anthropic.Anthropic) -> str:
    from trading_agents.ea_agents.ea_guardian import run_once, _load_config
    from trading_agents.ea_agents.ea_coach import run_cycle
    cfg = _load_config()
    tracked = cfg.get("tracked_eas", ["S6"])
    guardian_results = run_once()
    healthy = [ea for ea in tracked if ea not in guardian_results]
    issues = list(guardian_results.keys())
    run_cycle()
    return (
        f"Weekly EA Report:\n"
        f"Healthy EAs: {', '.join(healthy) or 'none'}\n"
        f"EAs with issues: {', '.join(issues) or 'none'}\n"
        f"Coach cycle ran — check Telegram for any pending decisions."
    )


def run_task(task: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    routing = _route(task, client)
    agent = routing.get("agent", "report")
    ea_name = routing.get("ea_name")
    proposed_change = routing.get("proposed_change") or ""
    user_answer = routing.get("user_answer")

    log.info("Routing '%s' → %s (EA: %s)", task, agent, ea_name)

    try:
        if agent == "guardian":
            return _run_guardian(ea_name)
        elif agent == "coach":
            return _run_coach(ea_name)
        elif agent == "validator":
            if not ea_name:
                return "EAValidator: please specify an EA name."
            return _run_validator(ea_name, proposed_change, client)
        elif agent == "answer":
            if not ea_name or not user_answer:
                return "Answer: please specify EA name and answer (YES/NO/TEST MORE)."
            return _run_answer(ea_name, user_answer)
        elif agent == "report":
            return _run_weekly_report(client)
        else:
            return f"Unknown agent: {agent}"
    except Exception as e:
        log.error("Task failed: %s", e)
        return f"EA team error: {e}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--task" not in sys.argv:
        print("Usage: python -m trading_agents.ea_agents.ea_lifecycle_manager --task <description>")
        sys.exit(1)
    idx = sys.argv.index("--task")
    task = " ".join(sys.argv[idx + 1:])
    result = run_task(task)
    print(result)
