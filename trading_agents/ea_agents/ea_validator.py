"""
EAValidator — Tests an EA across multiple pairs, sessions, and market conditions.

Produces a compatibility matrix so EACoach always comes to Junait with evidence.
Called by EACoach automatically, or run standalone for deep validation.

Usage:
  python -m trading_agents.ea_agents.ea_validator --ea S6
  python -m trading_agents.ea_agents.ea_validator --ea S6 --change "restrict to London session"
  python -m trading_agents.ea_agents.ea_validator --ea S6 --mode full
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("EAValidator")

BASE_DIR    = Path(__file__).parent.parent.parent
CONFIG_FILE = Path(__file__).parent / "ea_agents_config.json"
VALIDATOR_STATE = BASE_DIR / "logs" / "ea_agents" / "_validator_results.json"

INTERPRETATION_PROMPT = """You are EAValidator, an expert in algorithmic trading strategy validation.

Given backtest results across multiple pairs and sessions, produce a clear compatibility verdict.

Respond in JSON:
{
  "compatible_pairs": ["list of pairs that PASS"],
  "incompatible_pairs": ["list of pairs that FAIL"],
  "best_session": "session name",
  "overall_verdict": "PASS" | "CONDITIONAL_PASS" | "FAIL",
  "recommendation": "specific actionable recommendation in one sentence",
  "confidence": "high" | "medium" | "low"
}

PASS criteria: profit_factor >= 1.4 AND win_rate >= 52% AND max_drawdown < 15%
FAIL criteria: profit_factor < 1.0 on majority of conditions"""


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents.dev_agents.notifier import notify
        notify(msg, level=level, category="ea_validator")
    except Exception as e:
        log.warning("Notify failed: %s", e)


def _run_backtest_for_pair(ea_name: str, symbol: str, session: str, months: int = 3) -> dict | None:
    """Run a backtest for a specific EA/symbol/session combination."""
    try:
        import sys as _sys
        bt_path = BASE_DIR / "mt5_bridge" / "backtest.py"
        if not bt_path.exists():
            log.warning("backtest.py not found at %s", bt_path)
            return None

        # import and call directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("backtest", bt_path)
        bt_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bt_mod)

        # build params based on EA config
        params = {}
        if hasattr(bt_mod, "DEFAULT_PARAMS"):
            params = bt_mod.DEFAULT_PARAMS.copy()

        # apply session filter if possible
        session_hours = _load_config().get("test_sessions", {}).get(session, [])
        if session_hours and len(session_hours) == 2:
            params["SessionStart"] = session_hours[0]
            params["SessionEnd"] = session_hours[1]

        # run backtest
        if hasattr(bt_mod, "run_backtest"):
            result = bt_mod.run_backtest(symbol=symbol, months=months, params=params)
            return result
        elif hasattr(bt_mod, "Backtester"):
            bt = bt_mod.Backtester(symbol=symbol, initial_balance=1000, params=params)
            trades = bt.run(months=months)
            return bt.get_metrics(trades) if trades else None
    except Exception as e:
        log.warning("Backtest failed for %s/%s/%s: %s", ea_name, symbol, session, e)
        return None


def _score_result(result: dict | None, criteria: dict) -> tuple[str, dict]:
    """Return (verdict, metrics) for a single backtest result."""
    if not result:
        return "NO_DATA", {}

    metrics = result.get("metrics", result)  # handle both flat and nested
    pf = metrics.get("profit_factor", 0)
    wr = metrics.get("win_rate_pct", metrics.get("win_rate", 0))
    dd = metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 100))

    min_pf = criteria.get("min_profit_factor", 1.4)
    min_wr = criteria.get("min_win_rate_pct", 52)
    max_dd = criteria.get("max_drawdown_pct", 15)

    passed = pf >= min_pf and wr >= min_wr and dd <= max_dd
    return ("PASS" if passed else "FAIL"), {"pf": round(pf, 2), "wr": round(wr, 1), "dd": round(dd, 1)}


def run_full_validation(ea_name: str, proposed_change: str = "", client: anthropic.Anthropic | None = None) -> dict:
    """
    Test EA across all configured pairs × sessions. Returns full compatibility matrix.
    Saves results to _validator_results.json and notifies Junait.
    """
    cfg = _load_config()
    pairs = cfg.get("test_pairs", ["EURUSD", "XAUUSD", "GBPUSD"])
    sessions = list(cfg.get("test_sessions", {"london": [], "new_york": []}).keys())
    criteria = cfg.get("validator_pass_criteria", {})

    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    raw_results = {}
    log.info("EAValidator: testing %s across %d pairs × %d sessions", ea_name, len(pairs), len(sessions))

    for pair in pairs:
        for session in sessions:
            key = f"{pair}_{session}"
            log.info("  Testing %s...", key)
            result = _run_backtest_for_pair(ea_name, pair, session)
            verdict, metrics = _score_result(result, criteria)
            raw_results[key] = {"verdict": verdict, **metrics}

    # ask Claude to interpret overall results
    user_msg = (
        f"EA: {ea_name}\n"
        f"Proposed change: {proposed_change or 'baseline validation'}\n\n"
        f"Backtest results across pairs × sessions:\n{json.dumps(raw_results, indent=2)}\n\n"
        f"Pass criteria: {json.dumps(criteria)}"
    )
    import sys as _sys, pathlib as _pl
    _ta = str(_pl.Path(__file__).resolve().parents[1])
    if _ta not in _sys.path: _sys.path.insert(0, _ta)
    from llm_fallback import chat_resilient
    # Sonnet (unchanged) + NVIDIA fallback if Claude is down
    raw = chat_resilient(
        client, system=INTERPRETATION_PROMPT, user=user_msg, max_tokens=1024,
        model="claude-sonnet-4-6", thinking=False, nvidia_tier="HEAVY",
        label="ea_validator")
    start = raw.find("{")
    end = raw.rfind("}") + 1
    interpretation = json.loads(raw[start:end]) if start >= 0 else {}

    output = {
        "ea": ea_name,
        "proposed_change": proposed_change,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "raw_results": raw_results,
        "compatible_pairs": interpretation.get("compatible_pairs", []),
        "incompatible_pairs": interpretation.get("incompatible_pairs", []),
        "best_session": interpretation.get("best_session", "unknown"),
        "overall_verdict": interpretation.get("overall_verdict", "UNKNOWN"),
        "recommendation": interpretation.get("recommendation", ""),
        "confidence": interpretation.get("confidence", "low"),
    }

    # save
    VALIDATOR_STATE.parent.mkdir(parents=True, exist_ok=True)
    VALIDATOR_STATE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    log.info("EAValidator result: %s — %s", output["overall_verdict"], output["recommendation"])

    # notify
    verdict = output["overall_verdict"]
    compat = ", ".join(output["compatible_pairs"]) or "none"
    incompat = ", ".join(output["incompatible_pairs"]) or "none"
    level = "INFO" if verdict == "PASS" else ("WARNING" if verdict == "CONDITIONAL_PASS" else "CRITICAL")
    _notify(
        f"*EAValidator [{ea_name}]*: {verdict}\n"
        f"Works on: {compat}\n"
        f"Fails on: {incompat}\n"
        f"Best session: {output['best_session']}\n"
        f"Recommendation: {output['recommendation']}",
        level=level,
    )
    return output


def run_quick_check(ea_name: str, symbol: str, client: anthropic.Anthropic | None = None) -> dict:
    """Quick single-pair validation."""
    cfg = _load_config()
    criteria = cfg.get("validator_pass_criteria", {})
    result = _run_backtest_for_pair(ea_name, symbol, "london")
    verdict, metrics = _score_result(result, criteria)
    log.info("Quick check %s/%s: %s — %s", ea_name, symbol, verdict, metrics)
    return {"ea": ea_name, "symbol": symbol, "verdict": verdict, **metrics}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--ea" not in sys.argv:
        print("Usage: python -m trading_agents.ea_agents.ea_validator --ea <name> [--change 'description'] [--mode full]")
        sys.exit(1)

    ea = sys.argv[sys.argv.index("--ea") + 1]
    change = ""
    if "--change" in sys.argv:
        change = sys.argv[sys.argv.index("--change") + 1]

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = run_full_validation(ea, proposed_change=change, client=client)
    print(json.dumps(result, indent=2))
