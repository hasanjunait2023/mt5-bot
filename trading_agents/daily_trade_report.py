"""End-of-day trade report — daily Telegram digest at 23:00 BD (17:00 UTC).

For the current Bangladesh trading day (UTC+6) it answers, from the cross-agent
trade_journal: which agent took which trade on which strategy, what won, what
lost, WHY each loss happened, and the day's overall result.

Usage:
  python -m trading_agents.daily_trade_report --once    # build + send now
  python -m trading_agents.daily_trade_report --loop     # daily at 17:00 UTC
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("daily_trade_report")

BD = timedelta(hours=6)            # Bangladesh = UTC+6
SEND_HOUR_UTC = 17                 # 17:00 UTC == 23:00 BD
STATE = Path(__file__).resolve().parent.parent / "logs" / "daily_trade_report" / "_state.json"

_LOSS_REASON = {
    "SL_HIT": "stop loss hit",
    "TP_HIT": "take profit (win)",
    "MANUAL": "closed manually",
    "CLOSED": "closed (other)",
}


# ── helpers (pure) ────────────────────────────────────────────────────────────

def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _bd_date(rec: dict, now_utc: datetime):
    """BD calendar date this trade belongs to — by close time if closed, else open."""
    t = _parse(rec.get("close_time")) or _parse(rec.get("open_time"))
    if t is None:
        return None
    return (t.astimezone(timezone.utc) + BD).date()


def todays_trades(records: list[dict], now_utc: datetime,
                  include_demo: bool = False) -> list[dict]:
    today = (now_utc + BD).date()
    out = []
    for r in records:
        if _bd_date(r, now_utc) != today:
            continue
        if not include_demo and r.get("demo") is True:
            continue
        out.append(r)
    return out


def _agent_of(r: dict) -> str:
    return r.get("agent") or r.get("source") or "unknown"


def _strat_of(r: dict) -> str:
    strats = r.get("strategies") or []
    if strats:
        return ", ".join(str(s) for s in strats)
    return r.get("source") or "—"


def _money(x) -> str:
    try:
        return f"{'+' if x >= 0 else ''}${x:,.2f}"
    except Exception:
        return "$0.00"


def build_report(records: list[dict], now_utc: datetime,
                 include_demo: bool = False) -> str:
    today = todays_trades(records, now_utc, include_demo)
    date_str = (now_utc + BD).date().isoformat()

    closed = [r for r in today if r.get("outcome") not in ("OPEN", None)
              and r.get("pnl") is not None]
    open_now = [r for r in today if r.get("outcome") == "OPEN"]

    if not closed and not open_now:
        return f"📅 *{date_str} (BD)*\n\nNo trades taken today."

    wins = [r for r in closed if r["pnl"] > 0]
    losses = [r for r in closed if r["pnl"] <= 0]
    total_pnl = sum(r["pnl"] for r in closed)
    wr = round(len(wins) / len(closed) * 100) if closed else 0

    lines = [f"📅 *{date_str} (BD)*", ""]
    lines.append("*Overview*")
    lines.append(f"Trades: {len(closed)} closed" +
                 (f" · {len(open_now)} still open" if open_now else ""))
    if closed:
        lines.append(f"Result: {_money(total_pnl)} · Win rate {wr}% "
                     f"({len(wins)}W / {len(losses)}L)")

    # ── per agent ──
    agents: dict[str, dict] = {}
    for r in closed:
        a = agents.setdefault(_agent_of(r), {"pnl": 0.0, "w": 0, "l": 0, "n": 0})
        a["pnl"] += r["pnl"]
        a["n"] += 1
        a["w" if r["pnl"] > 0 else "l"] += 1
    if agents:
        lines += ["", "*By agent*"]
        for name, a in sorted(agents.items(), key=lambda kv: -kv[1]["pnl"]):
            lines.append(f"• {name} — {_money(a['pnl'])} · "
                         f"{a['w']}W/{a['l']}L ({a['n']})")

    # ── why losses ──
    if losses:
        lines += ["", "*Losses — why*"]
        for r in sorted(losses, key=lambda x: x["pnl"]):
            reason = _LOSS_REASON.get(r.get("outcome", ""), r.get("outcome", "?"))
            rr = r.get("actual_rr")
            rr_s = f" · RR {rr}" if rr is not None else ""
            lines.append(f"🔴 {_agent_of(r)} {r.get('symbol','?')} "
                         f"{r.get('direction','')} {_money(r['pnl'])} · "
                         f"{reason}{rr_s}")
            lines.append(f"   _{_strat_of(r)}_" +
                         (f" — {r.get('rationale','')[:90]}" if r.get("rationale") else ""))

    # ── best / worst ──
    if closed:
        best = max(closed, key=lambda r: r["pnl"])
        worst = min(closed, key=lambda r: r["pnl"])
        lines += ["", f"Best: {_agent_of(best)} {best.get('symbol','')} "
                      f"{_money(best['pnl'])} · Worst: {_agent_of(worst)} "
                      f"{worst.get('symbol','')} {_money(worst['pnl'])}"]

    if open_now:
        lines += ["", f"_{len(open_now)} position(s) still open at report time._"]

    return "\n".join(lines)


# ── side effects ──────────────────────────────────────────────────────────────

def _write_state(extra: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(), **extra}), encoding="utf-8")
    except Exception:
        pass


def send_report() -> str:
    from trading_agents import trade_journal
    records = trade_journal.get_all(limit=2000)
    msg = build_report(records, datetime.now(timezone.utc))
    try:
        from trading_agents import telegram_hq
        telegram_hq.send("digest", msg, title="EOD Daily Trade Report")
    except Exception as e:
        log.warning("telegram send failed: %s\n%s", e, msg)
    _write_state({"sent": True})
    return msg


def _secs_to_hour(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    ap = argparse.ArgumentParser(description="EOD daily trade report (Telegram)")
    ap.add_argument("--once", action="store_true", help="build + send now")
    ap.add_argument("--loop", action="store_true", help="send daily at 17:00 UTC (23:00 BD)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if args.loop:
        log.info("EOD report loop started — fires daily 17:00 UTC (23:00 BD)")
        _write_state({"booted": True})
        while True:
            time.sleep(_secs_to_hour(SEND_HOUR_UTC))
            try:
                send_report()
                log.info("EOD report sent")
            except Exception as e:
                log.error("report failed: %s", e)
            time.sleep(120)  # clear the target minute so we don't double-fire
    else:
        print(send_report())


if __name__ == "__main__":
    main()
