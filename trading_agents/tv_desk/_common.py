"""_common — shared per-symbol pipeline + scheduling helpers for both agents."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import config, structure, synthesize, annotate, store, tracker
from .tv_client import TVClient

log = logging.getLogger("tv_desk.common")


def _telegram():
    import os
    if os.getenv("TV_DESK_NO_TELEGRAM") == "1":
        return None
    try:
        from .. import telegram_hq
        return telegram_hq
    except Exception:
        return None


def _corr_group(symbol: str) -> str | None:
    for g, members in config.CORR_GROUPS.items():
        if symbol in members:
            return g
    return None


def _topic_ready(tg, topic: str) -> bool:
    """True only if the Telegram topic has a forum thread configured + enabled.
    Avoids leaking posts into the group's General topic before /hq_setup."""
    try:
        cat = tg.load_config().get("categories", {}).get(topic, {})
        return cat.get("enabled", True) and cat.get("thread_id") is not None
    except Exception:
        return False


def _caption(facts: dict, plan: dict, session: str | None) -> str:
    dp = int(facts.get("dp", 5))
    head = f"📈 *{facts['name']}* `{facts['symbol']}` · {facts['entry_tf']} · {facts['mode']}"
    if session:
        head += f" · {session.upper()}"
    dr = facts["dealing_range"]
    ms = (facts.get("market_structure") or {})
    lines = [
        head, "",
        f"Bias: *{plan['bias']}* · {dr['zone']} (eq {dr['equilibrium']})"
        + (f" · {ms.get('trend')} {ms.get('event') or ''}" if ms.get("trend") else ""),
        plan.get("narrative", "")[:360], "",
    ]
    if plan.get("news"):
        ev = plan["news"][0]
        lines.append(f"⚠️ News in horizon: *{ev['title']}* ({ev['ccy']}) {ev['at']}")
        lines.append("")
    lines.append("*Entries:*")
    for k, e in enumerate(plan["entries"], 1):
        arrow = "🟢" if e["side"] == "BUY" else "🔴"
        tier = e.get("tier", "?")
        lines.append(
            f"{k}) {arrow} *{e['side']}* `{e['entry']:.{dp}f}` · SL `{e['sl']:.{dp}f}` · "
            f"TP1 `{e['tp1']:.{dp}f}` · TP2 `{e['tp2']:.{dp}f}` · "
            f"1:{e['rr'][0]:g}/1:{e['rr'][-1]:g} · *{tier}* {e.get('score','')} · {e['win_prob']}%"
        )
    lines.append("")
    lines.append(f"_{plan.get('source','llm')} · {datetime.now(timezone.utc).strftime('%H:%M')} UTC_")
    return "\n".join(lines)


def run_symbol(tv: TVClient, sym_cfg: dict, *, mode: str, agent_dir: Path,
               topic: str | None, session: str | None = None,
               broadcaster=None) -> dict:
    """Full pipeline for one symbol: analyze → synthesize → annotate → persist → notify."""
    res = structure.analyze(tv, sym_cfg, mode=mode)
    facts = res["facts"]
    plan = synthesize.synthesize(facts, mode=mode)

    entry_tf_code = "60" if mode == "intraday" else "15"
    event_id = f"{mode}-{facts['symbol']}-{int(time.time() * 1000)}"
    png = annotate.draw_plan(tv, facts, plan, entry_tf_code=entry_tf_code,
                             screenshot_name=event_id)
    chart_path = store.save_chart(agent_dir, event_id, png) if png else None

    event = {
        "id": event_id,
        "mode": mode,
        "session": session,
        "symbol": facts["symbol"],
        "name": facts["name"],
        "tv_symbol": facts["tv_symbol"],
        "entry_tf": facts["entry_tf"],
        "entry_tf_code": facts.get("entry_tf_code"),
        "price": facts["price"],
        "bias": plan["bias"],
        "narrative": plan.get("narrative", ""),
        "market_structure": facts.get("market_structure"),
        "htf_levels": facts.get("htf_levels"),
        "session_ranges": facts.get("session_ranges"),
        "absorption": facts.get("absorption"),
        "dealing_range": facts["dealing_range"],
        "pdh": facts.get("pdh"), "pdl": facts.get("pdl"),
        "entries": plan["entries"],
        "source": plan.get("source"),
        "news": plan.get("news") or [],
        "corr_group": _corr_group(facts["symbol"]),
        "top_tier": (plan["entries"][0].get("tier") if plan["entries"] else None),
        "chart_path": chart_path,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    store.append_event(agent_dir, event)
    try:
        tracker.record(agent_dir, event, mode=mode)
    except Exception:
        log.exception("tracker.record failed for %s", facts["symbol"])

    tg = _telegram() if topic else None
    if tg and _topic_ready(tg, topic):
        try:
            cap = _caption(facts, plan, session)
            if png:
                tg.send_photo(topic, png, cap,
                              dedupe_key=f"tvdesk|{mode}|{facts['symbol']}|{session or ''}")
            else:
                tg.send(topic, cap, level="INFO")
        except Exception:
            log.exception("telegram send failed for %s", facts["symbol"])
    elif tg and topic:
        log.info("telegram topic '%s' not set up (run /hq_setup) — skipping post for %s",
                 topic, facts["symbol"])

    if broadcaster:
        try:
            broadcaster({"type": f"tvdesk_{mode}", "data": event})
        except Exception:
            pass

    log.info("%s %s — %d entries (%s)", mode, facts["symbol"],
             len(plan["entries"]), plan.get("source"))
    return event


# ── scheduling ───────────────────────────────────────────────────────────────
def next_daily_bd(hour_bd: int, now: datetime | None = None) -> datetime:
    """Next UTC datetime for a daily fire at `hour_bd` Bangladesh time (UTC+6)."""
    now = now or datetime.now(timezone.utc)
    hour_utc = (hour_bd - config.BD_UTC_OFFSET_H) % 24
    cand = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if cand <= now:
        cand += timedelta(days=1)
    return cand


def sleep_until(target: datetime, *, heartbeat_dir: Path, heartbeat_state: dict,
                poll: float = 120.0):
    """Sleep until `target`, refreshing the agent state file every `poll`s so the
    orchestrator's file-freshness health check stays green while idle."""
    while True:
        now = datetime.now(timezone.utc)
        if now >= target:
            return
        remaining = (target - now).total_seconds()
        store.write_state(heartbeat_dir, {
            **heartbeat_state, "running": True, "idle": True,
            "next_run": target.isoformat(timespec="seconds"),
        })
        time.sleep(min(poll, max(1.0, remaining)))
