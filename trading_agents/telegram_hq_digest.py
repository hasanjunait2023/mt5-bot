"""
Telegram HQ — daily digest + approval reminders.

Posts a once-a-day rollup (P&L, system status, pending approvals you still
owe, open issues, scout progress) to the Digest topic, and nags about EA
decisions left unanswered. Reads only existing state files — no new sources.

Usage:
  python -m trading_agents.telegram_hq_digest            # run loop
  python -m trading_agents.telegram_hq_digest --once     # one digest now
  python -m trading_agents.telegram_hq_digest --reminders # one reminder sweep
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from trading_agents import telegram_hq

log = logging.getLogger("HQDigest")

BASE_DIR     = Path(__file__).parent.parent
LIVE_STATE   = BASE_DIR / "mt5_bridge" / "_live_state.json"
SUPERVISOR   = BASE_DIR / "logs" / "supervisor_report.json"
COACH_STATE  = BASE_DIR / "logs" / "ea_agents" / "_coach_state.json"
SCOUT_STATE  = BASE_DIR / "trading_agents" / "strategy_scout" / "_scout_state.json"

REMINDER_AFTER_HOURS = 12   # nag once an approval is older than this
POLL_SEC = 300              # wake cadence; picks up config changes


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pending_approvals() -> list[tuple[str, dict]]:
    coach = _read(COACH_STATE)
    out = []
    for ea, d in coach.get("eas", {}).items():
        pq = d.get("pending_question")
        if pq:
            out.append((ea, pq))
    return out


def build_digest() -> str:
    live = _read(LIVE_STATE)
    acct = live.get("account", {})
    sup  = _read(SUPERVISOR)
    coach = _read(COACH_STATE)
    scout = _read(SCOUT_STATE)

    lines = [f"_{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_", ""]

    # Account / P&L
    if acct:
        lines += [
            "*Account*",
            f"• Equity: {acct.get('equity', 0):.2f}  |  Balance: {acct.get('balance', 0):.2f}",
            f"• Daily P&L: {acct.get('daily_pnl', 0):.2f}  "
            f"(DD {acct.get('daily_dd_pct', 0):.2f}% / total {acct.get('total_dd_pct', 0):.2f}%)",
            f"• Open positions: {len(live.get('positions', []))}",
            "",
        ]
    else:
        lines += ["*Account*", "• Live trader offline / no state.", ""]

    # System status
    status = sup.get("overall_status") or sup.get("status") or "unknown"
    issues = sup.get("issues") or sup.get("unresolved") or []
    lines += [
        "*System*",
        f"• Supervisor status: {status}",
        f"• Open issues: {len(issues)}",
        "",
    ]

    # EA lifecycle
    eas = coach.get("eas", {})
    if eas:
        stages = ", ".join(f"{ea}:{d.get('lifecycle_stage', '?')}" for ea, d in eas.items())
        lines += ["*EAs*", f"• {stages}", ""]

    # Pending approvals you owe
    pend = _pending_approvals()
    if pend:
        lines.append("*⏳ Awaiting your decision*")
        for ea, pq in pend:
            lines.append(f"• [{ea}] {pq.get('question', '')[:120]}")
        lines.append("Reply in the EA Coach · Approvals topic: YES / NO / TEST MORE")
        lines.append("")

    # Scout progress
    if scout.get("ideas"):
        stage_counts: dict[str, int] = {}
        for idea in scout["ideas"].values():
            stage_counts[idea.get("stage", "?")] = stage_counts.get(idea.get("stage", "?"), 0) + 1
        lines += ["*Strategy Scout*",
                  f"• Cycles: {scout.get('cycles', 0)}  |  "
                  + ", ".join(f"{k}:{v}" for k, v in stage_counts.items())]

    return "\n".join(lines)


def send_digest() -> None:
    cfg = telegram_hq.load_config()
    if not cfg.get("digest", {}).get("enabled", True):
        log.info("Digest disabled in config — skipping.")
        return
    telegram_hq.send("digest", build_digest(), level="INFO", title="Daily HQ Digest")
    log.info("Digest sent.")


def run_reminders() -> None:
    now = datetime.now(timezone.utc)
    for ea, pq in _pending_approvals():
        try:
            asked = datetime.fromisoformat(pq.get("asked_at", ""))
        except Exception:
            continue
        age_h = (now - asked).total_seconds() / 3600
        if age_h >= REMINDER_AFTER_HOURS:
            telegram_hq.send(
                "ea_coach",
                f"⏰ *Reminder* — [{ea}] has been waiting {age_h:.0f}h for your decision:\n"
                f"{pq.get('question', '')}\n\nReply: YES / NO / TEST MORE",
                level="WARNING",
                title="Pending Approval Reminder",
            )
            log.info("Reminder sent for %s (%.0fh)", ea, age_h)


def _next_digest_time(hour_utc: int) -> datetime:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_loop() -> None:
    cfg = telegram_hq.load_config()
    hour = cfg.get("digest", {}).get("hour_utc", 6)
    rem_h = cfg.get("digest", {}).get("reminder_hours", 6)
    next_digest = _next_digest_time(hour)
    next_rem = datetime.now(timezone.utc) + timedelta(hours=rem_h)
    log.info("HQ digest loop started — next digest %s UTC, reminders every %dh",
             next_digest, rem_h)

    while True:
        now = datetime.now(timezone.utc)
        if now >= next_digest:
            try:
                send_digest()
            except Exception as e:
                log.error("digest error: %s", e)
            cfg = telegram_hq.load_config()
            hour = cfg.get("digest", {}).get("hour_utc", 6)
            next_digest = _next_digest_time(hour)
        if now >= next_rem:
            try:
                run_reminders()
            except Exception as e:
                log.error("reminder error: %s", e)
            cfg = telegram_hq.load_config()
            rem_h = cfg.get("digest", {}).get("reminder_hours", 6)
            next_rem = now + timedelta(hours=rem_h)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if "--once" in sys.argv:
        send_digest()
    elif "--reminders" in sys.argv:
        run_reminders()
    else:
        run_loop()
