"""
GrowthPipeline — the autonomous strategy-growth loop.

Each cycle: Scout collects ideas → StrategyResearcher backtests them → winners are
pitched to the CEO (Maic), who auto-delegates to the dev team (build EA) and EA team
(validate). Junait is notified at every stage. The loop is fully autonomous up to the
demo→live decision, which stays gated behind the existing EA Coach YES/NO question.

Usage:
  python -m trading_agents.strategy_scout.growth_pipeline --once
  python -m trading_agents.strategy_scout.growth_pipeline --interval 8
"""

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("GrowthPipeline")

BASE_DIR    = Path(__file__).parent.parent.parent
CONFIG_FILE = Path(__file__).parent / "scout_config.json"
STATE_FILE  = Path(__file__).parent / "_scout_state.json"

STAGES = ["DISCOVERED", "BACKTESTED", "PITCHED", "BUILDING", "VALIDATING", "LIVE", "REJECTED", "ARCHIVED"]


def _cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents.dev_agents.notifier import notify
        notify(msg, level=level, category="strategy_scout")
    except Exception as e:
        log.warning("Notify failed: %s", e)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ideas": {}, "cycles": 0, "scorecard": {}}


def _save_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _idea_id(idea: dict) -> str:
    basis = json.dumps(idea.get("parameters", {}), sort_keys=True) + idea.get("description", "")
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


# ── Step 2: backtest via existing StrategyResearcher ──────────────────────────

def _backtest(idea: dict, symbols: list[str], months: int) -> dict | None:
    try:
        sys.path.insert(0, str(BASE_DIR / "trading_agents"))
        from strategy_researcher import StrategyResearcher  # type: ignore
        researcher = StrategyResearcher()
    except Exception as e:
        log.error("Cannot import StrategyResearcher: %s", e)
        return None

    best = None
    for sym in symbols:
        try:
            res = researcher.test_strategy(sym, idea["parameters"], months=months, use_walk_forward=True)
        except TypeError:
            res = researcher.test_strategy(sym, idea["parameters"], months)
        except Exception as e:
            log.warning("Backtest failed for %s: %s", sym, e)
            continue
        if not res:
            continue
        metrics = res.get("metrics", {})
        pf = metrics.get("profit_factor", 0) or 0
        wf = res.get("walk_forward_details", {})
        consistency = wf.get("consistency", res.get("aggregate_metrics", {}).get("consistency_score", 0)) or 0
        scored = {
            "symbol": sym,
            "profit_factor": round(pf, 2),
            "win_rate": round(metrics.get("win_rate_pct", 0), 1),
            "max_dd": round(metrics.get("max_drawdown_pct", 0), 1),
            "consistency": round(consistency, 2),
            "net_pnl": round(metrics.get("net_pnl", 0), 2),
        }
        if best is None or scored["profit_factor"] > best["profit_factor"]:
            best = scored
    return best


# ── Step 4: pitch winners to the CEO ──────────────────────────────────────────

def _pitch_to_ceo(idea: dict, score: dict) -> str:
    try:
        sys.path.insert(0, str(BASE_DIR / "trading_agents"))
        from maic_ceo_agent import chat  # type: ignore
    except Exception as e:
        log.error("Cannot import Maic chat(): %s", e)
        return f"Maic unavailable: {e}"

    pitch = (
        f"Scout has a validated new strategy to grow the account.\n\n"
        f"Strategy: {idea.get('description')}\n"
        f"Type: {idea.get('type')}\n"
        f"Source: {idea.get('source')}\n"
        f"Best backtest: {score['symbol']} — PF {score['profit_factor']}, "
        f"WR {score['win_rate']}%, MaxDD {score['max_dd']}%, "
        f"consistency {score['consistency']}\n"
        f"Target symbols: {', '.join(idea.get('symbols', []))}\n"
        f"Session: {idea.get('session_preference')}\n"
        f"Parameters: {json.dumps(idea.get('parameters'))}\n\n"
        f"Please have the development team build this EA, then have the EA team "
        f"validate it on demo. Proceed autonomously through dev and demo validation; "
        f"the demo→live decision stays with Junait via the EA Coach."
    )
    try:
        return chat("strategy_scout", pitch)
    except Exception as e:
        log.error("Maic pitch failed: %s", e)
        return f"Pitch failed: {e}"


# ── JTCC integration: write winning idea as a YAML strategy file ──────────────

def _write_jtcc_yaml_stub(idea: dict, score: dict) -> Path | None:
    """Auto-generate a JTCC YAML from a Scout winner. JTCC loader hot-reloads it.

    Conservative defaults: high confidence required, single symbol from backtest,
    primary session only. Junait can edit later in JTCC strategies/ folder.
    """
    import re
    jtcc_dir = BASE_DIR / "trading_agents" / "jtcc" / "strategies"
    if not jtcc_dir.exists():
        return None  # JTCC not installed

    raw_name = idea.get("description", "scout_idea")[:50]
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).lower().strip("_")[:40]
    next_n = len(list(jtcc_dir.glob("s*.yaml"))) + 1
    filename = f"s{next_n:02d}_scout_{safe_name}.yaml"
    path = jtcc_dir / filename
    if path.exists():
        return path  # already exists

    symbol = score.get("symbol", "XAUUSD")
    direction_hint = (idea.get("bias") or "").upper()  # "BULLISH"/"BEARISH" if known

    # Conservative skeleton — Junait/Coach can tune. Defaults: SMC confluence + session
    # gate + news guard + min RR 2.0. Confidence required = 7 (strict for new ideas).
    yaml_doc = f"""name: "Scout {raw_name[:30]}"
version: 1.0
description: "Auto-generated by Strategy Scout. PF {score.get('profit_factor', '?')}, WR {score.get('win_rate', '?')}%. Source: {idea.get('source', '?')}"
symbols: [{symbol}]
timeframe: M15

entry_rules:
  buy:
    - "market.trend == BULLISH"
    - "session.primary is true"
    - "news.blocked is false"
    - "smc.sweep_detected is true"
    - "momentum.adx_trending is true"
    - "risk.can_trade is true"
  sell:
    - "market.trend == BEARISH"
    - "session.primary is true"
    - "news.blocked is false"
    - "smc.sweep_detected is true"
    - "momentum.adx_trending is true"
    - "risk.can_trade is true"

exit_rules:
  sl_method: "atr"
  tp_method: "rr"
  sl_buffer_pips: 5
  min_rr: 2.0

risk:
  max_trades_per_day: 1
  confidence_required: 7
"""
    try:
        path.write_text(yaml_doc, encoding="utf-8")
        log.info("Scout → JTCC: wrote %s", filename)
        return path
    except Exception as e:
        log.error("Failed to write JTCC YAML %s: %s", filename, e)
        return None


# ── Stage observation (read EA team state, don't re-drive) ─────────────────────

def _observe_downstream(state: dict) -> None:
    """Advance PITCHED ideas by reading EA Coach/Guardian state written by the EA team."""
    coach_state_file = BASE_DIR / "logs" / "ea_agents" / "_coach_state.json"
    if not coach_state_file.exists():
        return
    try:
        coach = json.loads(coach_state_file.read_text(encoding="utf-8"))
    except Exception:
        return
    ea_stages = {ea: d.get("lifecycle_stage") for ea, d in coach.get("eas", {}).items()}
    for idea_id, rec in state["ideas"].items():
        if rec["stage"] in ("PITCHED", "BUILDING", "VALIDATING"):
            desc = rec.get("description", "").lower()
            for ea, stage in ea_stages.items():
                if ea.lower() in desc or desc[:8] in ea.lower():
                    if stage == "live":
                        rec["stage"] = "LIVE"
                    elif stage in ("graduating", "ready_to_graduate"):
                        rec["stage"] = "VALIDATING"
                    elif stage == "demo":
                        rec["stage"] = "BUILDING"


# ── One full cycle ────────────────────────────────────────────────────────────

def run_once() -> dict:
    cfg = _cfg()
    state = _load_state()
    state["cycles"] = state.get("cycles", 0) + 1
    cycle_n = state["cycles"]
    log.info("=== GrowthPipeline cycle #%d ===", cycle_n)

    th = cfg.get("thresholds", {})
    pf_th = th.get("pf_threshold", 1.4)
    cons_th = th.get("consistency_threshold", 0.5)
    symbols = cfg.get("target_symbols", ["EURUSD"])
    months = cfg.get("backtest_months", 3)
    max_pitches = cfg.get("max_pitches_per_cycle", 2)
    stall_cycles = cfg.get("stall_cycles", 6)

    # 1. COLLECT
    try:
        from trading_agents.strategy_scout.strategy_scout import collect_ideas
        ideas = collect_ideas()
    except Exception as e:
        log.error("Collection failed: %s", e)
        _notify(f"*Scout CRITICAL*: collection crashed — {e}", level="CRITICAL")
        return {"error": str(e)}

    collected = len(ideas)
    backtested = 0
    passed = 0
    pitched = 0

    for idea in ideas:
        iid = _idea_id(idea)
        if iid in state["ideas"] and state["ideas"][iid]["stage"] not in ("REJECTED",):
            continue  # already in pipeline
        rec = {
            "id": iid,
            "description": idea.get("description", ""),
            "source": idea.get("source", ""),
            "stage": "DISCOVERED",
            "first_seen_cycle": cycle_n,
            "last_update": datetime.now(timezone.utc).isoformat(),
        }
        state["ideas"][iid] = rec

        # 2. BACKTEST
        score = _backtest(idea, idea.get("symbols", symbols), months)
        backtested += 1
        if not score:
            rec["stage"] = "REJECTED"
            rec["reason"] = "backtest produced no result"
            continue
        rec["stage"] = "BACKTESTED"
        rec["score"] = score

        # 3. RANK
        if score["profit_factor"] < pf_th or score["consistency"] < cons_th:
            rec["stage"] = "REJECTED"
            rec["reason"] = f"below thresholds (PF {score['profit_factor']}, cons {score['consistency']})"
            continue
        passed += 1

        # 4. PITCH (capped per cycle)
        if pitched < max_pitches:
            maic_response = _pitch_to_ceo(idea, score)
            rec["stage"] = "PITCHED"
            rec["pitched_at"] = datetime.now(timezone.utc).isoformat()
            rec["maic_response"] = maic_response[:500]
            pitched += 1

            # JTCC integration: auto-write YAML stub so JTCC can vote on it immediately
            # (in parallel with EA build pipeline). YAML goes into hot-reload folder.
            try:
                yaml_path = _write_jtcc_yaml_stub(idea, score)
                rec["jtcc_yaml"] = str(yaml_path) if yaml_path else None
            except Exception as e:
                log.warning("JTCC YAML write failed for %s: %s", iid, e)

            _notify(
                f"*Scout → CEO*: pitched new strategy\n"
                f"_{idea.get('description')}_\n"
                f"{score['symbol']}: PF {score['profit_factor']}, WR {score['win_rate']}%, "
                f"DD {score['max_dd']}%, consistency {score['consistency']}\n"
                f"Source: {idea.get('source')}\n"
                f"{'→ JTCC YAML auto-loaded' if rec.get('jtcc_yaml') else ''}",
                level="INFO",
            )

    # 5. OBSERVE downstream progress
    _observe_downstream(state)

    # 6. STALL detection
    stalled = []
    for iid, rec in state["ideas"].items():
        if rec["stage"] in ("PITCHED", "BUILDING", "VALIDATING"):
            age = cycle_n - rec.get("first_seen_cycle", cycle_n)
            if age >= stall_cycles:
                stalled.append(rec.get("description", iid))
    if stalled:
        _notify(f"*Scout WARNING*: {len(stalled)} idea(s) stalled >{stall_cycles} cycles:\n" +
                "\n".join(f"- {s}" for s in stalled[:5]), level="WARNING")

    # 7. SCORECARD + funnel notify
    live_count = sum(1 for r in state["ideas"].values() if r["stage"] == "LIVE")
    state["scorecard"] = {
        "cycle": cycle_n,
        "collected": collected, "backtested": backtested,
        "passed": passed, "pitched": pitched,
        "total_in_pipeline": len(state["ideas"]),
        "live": live_count,
    }
    _save_state(state)

    _notify(
        f"*Scout cycle #{cycle_n}*: {collected} collected → {backtested} backtested → "
        f"{passed} passed → {pitched} pitched | {live_count} live total",
        level="INFO",
    )
    log.info("Cycle #%d done: %d/%d/%d/%d", cycle_n, collected, backtested, passed, pitched)
    return state["scorecard"]


def run_loop(interval_hours: float | None = None) -> None:
    cfg = _cfg()
    interval = interval_hours or cfg.get("cycle_hours", 8)
    log.info("GrowthPipeline started — cycle every %.1fh", interval)
    while True:
        try:
            run_once()
        except Exception as e:
            log.error("Cycle crashed: %s", e)
            _notify(f"*Scout CRITICAL*: pipeline cycle crashed — {e}", level="CRITICAL")
        time.sleep(interval * 3600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
    interval = None
    if "--interval" in sys.argv:
        interval = float(sys.argv[sys.argv.index("--interval") + 1])
    if "--once" in sys.argv:
        print(json.dumps(run_once(), indent=2, default=str))
    else:
        run_loop(interval)
