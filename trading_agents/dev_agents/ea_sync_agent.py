"""
EASyncAgent — Detects parameter drift between Python strategies and MQL5 EAs.

Compares Python strategy logic against the paired MQL5 EA and generates a
config JSON with correct EA parameters. Never writes to .mq5 files directly.

Usage:
  python -m trading_agents.dev_agents.ea_sync_agent --strategy S6
  python -m trading_agents.dev_agents.ea_sync_agent --all
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

log = logging.getLogger("EASyncAgent")

BASE_DIR = Path(__file__).parent.parent.parent
CONFIGS_DIR = BASE_DIR / "configs"

STRATEGY_MAP = {
    "S1": (BASE_DIR / "mt5_bridge" / "strategy1_swing_scalp.py", BASE_DIR / "mql5_experts" / "ready_ea" / "S1_Swing_Scalp.mq5"),
    "S2": (BASE_DIR / "mt5_bridge" / "strategy2_m5_scalp.py", BASE_DIR / "mql5_experts" / "inspection_ea" / "S2_M5_Scalp.mq5"),
    "S4": (BASE_DIR / "mt5_bridge" / "strategy4_multi_pair.py", BASE_DIR / "mql5_experts" / "inspection_ea" / "S4_MultiPair_Engine.mq5"),
    "S5": (BASE_DIR / "mt5_bridge" / "strategy5_news_spike.py", BASE_DIR / "mql5_experts" / "ready_ea" / "S5_News_Spike_Reversal.mq5"),
    "S6": (BASE_DIR / "mt5_bridge" / "strategy6_asian_range.py", BASE_DIR / "mql5_experts" / "ready_ea" / "S6_Asian_Range_Breakout.mq5"),
}

SYSTEM_PROMPT = """You are EASyncAgent, an expert in both Python trading strategies and MQL5 Expert Advisors.

Given a Python strategy file and its paired MQL5 EA, compare:
1. Session hours (are trading windows identical?)
2. TP/SL ratios (are risk-reward ratios the same?)
3. Entry conditions (do the signal filters match?)
4. Risk parameters (lot sizing, max trades, daily DD limits)
5. Any logic present in one but missing in the other

Respond in JSON:
{
  "in_sync": true | false,
  "discrepancies": [
    {
      "parameter": "parameter name",
      "python_value": "value in Python",
      "ea_value": "value in MQL5 EA",
      "severity": "critical" | "minor",
      "description": "what this means"
    }
  ],
  "recommended_ea_params": {
    "parameter_name": "correct_value"
  },
  "summary": "one-line summary"
}"""


def _read_safe(path: Path, max_chars: int = 5000) -> str:
    if not path.exists():
        return f"[File not found: {path.name}]"
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def sync_strategy(strategy: str, client: anthropic.Anthropic) -> dict:
    entry = STRATEGY_MAP.get(strategy.upper())
    if not entry:
        log.error("Unknown strategy: %s. Available: %s", strategy, list(STRATEGY_MAP.keys()))
        return {"error": f"Unknown strategy: {strategy}"}

    py_path, mq5_path = entry
    py_code = _read_safe(py_path)
    mq5_code = _read_safe(mq5_path)

    user_msg = (
        f"Strategy: {strategy}\n\n"
        f"=== Python strategy ({py_path.name}) ===\n{py_code}\n\n"
        f"=== MQL5 EA ({mq5_path.name}) ===\n{mq5_code}"
    )

    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet (unchanged) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=SYSTEM_PROMPT, user=user_msg, max_tokens=3000,
        model="claude-sonnet-4-6", thinking=False, nvidia_tier="HEAVY",
        label="ea_sync")
    start = raw.find("{")
    end = raw.rfind("}") + 1
    result = json.loads(raw[start:end]) if start >= 0 else {"in_sync": False, "summary": raw}

    # save recommended params to configs/
    ts = datetime.utcnow().strftime("%Y%m%d")
    CONFIGS_DIR.mkdir(exist_ok=True)
    params_path = CONFIGS_DIR / f"ea_params_{strategy}_{ts}.json"
    params_path.write_text(json.dumps({
        "strategy": strategy,
        "generated_at": datetime.utcnow().isoformat(),
        "python_source": py_path.name,
        "ea_source": mq5_path.name,
        "recommended_params": result.get("recommended_ea_params", {}),
        "discrepancies": result.get("discrepancies", []),
    }, indent=2), encoding="utf-8")
    log.info("EA params saved: %s", params_path)

    in_sync = result.get("in_sync", False)
    summary = result.get("summary", "Sync check complete")
    if not in_sync:
        discrepancies = result.get("discrepancies", [])
        critical = [d for d in discrepancies if d.get("severity") == "critical"]
        level = "WARNING" if critical else "INFO"
        msg = (
            f"*EASyncAgent [{strategy}]*: Out of sync — {len(discrepancies)} discrepancies "
            f"({len(critical)} critical)\n{summary}\nParams saved: `{params_path.name}`\n"
            "Apply manually in MT5 terminal."
        )
        notify(msg, level=level)
    else:
        log.info("[%s] In sync: %s", strategy, summary)

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if "--all" in sys.argv:
        for s in STRATEGY_MAP:
            log.info("Checking %s...", s)
            result = sync_strategy(s, client)
            print(f"{s}: {'in sync' if result.get('in_sync') else 'OUT OF SYNC'} — {result.get('summary', '')}")
    elif "--strategy" in sys.argv:
        s = sys.argv[sys.argv.index("--strategy") + 1]
        result = sync_strategy(s, client)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python -m trading_agents.dev_agents.ea_sync_agent --strategy S6 | --all")
        sys.exit(1)
