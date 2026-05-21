"""
EACoach — Performance analyst, improvement suggester, and demo-to-live progression gate.

Runs every 6 hours. Analyses each tracked EA's live performance, decides if it's
ready to graduate from demo to live, proposes improvements, and opens a real
dialogue with Junait via Telegram before any decision is applied.

Usage:
  python -m trading_agents.ea_agents.ea_coach               # run one full cycle
  python -m trading_agents.ea_agents.ea_coach --ea S6       # analyse a single EA
  python -m trading_agents.ea_agents.ea_coach --loop        # run every 6h continuously
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("EACoach")

BASE_DIR   = Path(__file__).parent.parent.parent
LIVE_STATE = BASE_DIR / "mt5_bridge" / "_live_state.json"
CONFIG_FILE = Path(__file__).parent / "ea_agents_config.json"
COACH_STATE = BASE_DIR / "logs" / "ea_agents" / "_coach_state.json"
GUARDIAN_STATE = BASE_DIR / "logs" / "ea_agents" / "_guardian_state.json"
BACKTEST_DIR = BASE_DIR / "backtest_reports"
CONFIGS_DIR  = BASE_DIR / "configs"

SYSTEM_PROMPT = """You are EACoach, a senior trading systems analyst and mentor for EA lifecycle management.

You receive live performance data for a trading EA running on a demo or live MT5 account.

Your job:
1. Assess current performance against benchmarks (win rate ≥55%, PF ≥1.4, daily DD ≤3%)
2. Identify what's working and what needs improvement
3. Propose ONE concrete improvement per cycle (be specific: "restrict to London session 07:00-11:00")
4. Decide if the EA is ready to graduate from demo to live (if on demo)
5. Flag pairs or sessions that are consistently losing

Respond in JSON:
{
  "lifecycle_stage": "demo" | "ready_to_graduate" | "live" | "needs_work",
  "performance_summary": "2-3 sentence assessment",
  "improvement_proposal": {
    "type": "session_restriction" | "pair_disable" | "parameter_change" | "none",
    "description": "specific change proposed",
    "expected_impact": "why this will help"
  },
  "user_question": "exact question to ask Junait (null if no decision needed)",
  "question_type": "graduation" | "improvement" | "pair_disable" | null,
  "urgent": false
}"""


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_coach_state() -> dict:
    if COACH_STATE.exists():
        try:
            return json.loads(COACH_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_coach_state(state: dict) -> None:
    COACH_STATE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    COACH_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents.dev_agents.notifier import notify
        notify(msg, level=level, category="ea_coach")
    except Exception as e:
        log.warning("Notify failed: %s", e)


def _read_live_state() -> dict:
    try:
        return json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_backtest_summary(ea_name: str) -> str:
    """Return text summary from latest backtest HTML for this EA."""
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

    matches = sorted(BACKTEST_DIR.glob(f"*{ea_name}*.html"), key=lambda p: p.stat().st_mtime, reverse=True) if BACKTEST_DIR.exists() else []
    if not matches:
        return "No backtest report available."
    p = _P()
    p.feed(matches[0].read_text(encoding="utf-8", errors="replace"))
    return p.get()


def _build_performance_snapshot(ea_name: str, live_state: dict, coach_state: dict) -> dict:
    """Assemble performance data for Claude from live state + historical coach records."""
    account = live_state.get("account", {})
    ea_positions = live_state.get("ea_positions", {}).get(ea_name, [])
    daily_trades = live_state.get("daily_trades", {})

    # pull coach history for this EA
    ea_history = coach_state.get("eas", {}).get(ea_name, {})
    lifecycle_stage = ea_history.get("lifecycle_stage", "demo")
    decision_history = ea_history.get("decision_history", [])

    # simple win rate from current open positions (approximation)
    wins = sum(1 for p in ea_positions if p.get("profit", 0) > 0)
    total = len(ea_positions)
    live_win_rate = round(wins / total * 100, 1) if total > 0 else None

    return {
        "ea_name": ea_name,
        "lifecycle_stage": lifecycle_stage,
        "account": {
            "balance": account.get("balance"),
            "equity": account.get("equity"),
            "daily_pnl": account.get("daily_pnl"),
            "daily_dd_pct": account.get("daily_dd_pct"),
            "total_dd_pct": account.get("total_dd_pct"),
        },
        "live_positions": total,
        "live_win_rate_pct": live_win_rate,
        "daily_trades_today": sum(daily_trades.values()),
        "is_demo": live_state.get("account", {}).get("server", "").lower().find("demo") >= 0,
        "days_on_demo": ea_history.get("days_on_demo", 0),
        "total_trades_on_demo": ea_history.get("total_trades_on_demo", 0),
        "avg_win_rate_7d": ea_history.get("avg_win_rate_7d"),
        "avg_pf_7d": ea_history.get("avg_pf_7d"),
        "recent_decision_history": decision_history[-3:],
    }


def _check_pending_question_timeout(ea_name: str, coach_state: dict) -> bool:
    """Return True if there's a pending question for this EA that's less than 48h old."""
    ea_data = coach_state.get("eas", {}).get(ea_name, {})
    pending = ea_data.get("pending_question")
    if not pending:
        return False
    asked_at = pending.get("asked_at", "")
    try:
        asked = datetime.fromisoformat(asked_at)
        if datetime.now(timezone.utc) - asked < timedelta(hours=48):
            log.info("[%s] Pending question still within 48h window — skipping new question", ea_name)
            return True
    except Exception:
        pass
    return False


def _write_params_config(ea_name: str, change_description: str, proposal: dict) -> Path:
    """Write an approved improvement to configs/ for manual MT5 application."""
    CONFIGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = CONFIGS_DIR / f"ea_coach_change_{ea_name}_{ts}.json"
    path.write_text(json.dumps({
        "ea": ea_name,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "change_type": proposal.get("type"),
        "description": change_description,
        "expected_impact": proposal.get("expected_impact"),
        "instruction": "Apply this change manually in MT5 terminal / EA parameters.",
    }, indent=2), encoding="utf-8")
    return path


def analyse_ea(ea_name: str, client: anthropic.Anthropic) -> dict:
    """Run one analysis cycle for a single EA. Returns the Claude assessment."""
    cfg = _load_config()
    live_state = _read_live_state()
    coach_state = _load_coach_state()

    # skip if awaiting user reply
    if _check_pending_question_timeout(ea_name, coach_state):
        return {"skipped": True, "reason": "awaiting_user_reply"}

    snapshot = _build_performance_snapshot(ea_name, live_state, coach_state)
    backtest_summary = _get_backtest_summary(ea_name)
    graduation_criteria = cfg.get("graduation_criteria", {})

    user_msg = (
        f"EA: {ea_name}\n"
        f"Graduation criteria: {json.dumps(graduation_criteria)}\n\n"
        f"Current performance snapshot:\n{json.dumps(snapshot, indent=2)}\n\n"
        f"Latest backtest summary:\n{backtest_summary}"
    )

    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet (unchanged) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=SYSTEM_PROMPT, user=user_msg, max_tokens=1024,
        model="claude-sonnet-4-6", thinking=False, nvidia_tier="HEAVY",
        label="ea_coach")
    start = raw.find("{")
    end = raw.rfind("}") + 1
    result = json.loads(raw[start:end]) if start >= 0 else {"lifecycle_stage": "demo", "performance_summary": raw}

    log.info("[%s] Stage: %s | Summary: %s", ea_name, result.get("lifecycle_stage"), result.get("performance_summary", "")[:80])

    # update coach state for this EA
    ea_data = coach_state.setdefault("eas", {}).setdefault(ea_name, {})
    ea_data["lifecycle_stage"] = result.get("lifecycle_stage", "demo")
    ea_data["last_analysis"] = datetime.now(timezone.utc).isoformat()
    ea_data["last_summary"] = result.get("performance_summary", "")

    # handle user question
    question = result.get("user_question")
    if question:
        _send_user_question(ea_name, question, result, ea_data)

    _save_coach_state(coach_state)
    return result


def _send_user_question(ea_name: str, question: str, result: dict, ea_data: dict) -> None:
    """Send the pending question to Junait via Telegram and record it."""
    stage = result.get("lifecycle_stage", "")
    summary = result.get("performance_summary", "")
    proposal = result.get("improvement_proposal", {})

    # build a rich context message
    proposal_text = ""
    if proposal.get("type") != "none" and proposal.get("description"):
        proposal_text = f"\n*Proposal:* {proposal['description']}\n*Expected impact:* {proposal.get('expected_impact', '')}"

    msg = (
        f"*EACoach [{ea_name}]* — {stage.replace('_', ' ').title()}\n\n"
        f"{summary}{proposal_text}\n\n"
        f"*{question}*\n\n"
        f"Reply to Maic: YES / NO / TEST MORE"
    )
    level = "WARNING" if result.get("urgent") else "INFO"
    _notify(msg, level=level)

    # record pending question
    ea_data["pending_question"] = {
        "question": question,
        "type": result.get("question_type"),
        "proposal": result.get("improvement_proposal"),
        "asked_at": datetime.now(timezone.utc).isoformat(),
    }
    log.info("[%s] Question sent to Junait: %s", ea_name, question)


def record_user_answer(ea_name: str, answer: str) -> str:
    """Process Junait's reply to a pending question. Called by Maic when user replies."""
    coach_state = _load_coach_state()
    ea_data = coach_state.get("eas", {}).get(ea_name, {})
    pending = ea_data.get("pending_question")
    if not pending:
        return f"No pending question for {ea_name}"

    answer_upper = answer.strip().upper()
    qtype = pending.get("type")
    proposal = pending.get("proposal", {})

    # record decision
    ea_data.setdefault("decision_history", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": pending.get("question"),
        "answer": answer_upper,
        "type": qtype,
    })

    response_msg = ""

    if answer_upper == "YES":
        if qtype == "graduation":
            # NON-BYPASSABLE: human YES is necessary but not sufficient.
            import sys as _sys, pathlib as _pl
            _ta = str(_pl.Path(__file__).resolve().parents[1])
            if _ta not in _sys.path: _sys.path.insert(0, _ta)
            from promotion_gate import can_go_live
            allowed, reasons = can_go_live(ea_name)
            if not allowed:
                bullet = "\n- ".join(reasons)
                ea_data.setdefault("graduation_blocks", []).append({
                    "at": datetime.now(timezone.utc).isoformat(),
                    "reasons": reasons,
                })
                response_msg = (f"EACoach: {ea_name} graduation BLOCKED by "
                                f"safety gate despite YES:\n- {bullet}")
                _notify(f"*EACoach [{ea_name}]*: 🚫 Graduation BLOCKED — "
                        f"evidence insufficient:\n- {bullet}\n"
                        f"Fix the above, then re-approve.", level="WARNING")
            else:
                ea_data["lifecycle_stage"] = "live"
                ea_data["graduated_at"] = datetime.now(timezone.utc).isoformat()
                response_msg = f"EACoach: {ea_name} marked for live deployment. Params config written — apply in MT5."
                _notify(f"*EACoach [{ea_name}]*: ✅ Graduated to LIVE "
                        f"(safety gate passed). Apply settings in MT5.", level="INFO")

        elif qtype in ("improvement", "pair_disable", "session_restriction"):
            path = _write_params_config(ea_name, proposal.get("description", ""), proposal)
            response_msg = f"EACoach: Change approved. Config written to `{path.name}` — apply manually in MT5."
            _notify(f"*EACoach [{ea_name}]*: Improvement approved.\nConfig: `{path.name}`\nApply manually in MT5.", level="INFO")

    elif answer_upper == "NO":
        # don't ask again for 48h
        ea_data["pending_question"]["rejected_at"] = datetime.now(timezone.utc).isoformat()
        response_msg = f"EACoach: Understood. Will not re-ask for 48 hours."
        _notify(f"*EACoach [{ea_name}]*: Change rejected by Junait. Noted — monitoring continues.", level="INFO")

    elif "TEST" in answer_upper:
        # trigger EAValidator for deeper testing
        response_msg = f"EACoach: Running extended validation on {ea_name}..."
        _notify(f"*EACoach [{ea_name}]*: Extended testing requested — running EAValidator.", level="INFO")
        try:
            from trading_agents.ea_agents.ea_validator import run_full_validation
            import anthropic as _anth
            client = _anth.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            run_full_validation(ea_name, proposed_change=proposal.get("description", ""), client=client)
        except Exception as e:
            response_msg += f" (Validator error: {e})"

    ea_data.pop("pending_question", None)  # clear pending
    _save_coach_state(coach_state)
    return response_msg


def run_cycle(filter_ea: str | None = None) -> None:
    cfg = _load_config()
    tracked = [filter_ea] if filter_ea else cfg.get("tracked_eas", ["S6"])
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    for ea in tracked:
        log.info("Analysing %s...", ea)
        try:
            analyse_ea(ea, client)
        except Exception as e:
            log.error("[%s] Coach cycle error: %s", ea, e)


def run_loop(filter_ea: str | None = None) -> None:
    cfg = _load_config()
    hours = cfg.get("coach_cycle_hours", 6)
    log.info("EACoach loop started — running every %dh", hours)
    while True:
        run_cycle(filter_ea)
        time.sleep(hours * 3600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    filter_ea = None
    if "--ea" in sys.argv:
        filter_ea = sys.argv[sys.argv.index("--ea") + 1]
    if "--loop" in sys.argv:
        run_loop(filter_ea)
    else:
        run_cycle(filter_ea)
