"""
Daily agent activity report — a short Telegram brief, once a day at 22:00 Dhaka,
answering "what did each agent do today, and who did nothing?".

Pure data aggregation (no LLM): folds the LLM telemetry (logs/agent_metrics.jsonl),
the trade journal (logs/journal/*.jsonl), and the orchestrator process state
(logs/_orchestrator_state.json) into one compact message.

    python -m trading_agents.daily_agent_report           # build + send once now
    python -m trading_agents.daily_agent_report --loop     # send daily at 22:00 BD
    python -m trading_agents.daily_agent_report --dry      # print, do not send
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

BD = timezone(timedelta(hours=6))            # Asia/Dhaka, no DST
METRICS = BASE_DIR / "logs" / "agent_metrics.jsonl"
ORCH = BASE_DIR / "logs" / "_orchestrator_state.json"
SEND_HOUR_UTC = 16                            # 22:00 Dhaka


def _today_start_utc() -> datetime:
    """UTC instant of 00:00 today in Dhaka time."""
    now_bd = datetime.now(BD)
    return now_bd.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _parse_ts(s) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _read_jsonl(p: Path) -> list[dict]:
    out: list[dict] = []
    try:
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except Exception:
                        pass
    except Exception:
        pass
    return out


# ── LLM telemetry ────────────────────────────────────────────────────────────

def _llm_activity(cutoff: datetime) -> tuple[dict, list[str]]:
    """Return (worked_today, silent_today). worked_today[agent] = {calls, errors,
    backends}. silent_today = agents seen historically but idle today."""
    rows = _read_jsonl(METRICS)
    seen: set[str] = set()
    worked: dict[str, dict] = {}
    for e in rows:
        agent = e.get("agent", "?")
        seen.add(agent)
        ts = _parse_ts(e.get("ts"))
        if ts is None or ts < cutoff:
            continue
        g = worked.setdefault(agent, {"calls": 0, "errors": 0, "backends": set()})
        g["calls"] += 1
        if not e.get("ok", True):
            g["errors"] += 1
        if e.get("backend"):
            g["backends"].add(e["backend"])
    silent = sorted(seen - set(worked))
    return worked, silent


# ── Trades ───────────────────────────────────────────────────────────────────

def _trades_today(cutoff: datetime) -> dict:
    """Per-source: opens today + realized pnl from closes today."""
    try:
        from trading_agents import trade_journal
        recs = trade_journal._read_raw()
    except Exception:
        recs = _read_jsonl(BASE_DIR / "logs" / "trade_journal.jsonl")
        jdir = BASE_DIR / "logs" / "journal"
        if jdir.exists():
            for sh in jdir.glob("*.jsonl"):
                recs += _read_jsonl(sh)
    by_src: dict[str, dict] = {}
    for r in recs:
        src = r.get("source") or r.get("agent") or "?"
        ot = _parse_ts(r.get("open_time"))
        ct = _parse_ts(r.get("close_time"))
        if ot and ot >= cutoff:
            by_src.setdefault(src, {"opens": 0, "pnl": 0.0, "closed": 0})["opens"] += 1
        if ct and ct >= cutoff and r.get("pnl") is not None:
            g = by_src.setdefault(src, {"opens": 0, "pnl": 0.0, "closed": 0})
            g["pnl"] += float(r["pnl"])
            g["closed"] += 1
    return by_src


# ── Orchestrator process state ────────────────────────────────────────────────

def _control_plane() -> dict:
    try:
        orch = json.loads(ORCH.read_text(encoding="utf-8")) if ORCH.exists() else {}
    except Exception:
        orch = {}
    svcs = orch.get("services", [])
    up = [s for s in svcs if s.get("status") == "running"]
    failed = [s for s in svcs if s.get("status") == "failed"]
    other = [s for s in svcs if s.get("status") not in ("running", "failed")]
    fresh = False
    try:
        fresh = (time.time() - ORCH.stat().st_mtime) < 180
    except Exception:
        pass
    return {"total": len(svcs), "up": up, "failed": failed, "other": other, "fresh": fresh}


# ── Build ──────────────────────────────────────────────────────────────────

def build_report() -> str:
    cutoff = _today_start_utc()
    worked, silent = _llm_activity(cutoff)
    trades = _trades_today(cutoff)
    cp = _control_plane()

    day = datetime.now(BD).strftime("%d %b")
    L: list[str] = [f"📋 *Daily Agent Report* · {day}"]

    # Control plane
    if cp["total"]:
        dot = "🟢" if cp["fresh"] else "🔴"
        L.append(f"{dot} Control plane: {len(cp['up'])}/{cp['total']} up")
        if cp["failed"]:
            L.append("⚠️ FAILED: " + ", ".join(s.get("id", s.get("name", "?")) for s in cp["failed"]))
        if cp["other"]:
            L.append("⚪ not running: " + ", ".join(
                f"{s.get('id','?')}({s.get('status','?')})" for s in cp["other"]))
    else:
        L.append("🔴 Control plane: orchestrator not reporting")

    # Worked today (LLM)
    L.append("\n*Worked today*")
    if worked:
        for a in sorted(worked, key=lambda k: -worked[k]["calls"]):
            g = worked[a]
            be = "/".join(sorted(g["backends"])) or "?"
            err = f" · {g['errors']}err" if g["errors"] else ""
            L.append(f"• {a} — {g['calls']} calls ({be}){err}")
    else:
        L.append("• (no LLM agent activity today)")

    # Trades today
    if trades:
        bits = []
        net = 0.0
        for src, g in sorted(trades.items(), key=lambda kv: -kv[1]["opens"]):
            net += g["pnl"]
            seg = f"{src} {g['opens']}"
            if g["closed"]:
                seg += f"({g['pnl']:+.2f})"
            bits.append(seg)
        L.append("💹 Trades today: " + ", ".join(bits) + f" | net {net:+.2f}")
    else:
        L.append("💤 No trades today")

    # Idle / no work today
    if silent:
        L.append("\n*Quiet today* (no LLM calls)")
        L.append("• " + ", ".join(silent))

    return "\n".join(L)


def send_report() -> None:
    msg = build_report()
    try:
        try:
            from dotenv import load_dotenv
            load_dotenv(BASE_DIR / ".env")
        except Exception:
            pass
        from trading_agents import telegram_hq
        telegram_hq.send("ceo", msg, title="Daily Agent Report")
        print("agent report sent")
    except Exception as e:
        print(f"send failed: {e}\n\n{msg}")


def _secs_to_hour(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="send daily at 22:00 Dhaka")
    ap.add_argument("--hour", type=int, default=SEND_HOUR_UTC, help="UTC send hour")
    ap.add_argument("--dry", action="store_true", help="print only, do not send")
    args = ap.parse_args()

    if args.dry:
        print(build_report())
        return
    if not args.loop:
        send_report()
        return
    while True:
        time.sleep(_secs_to_hour(args.hour))
        send_report()
        time.sleep(120)


if __name__ == "__main__":
    main()
