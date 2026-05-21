"""
CodeReviewerAgent — Claude-powered code review on git diffs.

Usage:
  python -m trading_agents.dev_agents.code_reviewer              # review HEAD~1..HEAD
  python -m trading_agents.dev_agents.code_reviewer --base main  # review current vs main
  python -m trading_agents.dev_agents.code_reviewer --mode ci    # CI mode, exits with code 1 on critical
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .notifier import notify

load_dotenv()

log = logging.getLogger("CodeReviewerAgent")

BASE_DIR = Path(__file__).parent.parent.parent
REVIEW_LOG_DIR = BASE_DIR / "logs" / "dev_agents"

SYSTEM_PROMPT = """You are CodeReviewerAgent, a senior engineer reviewing code changes.

Review the provided git diff and identify issues. For each issue, classify:
- CRITICAL: bugs, security issues (hardcoded secrets, command injection, bare except hiding errors), logic errors
- WARNING: code smells, missing error handling at system boundaries, deprecated patterns
- INFO: style suggestions, minor improvements

For MQL5 files: check consistency with Python strategy equivalents, session hours, TP/SL ratios.
For Python files: check exception handling, resource cleanup, MT5 connection safety, hardcoded values.

Respond in JSON:
{
  "critical_count": 0,
  "warning_count": 0,
  "info_count": 0,
  "issues": [
    {
      "severity": "CRITICAL" | "WARNING" | "INFO",
      "file": "filename",
      "line": "line number or range",
      "description": "what the issue is",
      "suggestion": "how to fix it"
    }
  ],
  "summary": "one-line overall assessment"
}"""


def _get_diff(base: str = "HEAD~1") -> str:
    result = subprocess.run(
        ["git", "diff", f"{base}..HEAD", "--unified=5"],
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
    )
    return result.stdout


def _get_commit_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
    )
    return result.stdout.strip()


def _filter_diff(diff: str) -> str:
    """Keep only .py and .mq5 file sections, cap at 8000 chars."""
    lines = diff.split("\n")
    filtered = []
    include = False
    for line in lines:
        if line.startswith("diff --git"):
            include = any(line.endswith(ext) for ext in (".py", ".mq5", ".json"))
        if include:
            filtered.append(line)
    return "\n".join(filtered)[:8000]


def review(base: str = "HEAD~1", client: anthropic.Anthropic | None = None) -> dict:
    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    diff = _get_diff(base)
    filtered = _filter_diff(diff)
    if not filtered.strip():
        log.info("No .py or .mq5 changes found in diff")
        return {"critical_count": 0, "warning_count": 0, "info_count": 0, "issues": [], "summary": "No relevant changes"}

    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet (unchanged) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=SYSTEM_PROMPT, user=f"Git diff to review:\n\n{filtered}",
        max_tokens=4096, model="claude-sonnet-4-6", thinking=False,
        nvidia_tier="HEAVY", label="code_reviewer")
    start = raw.find("{")
    end = raw.rfind("}") + 1
    result = json.loads(raw[start:end]) if start >= 0 else {"issues": [], "summary": raw, "critical_count": 0, "warning_count": 0, "info_count": 0}

    # save report
    sha = _get_commit_sha()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    REVIEW_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REVIEW_LOG_DIR / f"review_{sha}_{ts}.md"
    _write_report(result, report_path, sha)

    # notify
    c = result.get("critical_count", 0)
    w = result.get("warning_count", 0)
    level = "CRITICAL" if c > 0 else ("WARNING" if w > 0 else "INFO")
    summary = result.get("summary", "Review complete")
    notify(f"*CodeReview* [{sha}]: {c} critical, {w} warnings\n{summary}\nReport: `{report_path.name}`", level=level)

    return result


def _write_report(result: dict, path: Path, sha: str) -> None:
    lines = [f"# Code Review — {sha}\n", f"**Summary:** {result.get('summary', '')}\n",
             f"- Critical: {result.get('critical_count', 0)}\n",
             f"- Warnings: {result.get('warning_count', 0)}\n",
             f"- Info: {result.get('info_count', 0)}\n\n## Issues\n"]
    for issue in result.get("issues", []):
        lines.append(f"### [{issue['severity']}] {issue['file']} line {issue.get('line', '?')}\n")
        lines.append(f"{issue['description']}\n")
        if issue.get("suggestion"):
            lines.append(f"**Fix:** {issue['suggestion']}\n\n")
    path.write_text("".join(lines), encoding="utf-8")
    log.info("Review report: %s", path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    base = "HEAD~1"
    ci_mode = "--mode" in sys.argv and sys.argv[sys.argv.index("--mode") + 1] == "ci"
    if "--base" in sys.argv:
        base = sys.argv[sys.argv.index("--base") + 1]

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = review(base=base, client=client)
    print(json.dumps(result, indent=2))

    if ci_mode and result.get("critical_count", 0) > 0:
        sys.exit(1)
