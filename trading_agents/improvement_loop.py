"""
improvement_loop.py — Phase 5 north star: improve losing strategies until profitable.

Owner's call: losing strategies are NOT killed/demoted. They are iterated toward
profitability by learning from (a) their mistakes (loss_analyzer), (b) their correct
decisions (win_analyzer), and (c) research, then proposing a bounded change that is
backtested and applied behind a HUMAN GATE. Nothing is auto-applied; nothing is deleted.

Each iteration is journaled to logs/_improvement/<strategy>.jsonl so the loop learns
across attempts and the owner/CEO can see the improvement history.

Pipeline per strategy in the scorecard's improvement_queue:
  1. diagnose   — loss_patterns + win_patterns + original backtest verdict
  2. research   — relevant refinement ideas (LLM; optionally strategy_researcher)
  3. propose    — ONE concrete bounded change (param / symbol filter / session / confluence)
  4. (backtest) — integration point: run the strategy's REAL-COST backtest on the change
  5. GATE       — Telegram proposal for human approval; apply stays manual+promotion_gate
  6. re-measure — next scorecard cycle tracks live PF; loop continues until PROFITABLE

Run:
    python -m trading_agents.improvement_loop            # one pass over the queue
    python -m trading_agents.improvement_loop --loop --interval 360   # every 6h
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
SCORECARD = BASE_DIR / "logs" / "_strategy_scorecard.json"
IMP_DIR = BASE_DIR / "logs" / "_improvement"
IMP_DIR.mkdir(parents=True, exist_ok=True)
STATE = IMP_DIR / "_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("improvement_loop")


def _load_scorecard() -> dict | None:
    try:
        if SCORECARD.exists():
            return json.loads(SCORECARD.read_text(encoding="utf-8"))
        from trading_agents.strategy_scorecard import build_scorecard
        return build_scorecard()
    except Exception as e:
        log.warning("scorecard load failed: %s", e)
        return None


def _history(strategy: str) -> list[dict]:
    f = IMP_DIR / f"{_safe(strategy)}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:48] or "strat"


def _journal_iteration(strategy: str, rec: dict) -> None:
    f = IMP_DIR / f"{_safe(strategy)}.jsonl"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _research(strategy: str, card: dict) -> str:
    """Best-effort research note for this strategy's failure mode."""
    try:
        import os
        import anthropic
        from trading_agents.llm_fallback import chat_resilient
    except Exception:
        return ""
    prompt = (
        f"Strategy '{strategy}' is losing live (PF {card.get('live_pf')}, n={card.get('n')}). "
        f"Top failure: {card.get('top_failure')}. What works: {card.get('top_strength')}. "
        f"Original backtest PF: {card.get('backtest_pf')}.\n"
        "In 2-3 sentences, suggest the single most promising, well-established refinement "
        "(session filter, SL method, confluence weighting, symbol selection) to move it toward "
        "profitability WITHOUT inventing a new edge. Be specific and conservative."
    )
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or "x")
        r = chat_resilient(
            client,
            system="You are a conservative, well-established trading-strategy coach.",
            user=prompt, max_tokens=250, thinking=False,
            nvidia_tier="HEAVY", label="improvement_research")
        return (r or "").strip()
    except Exception as e:
        log.warning("research failed for %s: %s", strategy, e)
        return ""


def _propose(strategy: str, card: dict, research: str, iteration: int) -> dict:
    """One bounded, backtestable change. Reinforces what wins, fixes what fails."""
    return {
        "iteration":   iteration,
        "ts":          datetime.now(timezone.utc).isoformat(),
        "strategy":    strategy,
        "live_pf":     card.get("live_pf"),
        "n":           card.get("n"),
        "diagnose":    {"top_failure": card.get("top_failure"),
                        "fix_headline": card.get("fix_headline"),
                        "top_strength": card.get("top_strength")},
        "research":    research,
        "change":      card.get("fix_headline") or "review failure mode; restrict to winning conditions",
        "change_details": card.get("fix_details", []),
        "backtest":    None,    # integration point — fill when the harness runs
        "status":      "PENDING_APPROVAL",   # human-gated; never auto-applied
    }


def _notify(strategy: str, prop: dict) -> None:
    msg = (f"⚙️ Improvement proposal — {strategy} (iteration {prop['iteration']})\n"
           f"Live PF {prop['live_pf']} · n={prop['n']} · failure: {prop['diagnose']['top_failure']}\n"
           f"Strength to keep: {prop['diagnose']['top_strength']}\n"
           f"Proposed change: {prop['change']}\n"
           + (f"Research: {prop['research']}\n" if prop["research"] else "")
           + "Reply APPROVE <strategy> to backtest+apply (human-gated), or SKIP.")
    try:
        from trading_agents import telegram_hq
        telegram_hq.send("digest", msg, title="Strategy Improvement")
    except Exception as e:
        log.warning("notify failed: %s\n%s", e, msg)


def run_once() -> dict:
    sc = _load_scorecard()
    if not sc:
        return {"error": "no scorecard"}
    queue = sc.get("improvement_queue", [])
    cards = {c["strategy"]: c for c in sc.get("strategies", [])}
    processed = []
    for strat in queue:
        card = cards.get(strat, {})
        hist = _history(strat)
        # don't re-propose if an unresolved proposal is already pending
        if hist and hist[-1].get("status") == "PENDING_APPROVAL":
            log.info("%s already has a pending proposal — skipping", strat)
            continue
        iteration = len([h for h in hist if h.get("status") != "boot"]) + 1
        research = _research(strat, card)
        prop = _propose(strat, card, research, iteration)
        _journal_iteration(strat, prop)
        _notify(strat, prop)
        processed.append(strat)
        log.info("proposed improvement for %s (iteration %d)", strat, iteration)

    STATE.write_text(json.dumps({"last_run": datetime.now(timezone.utc).isoformat(),
                                 "queue": queue, "processed": processed}), encoding="utf-8")
    return {"queue": queue, "processed": processed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=360, help="minutes between passes")
    args = ap.parse_args()
    if args.loop:
        STATE.write_text(json.dumps({"last_run": None, "booted": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        log.info("improvement loop started (every %dm)", args.interval)
        while True:
            try:
                r = run_once()
                log.info("improvement pass: %s", r)
            except Exception as e:
                log.warning("improvement loop error: %s", e)
            time.sleep(args.interval * 60)
    else:
        print(json.dumps(run_once(), indent=2))
