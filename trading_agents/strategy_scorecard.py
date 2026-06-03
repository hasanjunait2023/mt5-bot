"""
strategy_scorecard.py — Single source of truth for "is this strategy profitable,
who needs improvement, where & how". Consumed by the CEO agent, the dashboard
page, the EOD report, and the Phase 5 improvement loop. ONE verdict rule lives
here so dashboard + Telegram + CEO always agree.

Per (sub)strategy it fuses:
  - live realized stats        (trade_journal.get_stats, windowed)
  - 7d-vs-30d trend
  - backtest PF                (configs/backtest_verdicts.json, optional)
  - top failure mode + fix     (loss_analyzer, sample-gated; LLM-sharpened if enabled)
  - top strength               (win_analyzer)

Verdict rule (the only definition):
  n < MIN_SAMPLE              -> INSUFFICIENT  (grey; never call a winner on thin data)
  PF >= 1.3 AND net_pnl > 0   -> PROFITABLE    (green)
  else                        -> LOSING        (red; if n >= IMPROVE_SAMPLE -> in_improvement)

Run:
  python -m trading_agents.strategy_scorecard            # print once
  python -m trading_agents.strategy_scorecard --loop     # write json every N min
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.parent
OUT_PATH = BASE_DIR / "logs" / "_strategy_scorecard.json"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
_BACKTEST_VERDICTS = BASE_DIR / "configs" / "backtest_verdicts.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scorecard")

MIN_SAMPLE = 20          # below this -> INSUFFICIENT
IMPROVE_SAMPLE = 30      # LOSING at/above this -> enqueue for improvement
PROFIT_PF = 1.3          # PF bar for PROFITABLE
_LLM_FIX = os.getenv("SCORECARD_LLM_FIX", "0") in ("1", "true", "yes")


def _load_backtest_verdicts() -> dict[str, float]:
    """Optional map {strategy_name: backtest_pf} from prior cost-applied backtests."""
    if _BACKTEST_VERDICTS.exists():
        try:
            return json.loads(_BACKTEST_VERDICTS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _verdict(agg: dict) -> str:
    n = agg.get("trades", 0)
    if n < MIN_SAMPLE:
        return "INSUFFICIENT"
    pf = agg.get("profit_factor")
    net = agg.get("net_pnl", 0)
    if pf is not None and pf >= PROFIT_PF and net > 0:
        return "PROFITABLE"
    return "LOSING"


def _trend(net_7d: float | None, net_30d: float | None) -> str:
    if net_7d is None or net_30d is None:
        return "flat"
    # 7d run-rate vs 30d run-rate (per-day)
    r7, r30 = net_7d / 7.0, net_30d / 30.0
    if r7 > r30 * 1.15:
        return "up"
    if r7 < r30 * 0.85:
        return "down"
    return "flat"


def _llm_fix(strat: str, loss_agg: dict, backtest_pf: float | None) -> dict | None:
    """Sample-gated, backtest-anchored LLM fix. Only invoked for LOSING strategies
    with a real sample; returns {headline, details[]} or None on any failure."""
    try:
        import anthropic
        from trading_agents.llm_fallback import chat_resilient
    except Exception:
        return None
    prompt = (
        f"You are a trading-strategy coach. Strategy '{strat}' is losing on LIVE trades.\n"
        f"Loss diagnosis: {json.dumps(loss_agg)}\n"
        f"Its prior backtest profit factor was {backtest_pf}.\n"
        "Give ONE concrete fix as a JSON object: {\"headline\": \"<=90 chars, specific, "
        "e.g. disable a symbol / restrict a session / raise confluence>\", \"details\": "
        "[\"step 1\", \"step 2\"]}. Anchor to the backtest edge; do NOT invent a new edge "
        "from noise. Reply with ONLY the JSON."
    )
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or "x")
        resp = chat_resilient(
            client, system="You are a conservative trading-strategy coach.",
            user=prompt, max_tokens=300, thinking=False,
            nvidia_tier="HEAVY", label="scorecard_fix")
        txt = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
        start, end = txt.find("{"), txt.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(txt[start:end + 1])
            return {"headline": str(obj.get("headline", ""))[:90],
                    "details": [str(x) for x in (obj.get("details") or [])][:5]}
    except Exception as e:
        log.warning("LLM fix failed for %s: %s", strat, e)
    return None


def build_scorecard(window_days: int = 30, demo: bool | None = None) -> dict:
    from trading_agents import trade_journal
    from trading_agents import loss_analyzer, win_analyzer

    stats_30 = trade_journal.get_stats(window_days=window_days, demo=demo)
    stats_7 = trade_journal.get_stats(window_days=7, demo=demo)
    backtest = _load_backtest_verdicts()
    try:
        losses = loss_analyzer.analyze().get("by_strategy", {})
    except Exception:
        losses = {}
    try:
        wins = win_analyzer.analyze().get("by_strategy", {})
    except Exception:
        wins = {}

    by_strat_30 = stats_30.get("by_strategy", {})
    by_strat_7 = stats_7.get("by_strategy", {})

    cards: list[dict] = []
    improvement_queue: list[str] = []
    for strat, agg in by_strat_30.items():
        verdict = _verdict(agg)
        loss_agg = losses.get(strat, {})
        win_agg = wins.get(strat, {})
        backtest_pf = backtest.get(strat)
        net_7 = by_strat_7.get(strat, {}).get("net_pnl")

        # fix: rule-based by default; LLM-sharpened only when enabled + real sample
        fix_headline = loss_agg.get("suggestion", "")
        fix_details: list[str] = []
        in_improvement = False
        if verdict == "LOSING" and agg.get("trades", 0) >= IMPROVE_SAMPLE:
            in_improvement = True
            improvement_queue.append(strat)
            if _LLM_FIX:
                llm = _llm_fix(strat, loss_agg, backtest_pf)
                if llm:
                    fix_headline = llm["headline"] or fix_headline
                    fix_details = llm["details"]

        cards.append({
            "strategy":        strat,
            "verdict":         verdict,
            "in_improvement":  in_improvement,
            "live_pf":         agg.get("profit_factor"),
            "backtest_pf":     backtest_pf,
            "win_rate":        agg.get("win_rate_pct"),
            "expectancy":      agg.get("expectancy"),
            "net_pnl":         agg.get("net_pnl"),
            "max_drawdown":    agg.get("max_drawdown"),
            "avg_rr":          agg.get("avg_rr"),
            "n":               agg.get("trades", 0),
            "sample_ok":       agg.get("sample_ok", False),
            "trend":           _trend(net_7, agg.get("net_pnl")),
            "top_failure":     loss_agg.get("top_mistake"),
            "fix_headline":    fix_headline[:90] if fix_headline else "",
            "fix_details":     fix_details,
            "top_strength":    win_agg.get("top_strength"),
            "strength_note":   win_agg.get("strength_note", ""),
        })

    # rank: profitable (by net desc) -> losing (by net asc) -> insufficient
    order = {"PROFITABLE": 0, "LOSING": 1, "INSUFFICIENT": 2}
    cards.sort(key=lambda c: (order.get(c["verdict"], 3),
                              -(c["net_pnl"] or 0) if c["verdict"] == "PROFITABLE" else (c["net_pnl"] or 0)))

    total = stats_30.get("total", {})
    counts = {"profitable": 0, "losing": 0, "insufficient": 0}
    for c in cards:
        counts[c["verdict"].lower()] = counts.get(c["verdict"].lower(), 0) + 1

    return {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "window_days":    window_days,
        "demo_filter":    demo,
        "portfolio": {
            "net_pnl":      total.get("net_pnl", 0),
            "profit_factor": total.get("profit_factor"),
            "trades":       total.get("trades", 0),
            "equity_curve": stats_30.get("equity_curve", []),
        },
        "counts":             counts,
        "strategies":         cards,
        "improvement_queue":  improvement_queue,
    }


def write_scorecard(**kw) -> dict:
    sc = build_scorecard(**kw)
    OUT_PATH.write_text(json.dumps(sc, indent=2), encoding="utf-8")
    return sc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=15, help="minutes between runs")
    ap.add_argument("--demo", choices=["true", "false"], default=None)
    args = ap.parse_args()
    demo = None if args.demo is None else (args.demo == "true")

    if args.loop:
        log.info("scorecard loop started (every %dm)", args.interval)
        while True:
            try:
                sc = write_scorecard(demo=demo)
                log.info("scorecard: %s strategies, queue=%s", len(sc["strategies"]), sc["improvement_queue"])
            except Exception as e:
                log.warning("scorecard error: %s", e)
            time.sleep(args.interval * 60)
    else:
        print(json.dumps(build_scorecard(demo=demo), indent=2))
