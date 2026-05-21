"""
DevLeadAgent — Orchestrates the full development engineering team.

Receives a task description, picks the right agent(s), runs them in sequence,
and synthesizes results. Designed to be invoked by Maic via subprocess.

Usage (standalone):
  python -m trading_agents.dev_agents.dev_lead --task "write tests for backtest.py"
  python -m trading_agents.dev_agents.dev_lead --task "debug S6 no trades after reconnect"
  python -m trading_agents.dev_agents.dev_lead --task "review code HEAD"
  python -m trading_agents.dev_agents.dev_lead --task "analyze backtests"
  python -m trading_agents.dev_agents.dev_lead --task "sync S6 EA params"
  python -m trading_agents.dev_agents.dev_lead --task "weekly health check"

Maic delegation:
  [DELEGATE: dev_lead | task="write tests for backtest.py"]
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Work whether launched via `-m trading_agents.dev_agents.dev_lead`, as a bare
# script (Maic's delegation path), or imported. Bare scripts have no package
# context so relative imports fail — bootstrap sys.path + use absolute imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from trading_agents.dev_agents.notifier import notify

load_dotenv()

log = logging.getLogger("DevLead")

BASE_DIR = Path(__file__).parent.parent.parent

SYSTEM_PROMPT = """You are DevLead, engineering team lead for the FX Vault MT5 Bot.

You manage 7 specialized dev agents. When given a task, determine which agent(s) to invoke and in what order.

Available agents:
- monitor: Check live system health (MonitorAgent)
- backtest: Analyze backtest reports (BacktestAnalyst)
- test_writer: Generate pytest tests for a module (TestWriterAgent) — needs: file path
- code_review: Review git diff/commit (CodeReviewerAgent) — optional: base commit
- debug: Debug a strategy issue (DebugInvestigatorAgent) — needs: strategy name + symptom
- ea_sync: Check Python/EA parameter sync (EASyncAgent) — needs: strategy name or "all"
- doc_keeper: Update docstrings (DocKeeperAgent) — needs: scope

Respond ONLY in JSON:
{
  "steps": [
    {
      "agent": "agent_name",
      "params": {"key": "value"},
      "reason": "why this agent"
    }
  ],
  "summary": "what you plan to do"
}"""


def _route_task(task: str, client: anthropic.Anthropic) -> dict:
    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet router (unchanged model) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=SYSTEM_PROMPT, user=f"Task: {task}", max_tokens=1024,
        model="claude-sonnet-4-6", thinking=False, nvidia_tier="MEDIUM",
        label="dev_lead")
    start = raw.find("{")
    end = raw.rfind("}") + 1
    return json.loads(raw[start:end]) if start >= 0 else {"steps": [], "summary": raw}


def _run_monitor(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.monitor_agent import run_once
    result = run_once()
    return f"Monitor: {result.get('summary', 'checked')}"


def _run_backtest(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.backtest_analyst import run_once, REPORTS_DIR
    target_file = params.get("file")
    if target_file:
        from pathlib import Path as P
        run_once(P(target_file))
    else:
        run_once()
    return "Backtest analysis complete"


def _run_test_writer(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.test_writer import write_tests
    file_param = params.get("file", "")
    target = BASE_DIR / file_param if file_param else None
    if not target or not target.exists():
        return f"TestWriter: file not found: {file_param}"
    out = write_tests(target, client)
    return f"Tests written to {out}"


def _run_code_review(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.code_reviewer import review
    base = params.get("base", "HEAD~1")
    result = review(base=base, client=client)
    return f"Review: {result.get('critical_count', 0)} critical, {result.get('warning_count', 0)} warnings — {result.get('summary', '')}"


def _run_debug(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.debug_investigator import investigate
    strategy = params.get("strategy", "")
    symptom = params.get("symptom", "")
    if not strategy or not symptom:
        return "Debug: missing strategy or symptom param"
    result = investigate(strategy, symptom, client)
    return f"Debug [{strategy}]: {result.get('hypothesis', 'see report')} (confidence: {result.get('confidence', '?')})"


def _run_ea_sync(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.ea_sync_agent import sync_strategy, STRATEGY_MAP
    strategy = params.get("strategy", "all")
    if strategy.lower() == "all":
        results = []
        for s in STRATEGY_MAP:
            r = sync_strategy(s, client)
            results.append(f"{s}: {'ok' if r.get('in_sync') else 'drift'}")
        return "EASync: " + ", ".join(results)
    else:
        r = sync_strategy(strategy, client)
        return f"EASync [{strategy}]: {'in sync' if r.get('in_sync') else 'OUT OF SYNC'}"


def _run_doc_keeper(params: dict, client: anthropic.Anthropic) -> str:
    from trading_agents.dev_agents.doc_keeper import process_scope
    scope = params.get("scope", "mt5_bridge")
    count = process_scope(scope, client)
    return f"DocKeeper: added {count} docstrings in {scope}"


AGENT_HANDLERS = {
    "monitor": _run_monitor,
    "backtest": _run_backtest,
    "test_writer": _run_test_writer,
    "code_review": _run_code_review,
    "debug": _run_debug,
    "ea_sync": _run_ea_sync,
    "doc_keeper": _run_doc_keeper,
}


def run_task(task: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    plan = _route_task(task, client)
    log.info("DevLead plan: %s", plan.get("summary", ""))

    results = []
    for step in plan.get("steps", []):
        agent_name = step.get("agent", "")
        params = step.get("params", {})
        handler = AGENT_HANDLERS.get(agent_name)
        if not handler:
            results.append(f"[{agent_name}] Unknown agent")
            continue
        log.info("Running %s with params %s", agent_name, params)
        try:
            result = handler(params, client)
            results.append(f"[{agent_name}] {result}")
        except Exception as e:
            log.error("[%s] Failed: %s", agent_name, e)
            results.append(f"[{agent_name}] Error: {e}")

    summary = plan.get("summary", "Task complete")
    report = f"DevLead completed: {summary}\n" + "\n".join(results)
    notify(f"*DevLead*: {summary}\n" + "\n".join(results))
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--task" not in sys.argv:
        print("Usage: python -m trading_agents.dev_agents.dev_lead --task <description>")
        sys.exit(1)
    idx = sys.argv.index("--task")
    # join remaining args as the task (handles multi-word tasks)
    task = " ".join(sys.argv[idx + 1:])
    report = run_task(task)
    print(report)
