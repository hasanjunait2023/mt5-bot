"""
DebugInvestigatorAgent — Root cause analysis for trading strategy issues.

Replaces the manual debug_s6.py pattern. Assembles code + logs + backtest
context and asks Claude to form a root cause hypothesis.

Usage:
  python -m trading_agents.dev_agents.debug_investigator --strategy S6 --symptom "no trades after reconnect"
  python -m trading_agents.dev_agents.debug_investigator --strategy S1 --symptom "high loss rate after 14:00 UTC"
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .notifier import notify

load_dotenv()

log = logging.getLogger("DebugInvestigator")

BASE_DIR = Path(__file__).parent.parent.parent
DEBUG_LOG_DIR = BASE_DIR / "logs" / "dev_agents"

# Strategy file mappings
STRATEGY_MAP = {
    "S1": (BASE_DIR / "mt5_bridge" / "strategy1_swing_scalp.py", BASE_DIR / "mql5_experts" / "ready_ea" / "S1_Swing_Scalp.mq5"),
    "S2": (BASE_DIR / "mt5_bridge" / "strategy2_m5_scalp.py", BASE_DIR / "mql5_experts" / "inspection_ea" / "S2_M5_Scalp.mq5"),
    "S4": (BASE_DIR / "mt5_bridge" / "strategy4_multi_pair.py", BASE_DIR / "mql5_experts" / "inspection_ea" / "S4_MultiPair_Engine.mq5"),
    "S5": (BASE_DIR / "mt5_bridge" / "strategy5_news_spike.py", BASE_DIR / "mql5_experts" / "ready_ea" / "S5_News_Spike_Reversal.mq5"),
    "S6": (BASE_DIR / "mt5_bridge" / "strategy6_asian_range.py", BASE_DIR / "mql5_experts" / "ready_ea" / "S6_Asian_Range_Breakout.mq5"),
    "MTF": (BASE_DIR / "mt5_bridge" / "mtf_live_trader.py", BASE_DIR / "mql5_experts" / "scalpmaster" / "MTF_EMA_Scalper_M1.mq5"),
}

SYSTEM_PROMPT = """You are DebugInvestigatorAgent, an expert debugger for algorithmic trading systems.

Given: strategy source code, the paired MQL5 EA, recent log lines, and a symptom description.

Provide a structured root cause analysis:
1. Most likely root cause (be specific — name the function, variable, or condition)
2. Confidence level (high/medium/low) and reasoning
3. Minimal reproduction case (Python snippet that demonstrates the bug without MT5)
4. Suggested fix (concrete code change)
5. Any secondary causes worth checking

Format your response as JSON:
{
  "hypothesis": "specific root cause description",
  "confidence": "high" | "medium" | "low",
  "reasoning": "why you believe this is the cause",
  "reproduction": "python code snippet",
  "suggested_fix": "description of the fix",
  "secondary_causes": ["optional list of other things to check"]
}"""


def _read_safe(path: Path, max_chars: int = 3000) -> str:
    if not path.exists():
        return f"[File not found: {path}]"
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception as e:
        return f"[Read error: {e}]"


def _tail_log(lines: int = 200) -> str:
    log_path = BASE_DIR / "mt5_bridge" / "_live_log.txt"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        return "[Log not available]"


def _find_backtest_report(strategy: str) -> str:
    reports_dir = BASE_DIR / "backtest_reports"
    if not reports_dir.exists():
        return "[No backtest reports directory]"
    matches = sorted(reports_dir.glob(f"*{strategy}*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return "[No backtest report found for this strategy]"
    from html.parser import HTMLParser
    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            if data.strip():
                self.parts.append(data.strip())
        def get(self):
            return "\n".join(self.parts)[:2000]
    p = _P()
    p.feed(matches[0].read_text(encoding="utf-8", errors="replace"))
    return p.get()


def investigate(strategy: str, symptom: str, client: anthropic.Anthropic) -> dict:
    py_path, mq5_path = STRATEGY_MAP.get(strategy.upper(), (None, None))
    py_code = _read_safe(py_path) if py_path else "[Python strategy file not mapped]"
    mq5_code = _read_safe(mq5_path) if mq5_path else "[MQL5 EA not mapped]"
    log_tail = _tail_log()
    backtest = _find_backtest_report(strategy)

    user_msg = (
        f"Strategy: {strategy}\n"
        f"Symptom: {symptom}\n\n"
        f"=== Python Strategy (first 3000 chars) ===\n{py_code}\n\n"
        f"=== MQL5 EA (first 3000 chars) ===\n{mq5_code}\n\n"
        f"=== Last 200 log lines ===\n{log_tail}\n\n"
        f"=== Latest backtest stats ===\n{backtest}"
    )

    # Claude Opus 4.7 + adaptive thinking; auto-fallback to NVIDIA if Claude is down
    sys.path.insert(0, str(BASE_DIR / "trading_agents"))
    from llm_fallback import chat_resilient
    raw = chat_resilient(client, system=SYSTEM_PROMPT, user=user_msg,
                          max_tokens=16000, nvidia_tier="ULTRA",
                          label="debug_investigator").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    result = json.loads(raw[start:end]) if start >= 0 else {"hypothesis": raw, "confidence": "low"}

    # save report
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    md_path = DEBUG_LOG_DIR / f"debug_{strategy}_{ts}.md"
    _write_report(result, md_path, strategy, symptom)

    hypothesis = result.get("hypothesis", "Unknown")
    confidence = result.get("confidence", "?")
    fix = result.get("suggested_fix", "See report")
    notify(
        f"*DebugInvestigator [{strategy}]*\nSymptom: {symptom}\nHypothesis ({confidence}): {hypothesis}\nFix: {fix}\nReport: `{md_path.name}`"
    )
    return result


def _write_report(result: dict, path: Path, strategy: str, symptom: str) -> None:
    lines = [
        f"# Debug Report — {strategy}\n\n",
        f"**Symptom:** {symptom}\n\n",
        f"## Root Cause Hypothesis\n{result.get('hypothesis', '')}\n\n",
        f"**Confidence:** {result.get('confidence', '?')}\n\n",
        f"**Reasoning:** {result.get('reasoning', '')}\n\n",
        f"## Reproduction\n```python\n{result.get('reproduction', '')}\n```\n\n",
        f"## Suggested Fix\n{result.get('suggested_fix', '')}\n\n",
    ]
    if result.get("secondary_causes"):
        lines.append("## Secondary Causes\n")
        for c in result["secondary_causes"]:
            lines.append(f"- {c}\n")
    path.write_text("".join(lines), encoding="utf-8")
    log.info("Debug report: %s", path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--strategy" not in sys.argv or "--symptom" not in sys.argv:
        print("Usage: python -m trading_agents.dev_agents.debug_investigator --strategy S6 --symptom <description>")
        sys.exit(1)
    strat = sys.argv[sys.argv.index("--strategy") + 1]
    symp = sys.argv[sys.argv.index("--symptom") + 1]
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = investigate(strat, symp, client)
    print(json.dumps(result, indent=2))
