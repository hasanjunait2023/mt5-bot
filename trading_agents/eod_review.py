"""EOD (End-of-Day) Strategy Review.

After NY session close, build the strategy scorecard (verdict + per-strategy P&L +
failure mode + improvement fix) and post a plain-language brief to Telegram so the
owner + CEO see who's profitable, who's losing, and what to fix — without reading
the dashboard. Losing strategies (n >= IMPROVE_SAMPLE) are flagged "in improvement",
never killed.

Usage:
    python -m trading_agents.eod_review          # run once
    python -m trading_agents.eod_review --loop    # daily at 15:00 UTC (NY close)
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "logs" / "eod_review"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE = LOG_DIR / "_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eod_review")

_VERDICT_ICON = {"PROFITABLE": "✅", "LOSING": "🔴", "INSUFFICIENT": "◌"}
_TREND_ICON = {"up": "▲", "down": "▼", "flat": "▬"}


def _fmt_money(x) -> str:
    if x is None:
        return "—"
    return f"+${x:,.0f}" if x >= 0 else f"-${abs(x):,.0f}"


def build_message(sc: dict) -> str:
    p = sc["portfolio"]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"📊 EOD Strategy Review — {date}",
             f"Portfolio ({sc['window_days']}d): {_fmt_money(p['net_pnl'])} · "
             f"PF {p.get('profit_factor') if p.get('profit_factor') is not None else '—'} · {p['trades']} trades",
             ""]

    buckets: dict[str, list] = {"PROFITABLE": [], "LOSING": [], "INSUFFICIENT": []}
    for c in sc["strategies"]:
        buckets[c["verdict"]].append(c)

    if buckets["PROFITABLE"]:
        lines.append(f"✅ PROFITABLE ({len(buckets['PROFITABLE'])})")
        for c in buckets["PROFITABLE"]:
            lines.append(f" • {c['strategy']}  PF {c['live_pf']}  {_fmt_money(c['net_pnl'])}  "
                         f"n={c['n']} {_TREND_ICON.get(c['trend'], '')}")
        lines.append("")

    if buckets["LOSING"]:
        lines.append(f"🔴 LOSING / IN IMPROVEMENT ({len(buckets['LOSING'])})")
        for c in buckets["LOSING"]:
            tag = " [improving]" if c["in_improvement"] else ""
            lines.append(f" • {c['strategy']}  PF {c['live_pf']}  {_fmt_money(c['net_pnl'])}  "
                         f"n={c['n']} {_TREND_ICON.get(c['trend'], '')}{tag}")
            if c.get("fix_headline"):
                lines.append(f"     fix: {c['fix_headline']}")
        lines.append("")

    if buckets["INSUFFICIENT"]:
        names = ", ".join(f"{c['strategy']}({c['n']})" for c in buckets["INSUFFICIENT"])
        lines.append(f"◌ INSUFFICIENT sample: {names}")

    if sc["improvement_queue"]:
        lines.append("")
        lines.append(f"⚙️ In improvement loop: {', '.join(sc['improvement_queue'])}")

    return "\n".join(lines)


def run_review() -> dict:
    from trading_agents import strategy_scorecard
    sc = strategy_scorecard.build_scorecard()
    msg = build_message(sc)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (LOG_DIR / f"{today}.json").write_text(json.dumps(sc, indent=2), encoding="utf-8")
    STATE.write_text(json.dumps({"last_run": datetime.now(timezone.utc).isoformat(),
                                 "strategies": len(sc["strategies"]),
                                 "improvement_queue": sc["improvement_queue"]}), encoding="utf-8")

    try:
        from trading_agents import telegram_hq
        telegram_hq.send("digest", msg, title="EOD Strategy Review")
        log.info("EOD review sent to Telegram")
    except Exception as e:
        log.warning("telegram send failed: %s\n%s", e, msg)

    return sc


def _wait_until_ny_close():
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if now.hour >= 15:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        log.info("next EOD review in %.0f min", wait / 60)
        time.sleep(min(wait, 3600))
        if datetime.now(timezone.utc).hour == 15:
            return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    if args.loop:
        # heartbeat immediately so the supervisor sees a fresh state file at boot
        STATE.write_text(json.dumps({"last_run": None, "booted": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        log.info("EOD review loop started")
        while True:
            _wait_until_ny_close()
            try:
                run_review()
            except Exception as e:
                log.warning("EOD review error: %s", e)
    else:
        sc = run_review()
        print(build_message(sc))
