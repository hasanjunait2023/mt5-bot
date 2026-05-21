"""
Maic — CEO Agent of the Fx Vault MT5 Bot System.

Central orchestrator: receives tasks from any interface (Telegram, CLI, etc.),
thinks through them, delegates to the right sub-agent or script, and reports back.
"""

import subprocess
import json
import re
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("Maic")

BASE_DIR = Path(__file__).parent.parent

HISTORY_FILE = BASE_DIR / "trading_agents" / ".maic_history.json"

MAIC_SYSTEM_PROMPT = """You are Maic, the CEO Agent of the Fx Vault MT5 Bot System, owned and operated by Junait (Jafrul Hasan Junait, @junaitfx).

## Identity
You are the central intelligence and master orchestrator of this automated trading system. You think strategically, delegate precisely, and report clearly. Every message from Junait comes through you first — nothing bypasses the CEO.

## System Architecture You Oversee

### Trading Core (mt5_bridge/)
- mt5_bridge.py — Live trade execution via MetaTrader 5
- backtest.py — Historical strategy backtesting
- optimizer.py — Parameter optimization for strategies
- xauusd_backtest.py — Dedicated XAUUSD (Gold) backtester
- session_analyzer.py — Trading session performance analysis
- ml_enhanced_signals.py — ML-powered signal generation
- news_filter.py — Economic news event filter
- mtf_strategy.py — Multi-timeframe strategy

### AI Agents (trading_agents/)
- video_analysis_agent.py — Extracts strategies from trading videos (Whisper + Claude Vision)
- strategy_researcher.py — Researches and validates new strategies
- execution_manager.py — Manages trade execution logic
- performance_optimizer.py — Analyzes and optimizes portfolio performance
- nvidia_model_router.py — Routes to NANO/LIGHT/MEDIUM/HEAVY NVIDIA NIM models

### Strategy Scout (trading_agents/strategy_scout/) — Autonomous strategy discovery
- strategy_scout.py — Collects trading edges from RSS/news, invents new setups with Claude, normalizes to canonical params
- growth_pipeline.py — Autonomous loop: Scout → backtest → pitches winners to YOU (Maic) → you delegate dev_lead + ea_team

### Supervisor (trading_agents/supervisor_agent.py) — Workspace-wide heartbeat
- supervisor_agent.py — Runs every 10h; audits ALL layers; escalates bugs to dev team; confirms resolution; sends full Telegram report

### EA Lifecycle Agents (trading_agents/ea_agents/) — EA management team
- ea_lifecycle_manager.py — Orchestrator, routes EA tasks (entry point for all EA team requests)
- ea_guardian.py — Live watchdog: detects anomalies, auto-escalates bugs to dev team
- ea_coach.py — Performance analyst: 6h cycles, improvement proposals, demo→live gate, Telegram dialogue
- ea_validator.py — Compatibility tester: tests EA across pairs × sessions × market conditions

### JTCC — Junait Trading Command Center (trading_agents/jtcc/)
The new 4-layer autonomous signal engine. Token-efficient (max 15 Claude API calls/day).
Runs alongside EAs on magic 20260600 (separate from EA magics).
- jtcc.main — Signal engine (L0 feed → L1 analysis → L2 strategy army → L3 master → L4 execution)
- jtcc.guardian — JTCC-specific watchdog (60s cycle, escalates via incident_pipeline)
- jtcc.coach — 6h analysis, proposes disable/pause/expand per strategy
- jtcc.digest — Daily 00:30 BD summary to Telegram digest thread
- strategies/*.yaml — 13 YAML strategies (hot-reloadable, drop new file = auto-load)
- Master Agent uses llm_fallback (Claude→NVIDIA), same as other agents
- All notifications via telegram_hq (live_trading, critical, ea_coach, digest threads)
- Dashboard: /jtcc page with equity curve, heatmap, latency, confluence radar

### Dev Agents (trading_agents/dev_agents/) — Engineering team
- dev_lead.py — Orchestrates all dev agents (entry point for all dev tasks)
- monitor_agent.py — Live system watchdog (anomaly detection)
- backtest_analyst.py — Auto-analyzes backtest reports, generates verdicts
- test_writer.py — Generates pytest test suites for any Python module
- code_reviewer.py — Claude-powered code review on git diffs
- debug_investigator.py — Root cause analysis for strategy issues
- ea_sync_agent.py — Detects Python/MQL5 EA parameter drift
- doc_keeper.py — Keeps docstrings and documentation up to date

### Dashboard
- FastAPI backend at dashboard/backend/
- Real-time WebSocket position tracking
- Trade history, logs, agent status

### Communication & Productivity
- Telegram Bot (@fxvaultjunaitmt5bot) — Primary channel from Junait to you
- Claude Code CLI — Direct interface
- Notion (API connected) — Create pages, update databases, log trade reports, store strategy notes

## Risk Parameters You Enforce
- Risk per trade: 1% of equity
- Risk:Reward: 1:2 minimum
- Daily drawdown limit: 3%
- Maximum drawdown: 20%
- Compounding: equity-based lot sizing

## Proven Results
- XAUUSD: +362% return ($462 from $100), best session configs
- EURUSD: +90% return ($190 from $100)
- Compound strategy: 1.5% risk per trade

## How You Work
When Junait gives you a task:
1. **UNDERSTAND** — Confirm what was asked, identify the goal
2. **THINK** — Break it into actionable steps, identify which sub-system handles it
3. **DELEGATE** — State what you're delegating and to which agent/script
4. **EXECUTE** — If you can run it, output an EXECUTE block (see below)
5. **REPORT** — Summarize results, flag issues, recommend next steps

## Delegation Protocol
When you need to trigger an action, include this in your response:
```
[DELEGATE: script_name | param1=value1 param2=value2]
```

Available delegations:
- `[DELEGATE: backtest | symbol=XAUUSD timeframe=M15 sessions=london,new_york]`
- `[DELEGATE: optimize | symbol=EURUSD strategy=mtf]`
- `[DELEGATE: live_status]` — check current MT5 positions
- `[DELEGATE: video_analysis | path=videos/strategy.mp4]`
- `[DELEGATE: session_analysis | symbol=XAUUSD]`
- `[DELEGATE: ml_signals | symbol=XAUUSD]`
- `[DELEGATE: dev_lead | task="write tests for backtest.py"]`
- `[DELEGATE: dev_lead | task="debug S6 no trades after reconnect"]`
- `[DELEGATE: dev_lead | task="review code HEAD"]`
- `[DELEGATE: dev_lead | task="analyze backtests"]`
- `[DELEGATE: dev_lead | task="sync S6 EA params"]`
- `[DELEGATE: dev_lead | task="weekly health check"]`
- `[DELEGATE: ea_team | task="check S6 health"]`
- `[DELEGATE: ea_team | task="is S6 ready for live?"]`
- `[DELEGATE: ea_team | task="test S6 on GBPUSD"]`
- `[DELEGATE: ea_team | task="run full validation on S6"]`
- `[DELEGATE: ea_team | task="S6 answer YES"]`
- `[DELEGATE: ea_team | task="weekly EA report"]`
- `[DELEGATE: supervisor | --once]` — run a full system audit right now
- `[DELEGATE: scout | --once]` — run one strategy-discovery cycle right now

## Delegation Integrity (non-negotiable)
- If a delegation result begins with `[DELEGATION FAILED ...]`, you MUST report
  it to Junait as a FAILURE, quote the reason, and propose a next step.
- NEVER claim a task succeeded, or summarize truncated/timed-out output as
  complete. A timeout or non-zero exit is a failure, not a partial success.
- If you are unsure whether an action ran, say so explicitly — do not guess.

## Communication Style
- Be decisive and strategic — you are the CEO
- Confirm understanding before acting on ambiguous requests
- Always state what you delegated and why
- Report outcomes in bullet points with numbers where relevant
- Keep Junait informed at every step
- If something is outside your current capability, say so clearly and suggest how to enable it

You are always on. You are always thinking. You manage everything so Junait only needs to communicate the goal.
"""


def _load_history(chat_id: str) -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data.get(str(chat_id), [])
    except Exception:
        return []


def _save_history(chat_id: str, history: list) -> None:
    data = {}
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[str(chat_id)] = history[-40:]  # keep last 20 exchanges
    HISTORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_prompt(history: list, user_message: str) -> str:
    parts = []
    for entry in history[-10:]:  # last 10 exchanges as context
        parts.append(f"Junait: {entry['user']}")
        parts.append(f"Maic: {entry['assistant']}")
    parts.append(f"Junait: {user_message}")
    return "\n\n".join(parts)


def _run_delegation(delegation_str: str) -> str:
    """Parse and execute a [DELEGATE: ...] block."""
    match = re.match(r"(\w+)\s*\|?\s*(.*)", delegation_str.strip())
    if not match:
        return f"Could not parse delegation: {delegation_str}"

    script = match.group(1).strip()
    params_raw = match.group(2).strip()

    script_map = {
        "backtest": BASE_DIR / "mt5_bridge" / "backtest.py",
        "optimize": BASE_DIR / "mt5_bridge" / "optimizer.py",
        "xauusd_backtest": BASE_DIR / "mt5_bridge" / "xauusd_backtest.py",
        "session_analysis": BASE_DIR / "mt5_bridge" / "session_analyzer.py",
        "ml_signals": BASE_DIR / "mt5_bridge" / "ml_enhanced_signals.py",
        "video_analysis": BASE_DIR / "trading_agents" / "video_analysis_agent.py",
        "live_status": BASE_DIR / "mt5_bridge" / "mt5_bridge.py",
        "dev_lead": BASE_DIR / "trading_agents" / "dev_agents" / "dev_lead.py",
        "ea_team":    BASE_DIR / "trading_agents" / "ea_agents"  / "ea_lifecycle_manager.py",
        "supervisor": BASE_DIR / "trading_agents" / "supervisor_agent.py",
        "scout":      BASE_DIR / "trading_agents" / "strategy_scout" / "growth_pipeline.py",
    }

    if script not in script_map:
        return f"Unknown delegation target: {script}. Available: {', '.join(script_map.keys())}"

    script_path = script_map[script]
    if not script_path.exists():
        return f"Script not found: {script_path}"

    # Package modules MUST run via `-m` so their intra-package imports
    # (`from .notifier import notify`, `from trading_agents... import ...`)
    # resolve. cwd=BASE_DIR puts the trading_agents namespace package on
    # sys.path. Standalone scripts (mt5_bridge/*, video_analysis) stay as
    # file-path invocations.
    _MODULE_TARGETS = {
        "dev_lead":   "trading_agents.dev_agents.dev_lead",
        "ea_team":    "trading_agents.ea_agents.ea_lifecycle_manager",
        "supervisor": "trading_agents.supervisor_agent",
        "scout":      "trading_agents.strategy_scout.growth_pipeline",
    }
    if script in _MODULE_TARGETS:
        cmd = [sys.executable, "-m", _MODULE_TARGETS[script]]
    else:
        cmd = [sys.executable, str(script_path)]
    if params_raw:
        for param in params_raw.split():
            cmd.append(f"--{param}" if "=" in param else param)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=BASE_DIR)
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0:
            # Non-zero exit — the script FAILED. Never let this be summarized
            # as success: mark it explicitly so Maic reports the failure.
            return (f"[DELEGATION FAILED rc={result.returncode}] {script} "
                    f"errored — DO NOT report this as success.\n"
                    f"{(err or out)[:1800]}")
        return (out or err or "Script ran with no output.")[:2000]
    except subprocess.TimeoutExpired:
        return (f"[DELEGATION FAILED: timeout] {script} exceeded 120s and was "
                f"killed — result is INCOMPLETE; DO NOT report success.")
    except Exception as e:
        return f"[DELEGATION FAILED: error] {script}: {e}"


# ── NVIDIA fallback ───────────────────────────────────────────────────────────

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Primary CEO brain: Claude Opus 4.7 via Claude CLI (see _call_claude --model).
# These NVIDIA models are the offline fallback only, used when the Claude CLI
# is unavailable: Nemotron Super 49B (fast ~1.5s) → Mistral Large 675B (deepest).
NVIDIA_CEO_MODEL         = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
NVIDIA_CEO_MODEL_FALLBACK = "mistralai/mistral-large-3-675b-instruct-2512"


def _get_nvidia_key() -> str:
    key = os.getenv("NVIDIA_API_KEY", "")
    if not key:
        # Read directly from the router module which has the key hardcoded
        try:
            sys.path.insert(0, str(BASE_DIR / "trading_agents"))
            from nvidia_model_router import NVIDIA_API_KEY as router_key
            return router_key
        except Exception:
            pass
    return key


def _call_nvidia(history: list, user_message: str) -> str:
    """Call NVIDIA NIM with full conversation history. Returns response text."""
    try:
        from openai import OpenAI
    except ImportError:
        return None  # openai not installed

    api_key = _get_nvidia_key()
    if not api_key:
        return None

    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)

    # Build multi-turn messages with history
    messages = [{"role": "system", "content": MAIC_SYSTEM_PROMPT}]
    for entry in history[-10:]:
        messages.append({"role": "user",      "content": entry["user"]})
        messages.append({"role": "assistant", "content": entry["assistant"]})
    messages.append({"role": "user", "content": user_message})

    for model in (NVIDIA_CEO_MODEL, NVIDIA_CEO_MODEL_FALLBACK):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=4096,
                timeout=120,
            )
            msg = resp.choices[0].message
            content = (getattr(msg, "content", None) or "").strip()
            # Nemotron-style reasoning models put the answer in reasoning_content
            # when content is empty. Pull from there so we never silently fail.
            if not content:
                rc = (getattr(msg, "reasoning_content", None) or "").strip()
                if rc:
                    # Strip any leading <think>...</think> block if present
                    cleaned = re.sub(r"^<think>.*?</think>\s*", "", rc, flags=re.S)
                    content = cleaned.strip() or rc
            if content:
                log.info(f"[Maic] NVIDIA fallback responded via {model}")
                return content
            log.warning(f"[Maic] NVIDIA model {model} returned empty content+reasoning")
        except Exception as e:
            log.warning(f"[Maic] NVIDIA model {model} failed: {e}")

    return None


# ── Primary + fallback chat ───────────────────────────────────────────────────

def _call_claude(full_prompt: str) -> str | None:
    """Try Claude CLI. Returns response text or None on any failure."""
    try:
        stdin_payload = f"[SYSTEM CONTEXT]\n{MAIC_SYSTEM_PROMPT}\n\n[CONVERSATION]\n{full_prompt}"
        result = subprocess.run(
            # CEO runs on the most capable model — Opus 4.7
            ["claude", "-p", "--model", "claude-opus-4-7", "--no-session-persistence"],
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(BASE_DIR),
            encoding="utf-8",
            errors="replace"
        )
        text = result.stdout.strip() or result.stderr.strip()
        # Treat error-only output as failure so NVIDIA kicks in
        if text and result.returncode == 0:
            return text
        log.warning(f"[Maic] Claude CLI exited {result.returncode}: {text[:120]}")
        return None
    except subprocess.TimeoutExpired:
        log.warning("[Maic] Claude CLI timed out — switching to NVIDIA")
        return None
    except FileNotFoundError:
        log.warning("[Maic] Claude CLI not found — switching to NVIDIA")
        return None
    except Exception as e:
        log.warning(f"[Maic] Claude CLI error: {e} — switching to NVIDIA")
        return None


def _call_claude_followup(followup_payload: str) -> str | None:
    """Claude CLI call for delegation followup. Returns text or None."""
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-opus-4-7", "--no-session-persistence"],
            input=followup_payload,
            capture_output=True, text=True, timeout=120,
            cwd=str(BASE_DIR), encoding="utf-8", errors="replace"
        )
        text = result.stdout.strip()
        return text if text and result.returncode == 0 else None
    except Exception:
        return None


_ACTION_KW = ("backtest", "optimize", "run ", "audit", "validate", "deploy",
              "status", "position", "analy", "sync", "health check",
              "go live", "graduate", "scout", "supervisor", "ml signal")


def _looks_actionable(msg: str) -> bool:
    """Heuristic: did Junait likely ask for an operation? Used only to flag a
    dropped action transparently — never to auto-execute (the live bridge is
    not something to fire on a fuzzy keyword guess)."""
    m = msg.lower()
    return any(k in m for k in _ACTION_KW)


def chat(chat_id: str, user_message: str) -> str:
    """
    Main entry point. Pass a message from any interface and get Maic's response.
    Tries Claude CLI first; falls back to NVIDIA NIM if Claude is unavailable.
    Maintains conversation history per chat_id.
    """
    history = _load_history(chat_id)
    full_prompt = _build_prompt(history, user_message)

    # ── Primary: Claude CLI ───────────────────────────────────────────────────
    response = _call_claude(full_prompt)
    backend = "claude"

    # ── Fallback: NVIDIA NIM ──────────────────────────────────────────────────
    if response is None:
        log.info("[Maic] Falling back to NVIDIA NIM...")
        response = _call_nvidia(history, user_message)
        backend = "nvidia"

    if response is None:
        return "Maic is temporarily unavailable — both Claude CLI and NVIDIA API failed. Please try again shortly."

    # ── Handle delegations ────────────────────────────────────────────────────
    delegations = re.findall(r"\[DELEGATE:\s*([^\]]+)\]", response)
    if delegations:
        delegation_results = []
        for d in delegations:
            outcome = _run_delegation(d)
            delegation_results.append(f"**Result from {d.split('|')[0].strip()}:**\n{outcome}")

        if delegation_results:
            results_context = "\n\n".join(delegation_results)
            followup_payload = (
                f"[SYSTEM CONTEXT]\n{MAIC_SYSTEM_PROMPT}\n\n[CONVERSATION]\n"
                f"{full_prompt}\n\nMaic: {response}\n\n"
                f"[DELEGATION RESULTS]\n{results_context}\n\n"
                f"Junait: [please summarize the delegation results above]"
            )
            if backend == "claude":
                final_response = _call_claude_followup(followup_payload) or response
            else:
                # Use NVIDIA for followup too
                nvidia_followup = _call_nvidia(
                    history + [{"user": user_message, "assistant": response}],
                    f"[Delegation results]\n{results_context}\n\nPlease summarize these results."
                )
                final_response = nvidia_followup or response

            final_response += f"\n\n[via {backend.upper()}]" if backend == "nvidia" else ""
            history.append({"user": user_message, "assistant": final_response,
                            "timestamp": datetime.now().isoformat()})
            _save_history(chat_id, history)
            return final_response

    if backend == "nvidia":
        response += "\n\n[via NVIDIA NIM — Claude CLI unavailable]"

    # Fail-safe: an actionable request that produced NO delegation was likely
    # dropped (model omitted the [DELEGATE] block). Don't silently swallow it,
    # and don't risk auto-firing scripts against the live bridge — flag it.
    if _looks_actionable(user_message):
        log.warning("[Maic] Actionable request with no delegation: %r", user_message[:120])
        response += ("\n\n⚠️ I did not run any operation for this. If you "
                     "intended an action, reply with an explicit command "
                     '(e.g. "backtest XAUUSD M15") and I will execute it.')

    history.append({"user": user_message, "assistant": response,
                    "timestamp": datetime.now().isoformat()})
    _save_history(chat_id, history)
    return response


def clear_history(chat_id: str) -> None:
    history = _load_history(chat_id)
    history.clear()
    _save_history(chat_id, history)


if __name__ == "__main__":
    # Direct CLI test: python maic_ceo_agent.py "your message"
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        result = chat("cli_user", msg)
        sys.stdout.buffer.write(result.encode("utf-8", errors="replace") + b"\n")
    else:
        sys.stdout.buffer.write(b"Usage: python maic_ceo_agent.py 'your message to Maic'\n")
