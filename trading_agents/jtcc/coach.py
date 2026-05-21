"""JTCC Coach — analyzes JTCC strategy performance every 6h, proposes ONE improvement.

Mirrors trading_agents/ea_agents/ea_coach.py pattern. Telegram dialogue with Junait
before applying changes. Saves state to logs/jtcc/_jtcc_coach.json.

Run:
  python -m trading_agents.jtcc.coach --once
  python -m trading_agents.jtcc.coach --loop
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent.parent.parent
PERF_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_performance.json"
TRADES_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_trades.jsonl"
COACH_STATE = BASE_DIR / "logs" / "jtcc" / "_jtcc_coach.json"
QUARANTINE_DIR = BASE_DIR / "trading_agents" / "jtcc" / "strategies" / "_quarantine"
STRATEGIES_DIR = BASE_DIR / "trading_agents" / "jtcc" / "strategies"

BD_TZ = ZoneInfo("Asia/Dhaka")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("jtcc.coach")

# Performance thresholds
MIN_TRADES_FOR_VERDICT = 15      # don't judge until 15 trades
DISABLE_WIN_RATE_PCT = 35        # < 35% WR over 15+ trades = disable proposal
LOSING_STREAK_LIMIT = 5          # 5 losses in a row = pause proposal
EXCELLENT_WIN_RATE_PCT = 65      # 65%+ WR = recommend wider deployment


def _read_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default or {}


def _save_state(state: dict) -> None:
    try:
        COACH_STATE.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now(tz=BD_TZ).isoformat()
        COACH_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Save coach state failed: %s", e)


def _trades_per_strategy() -> dict[str, list[dict]]:
    """Group closed trades by strategy."""
    if not TRADES_FILE.exists():
        return {}
    by_strat: dict[str, list[dict]] = {}
    try:
        for line in TRADES_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if entry.get("type") != "trade_close":
                    continue
                strat = entry.get("strategy", "unknown")
                by_strat.setdefault(strat, []).append(entry)
            except Exception:
                continue
    except Exception as e:
        log.error("Trade read failed: %s", e)
    return by_strat


def _analyze_strategy(name: str, trades: list[dict]) -> dict:
    if not trades:
        return {"strategy": name, "verdict": "no_data"}

    pnls = [t.get("pnl", 0) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    total = len(pnls)
    win_rate = round(wins / total * 100, 1) if total else 0
    total_pnl = round(sum(pnls), 2)

    # Trailing losing streak
    streak = 0
    for p in reversed(pnls):
        if p < 0:
            streak += 1
        else:
            break

    profit_factor = round(
        sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0) or 1e-9), 2
    )

    return {
        "strategy": name, "total_trades": total, "wins": wins, "losses": losses,
        "win_rate_pct": win_rate, "total_pnl": total_pnl, "profit_factor": profit_factor,
        "losing_streak": streak, "verdict": _verdict(total, win_rate, streak, profit_factor),
    }


def _verdict(total: int, win_rate: float, streak: int, pf: float) -> str:
    if total < MIN_TRADES_FOR_VERDICT:
        return "insufficient_data"
    if win_rate < DISABLE_WIN_RATE_PCT and pf < 1.0:
        return "propose_disable"
    if streak >= LOSING_STREAK_LIMIT:
        return "propose_pause"
    if win_rate >= EXCELLENT_WIN_RATE_PCT and pf >= 1.5:
        return "excellent"
    if 1.0 <= pf < 1.3:
        return "marginal"
    return "healthy"


def _build_proposal(analysis: list[dict]) -> dict | None:
    """Pick ONE highest-priority proposal."""
    disable_candidates = [a for a in analysis if a.get("verdict") == "propose_disable"]
    if disable_candidates:
        worst = min(disable_candidates, key=lambda x: x.get("win_rate_pct", 100))
        return {
            "type": "disable_strategy", "strategy": worst["strategy"],
            "reason": f"WR {worst['win_rate_pct']}% over {worst['total_trades']} trades, PF {worst['profit_factor']}",
            "action": f"Move {worst['strategy']}.yaml to _quarantine/",
            "expected_impact": "Stop bleeding from underperformer",
        }
    pause_candidates = [a for a in analysis if a.get("verdict") == "propose_pause"]
    if pause_candidates:
        worst = max(pause_candidates, key=lambda x: x.get("losing_streak", 0))
        return {
            "type": "pause_strategy", "strategy": worst["strategy"],
            "reason": f"Losing streak: {worst['losing_streak']} consecutive losses",
            "action": f"Temporarily increase confidence_required in {worst['strategy']}",
            "expected_impact": "Reduce trade frequency until conditions improve",
        }
    excellent = [a for a in analysis if a.get("verdict") == "excellent"]
    if excellent:
        best = max(excellent, key=lambda x: x.get("profit_factor", 0))
        return {
            "type": "expand_strategy", "strategy": best["strategy"],
            "reason": f"WR {best['win_rate_pct']}%, PF {best['profit_factor']} over {best['total_trades']} trades",
            "action": f"Consider adding more symbols to {best['strategy']}.yaml",
            "expected_impact": "Replicate winning edge across pairs",
        }
    return None


def run_cycle() -> dict:
    now = datetime.now(tz=BD_TZ)
    by_strat = _trades_per_strategy()
    analysis = [_analyze_strategy(n, trades) for n, trades in by_strat.items()]
    proposal = _build_proposal(analysis)

    state = {
        "last_run": now.isoformat(),
        "strategies_analyzed": len(analysis),
        "analysis": analysis,
        "proposal": proposal,
        "history": _read_json(COACH_STATE).get("history", [])[-20:],
    }
    if proposal:
        state["history"].append({"at": now.isoformat(), "proposal": proposal})
        _notify_proposal(proposal, analysis)
    else:
        log.info("Coach: no actionable proposals this cycle")

    _save_state(state)
    return state


def _notify_proposal(proposal: dict, analysis: list[dict]) -> None:
    try:
        from trading_agents.telegram_hq import send as tg_send
        msg = (
            f"🎓 JTCC COACH PROPOSAL\n\n"
            f"Type: {proposal['type']}\n"
            f"Strategy: {proposal['strategy']}\n"
            f"Reason: {proposal['reason']}\n"
            f"Action: {proposal['action']}\n"
            f"Impact: {proposal['expected_impact']}\n\n"
            f"Reply YES/NO to apply."
        )
        tg_send("ea_coach", msg, level="WARNING", title="JTCC Coach Proposal")
    except Exception as e:
        log.error("Coach Telegram send failed: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="JTCC Coach")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=6, help="Hours between cycles (default 6)")
    args = parser.parse_args()

    if args.once or not args.loop:
        result = run_cycle()
        print(json.dumps(result.get("proposal") or {"message": "No proposal"}, indent=2))
        return

    log.info("JTCC Coach loop started — every %dh", args.interval)
    while True:
        try:
            run_cycle()
        except Exception as e:
            log.error("Coach cycle error: %s", e)
        time.sleep(args.interval * 3600)


if __name__ == "__main__":
    main()
