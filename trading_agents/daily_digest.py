"""
Daily portfolio digest — one Telegram message answering "is the whole thing
healthy and making money?" so you don't have to click through 12 dashboard pages.

Pulls from the same registry the dashboard Hub uses, the MTF account snapshot,
and the orchestrator's process state, then posts to the '📊 Daily Digest' topic.

    python -m trading_agents.daily_digest            # send once now
    python -m trading_agents.daily_digest --loop     # send daily at digest hour
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _read_json(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def build_digest() -> str:
    from trading_agents.registry.manifest import load_all
    from trading_agents.registry.schema import normalize

    lines: list[str] = []

    # ── Account (from the live trader snapshot) ──────────────────────────────
    acct = _read_json(BASE_DIR / "mt5_bridge" / "_live_state.json").get("account", {})
    if acct:
        pnl = acct.get("daily_pnl")
        sign = "🟢" if (pnl or 0) >= 0 else "🔴"
        lines.append(
            f"💰 Equity ${acct.get('equity', 0):.2f} | "
            f"Daily {sign} ${pnl:.2f} | DD {acct.get('daily_dd_pct', 0):.1f}%"
            if pnl is not None else
            f"💰 Equity ${acct.get('equity', 0):.2f}"
        )

    # ── Per-strategy status ──────────────────────────────────────────────────
    lines.append("\n*Strategies*")
    for m in load_all():
        try:
            e = normalize(m, BASE_DIR)
        except Exception:
            continue
        dot = {"running": "🟢", "halted": "🔴", "stale": "🟡",
               "stopped": "⚪", "idle": "🟢"}.get(e["status"], "⚪")
        if e["mode"] == "live":
            extra = f"daily ${e['account'].get('daily_pnl') or 0:.2f}"
        else:
            g = e.get("paper_gate") or {}
            extra = (f"gate {g.get('trades_done', 0)}/{g.get('trades_needed', 20)} "
                     f"PF {g.get('pf_current', 0):.2f}") if g else e["mode"]
        lines.append(f"{dot} {e['name']} — {e['mode']} · {extra}")

    # ── Control plane ────────────────────────────────────────────────────────
    orch = _read_json(BASE_DIR / "logs" / "_orchestrator_state.json")
    if orch:
        svcs = orch.get("services", [])
        up = sum(1 for s in svcs if s.get("status") == "running")
        failed = [s["name"] for s in svcs if s.get("status") == "failed"]
        age = time.time() - (BASE_DIR / "logs" / "_orchestrator_state.json").stat().st_mtime
        orch_dot = "🟢" if age < 100 else "🔴"
        lines.append(f"\n{orch_dot} *Control plane*: {up}/{len(svcs)} processes up")
        if failed:
            lines.append(f"⚠️ FAILED: {', '.join(failed)}")
    else:
        lines.append("\n🔴 *Control plane*: orchestrator not reporting")

    return "\n".join(lines)


def send_digest() -> None:
    msg = build_digest()
    try:
        from trading_agents import telegram_hq
        telegram_hq.send("digest", msg, title="Daily Portfolio Digest")
        print("digest sent")
    except Exception as e:
        print(f"digest send failed: {e}\n\n{msg}")


def _secs_to_hour(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target.replace(day=now.day)
        from datetime import timedelta
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="send daily at the digest hour")
    ap.add_argument("--hour", type=int, default=None, help="UTC hour (default from telegram config)")
    args = ap.parse_args()

    hour = args.hour
    if hour is None:
        try:
            from trading_agents import telegram_hq
            hour = telegram_hq.load_config().get("digest", {}).get("hour_utc", 6)
        except Exception:
            hour = 6

    if not args.loop:
        send_digest()
        return

    while True:
        time.sleep(_secs_to_hour(hour))
        send_digest()
        time.sleep(120)  # avoid double-fire within the same minute


if __name__ == "__main__":
    main()
