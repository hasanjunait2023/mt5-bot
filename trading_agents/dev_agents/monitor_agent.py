"""
MonitorAgent — Continuous watchdog for the live MT5 trading system.

Polls _live_state.json every 60 seconds and uses Claude to interpret anomalies.
Run alongside the live trader: python -m trading_agents.dev_agents.monitor_agent
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .notifier import notify

load_dotenv()

log = logging.getLogger("MonitorAgent")

BASE_DIR = Path(__file__).parent.parent.parent
LIVE_STATE = BASE_DIR / "mt5_bridge" / "_live_state.json"
LIVE_LOG = BASE_DIR / "mt5_bridge" / "_live_log.txt"
MONITOR_STATE = BASE_DIR / "logs" / "dev_agents" / "_monitor_state.json"

POLL_INTERVAL = 60  # seconds

SYSTEM_PROMPT = """You are MonitorAgent, a watchdog for a live MT5 algorithmic trading system.
Analyze the account state and recent log lines provided. Identify any anomalies.

Respond in JSON with this exact format:
{
  "level": "INFO" | "WARNING" | "CRITICAL",
  "anomaly": true | false,
  "summary": "one-line summary",
  "details": "brief explanation if anomaly detected, else empty string",
  "recommended_action": "what to do if anomaly, else empty string"
}

Anomaly triggers (report WARNING or CRITICAL):
- Daily drawdown > 15% of equity
- Zero trades placed during an active trading session (London 07-12 UTC, NY 13-17 UTC) for > 4 hours
- 3 or more consecutive stop-outs in the last 10 trades
- Equity dropped > 20% from session open
- Log contains repeated ERROR lines in the last 20 lines
- No log update for > 30 minutes during active session

CRITICAL = action needed immediately. WARNING = monitor closely. INFO = all normal."""


def _read_live_state() -> dict:
    try:
        return json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tail_log(lines: int = 50) -> str:
    try:
        text = LIVE_LOG.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        return ""


def _save_monitor_state(result: dict) -> None:
    result["timestamp"] = datetime.utcnow().isoformat()
    MONITOR_STATE.parent.mkdir(parents=True, exist_ok=True)
    MONITOR_STATE.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _check_once(client: anthropic.Anthropic) -> dict:
    state = _read_live_state()
    log_tail = _tail_log()

    user_content = f"Account state:\n{json.dumps(state, indent=2)}\n\nLast 50 log lines:\n{log_tail}"

    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Haiku (unchanged, no thinking) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=SYSTEM_PROMPT, user=user_content, max_tokens=512,
        model="claude-haiku-4-5-20251001", thinking=False,
        nvidia_tier="MEDIUM", label="monitor")
    # extract JSON from response
    start = raw.find("{")
    end = raw.rfind("}") + 1
    result = json.loads(raw[start:end]) if start >= 0 else {"level": "INFO", "anomaly": False, "summary": raw}
    return result


def run_once() -> dict:
    """Run a single check. Returns the monitor result dict."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = _check_once(client)
    _save_monitor_state(result)
    if result.get("anomaly"):
        level = result.get("level", "WARNING")
        msg = f"*{result.get('summary', 'Anomaly detected')}*\n{result.get('details', '')}\nAction: {result.get('recommended_action', 'Check system')}"
        notify(msg, level=level)
        log.warning("Anomaly detected [%s]: %s", level, result.get("summary"))
    else:
        log.info("System OK: %s", result.get("summary", "No anomalies"))
    return result


def run_loop() -> None:
    """Continuous polling loop. Blocks forever."""
    log.info("MonitorAgent started — polling every %ds", POLL_INTERVAL)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    while True:
        try:
            result = _check_once(client)
            _save_monitor_state(result)
            if result.get("anomaly"):
                level = result.get("level", "WARNING")
                msg = (
                    f"*{result.get('summary', 'Anomaly detected')}*\n"
                    f"{result.get('details', '')}\n"
                    f"Action: {result.get('recommended_action', 'Check system')}"
                )
                notify(msg, level=level)
                log.warning("[%s] %s", level, result.get("summary"))
            else:
                log.info("OK: %s", result.get("summary", "all clear"))
        except Exception as e:
            log.error("Monitor check failed: %s", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--once" in sys.argv:
        result = run_once()
        print(json.dumps(result, indent=2))
    else:
        run_loop()
