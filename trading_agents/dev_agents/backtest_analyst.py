"""
BacktestAnalyst — Automatically analyzes backtest HTML reports using Claude.

Watches backtest_reports/ for new files and produces written verdicts with
concrete parameter change recommendations.

Usage:
  python -m trading_agents.dev_agents.backtest_analyst --once
  python -m trading_agents.dev_agents.backtest_analyst --watch   (continuous)
  python -m trading_agents.dev_agents.backtest_analyst --file backtest_reports/S6_report.html
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser

import anthropic
from dotenv import load_dotenv

from .notifier import notify

load_dotenv()

log = logging.getLogger("BacktestAnalyst")

BASE_DIR = Path(__file__).parent.parent.parent
REPORTS_DIR = BASE_DIR / "backtest_reports"
ANALYSIS_DIR = REPORTS_DIR
HISTORY_FILE = BASE_DIR / "logs" / "dev_agents" / "_backtest_history.json"

SYSTEM_PROMPT = """You are BacktestAnalyst, an expert trading strategy analyst reviewing backtest results.

Given backtest statistics, provide a structured analysis with:
1. Overall verdict (profitable / marginal / unprofitable)
2. Key strengths and weaknesses
3. Specific parameter recommendations (be concrete: e.g., "restrict to London session 07:00-12:00 UTC")
4. Risk assessment
5. Recommended next action (deploy / optimize further / disable)

Be concise and actionable. Format as markdown with clear sections.
End with a one-line Telegram summary (prefix with SUMMARY:)."""


class _StatParser(HTMLParser):
    """Extracts text content from backtest HTML reports."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True

    def handle_data(self, data):
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self.text_parts)


def _parse_report(html_path: Path) -> str:
    try:
        html = html_path.read_text(encoding="utf-8", errors="replace")
        parser = _StatParser()
        parser.feed(html)
        text = parser.get_text()
        # cap at 6000 chars to stay within token budget
        return text[:6000]
    except Exception as e:
        return f"Failed to parse report: {e}"


def _load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_history(history: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def analyze_report(html_path: Path, client: anthropic.Anthropic) -> str:
    """Analyze a single backtest HTML report. Returns the analysis markdown."""
    report_text = _parse_report(html_path)
    history = _load_history()
    prev = history.get(html_path.stem, "No previous run available.")

    user_msg = (
        f"Report file: {html_path.name}\n\n"
        f"Current backtest results:\n{report_text}\n\n"
        f"Previous run for comparison:\n{prev}"
    )

    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet (unchanged) + NVIDIA fallback if Claude is down
    analysis = chat_resilient(
        client, system=SYSTEM_PROMPT, user=user_msg, max_tokens=2048,
        model="claude-sonnet-4-6", thinking=False, nvidia_tier="HEAVY",
        label="backtest_analyst")

    # save analysis to file
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = ANALYSIS_DIR / f"analysis_{html_path.stem}_{ts}.md"
    out_path.write_text(analysis, encoding="utf-8")
    log.info("Analysis written to %s", out_path)

    # update history
    history[html_path.stem] = report_text[:1000]
    _save_history(history)

    # extract SUMMARY line for Telegram
    summary_match = re.search(r"SUMMARY:\s*(.+)", analysis)
    summary = summary_match.group(1).strip() if summary_match else f"Analysis complete for {html_path.name}"
    notify(f"*BacktestAnalyst*: {summary}\nFull report: `{out_path.name}`")

    return analysis


def _find_new_reports(seen: set) -> list:
    if not REPORTS_DIR.exists():
        return []
    return [p for p in REPORTS_DIR.glob("*.html") if p not in seen]


def run_once(target: Path | None = None) -> None:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    if target:
        files = [target]
    else:
        files = list(REPORTS_DIR.glob("*.html")) if REPORTS_DIR.exists() else []
    if not files:
        log.info("No HTML reports found in %s", REPORTS_DIR)
        return
    for f in files:
        log.info("Analyzing %s", f.name)
        analysis = analyze_report(f, client)
        print(analysis[:500])


def run_watch() -> None:
    """Watch backtest_reports/ for new HTML files and analyze them automatically."""
    log.info("BacktestAnalyst watching %s", REPORTS_DIR)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    seen: set = set(REPORTS_DIR.glob("*.html")) if REPORTS_DIR.exists() else set()
    while True:
        new = _find_new_reports(seen)
        for f in new:
            log.info("New report detected: %s", f.name)
            try:
                analyze_report(f, client)
            except Exception as e:
                log.error("Failed to analyze %s: %s", f.name, e)
            seen.add(f)
        time.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--watch" in sys.argv:
        run_watch()
    elif "--file" in sys.argv:
        idx = sys.argv.index("--file")
        run_once(Path(sys.argv[idx + 1]))
    else:
        run_once()
