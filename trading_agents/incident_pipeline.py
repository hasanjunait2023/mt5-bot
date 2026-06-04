"""
Autonomous Incident Pipeline — CEO-centered.

Flow:
  detection agent (ea_guardian / supervisor / any) -> report()
    -> circuit breakers (DD kill-switch, fix-loop guard, global enable)
    -> route to CEO (Maic's executive function): delegate to dev team,
       auto-fix + deploy  [FULL AUTO — user-chosen]
    -> verify; on verify-fail count toward fix-loop guard
    -> notify Telegram (CEO + Critical topics) AND write feedback for the
       originating agent so it learns its reported issue was resolved.

Circuit breakers are HARD-ON (survival rails, not optional):
  • account total_dd_pct >= halt_dd_pct  -> kill-switch: close all FxVault
    positions/orders via MT5, write halt flag, CRITICAL telegram, stop fixing.
  • same component fails > max_fix_attempts -> stop auto-fixing it, escalate
    to a human via CRITICAL telegram (prevents infinite bad-fix loops).

Config: configs/incident_pipeline.json (auto-created with safe defaults).
History (dashboard reads this): logs/_incidents.json
Originating-agent feedback:      logs/_incident_feedback.json
Kill-switch flag (bridge/EA):    mt5_bridge/_kill_switch.json
"""
from __future__ import annotations

import json
import time
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict

log = logging.getLogger("incident_pipeline")

_BASE      = Path(__file__).resolve().parents[1]          # "mt5 bot/"
_CFG_PATH  = _BASE / "configs" / "incident_pipeline.json"
_INCIDENTS = _BASE / "logs" / "_incidents.json"
_FEEDBACK  = _BASE / "logs" / "_incident_feedback.json"
_KILLFLAG  = _BASE / "mt5_bridge" / "_kill_switch.json"
_LIVESTATE = _BASE / "mt5_bridge" / "_live_state.json"

_DEFAULT_CFG = {
    "enabled":          True,
    "full_auto":        True,     # user-chosen: auto-fix + deploy, notify after
    "halt_dd_pct":      20.0,     # account total drawdown % -> kill-switch
    "max_fix_attempts": 3,        # per component, within lookback, before human
    "attempt_lookback_h": 12,
    "fxvault_magics":   [20260102, 20260500, 20260602],
    "history_cap":      300,
}


# ───────────────────────── config / io ─────────────────────────
def _cfg() -> dict:
    try:
        if _CFG_PATH.exists():
            return {**_DEFAULT_CFG, **json.loads(_CFG_PATH.read_text("utf-8"))}
    except Exception as e:
        log.warning("incident cfg read failed: %s", e)
    try:
        _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CFG_PATH.write_text(json.dumps(_DEFAULT_CFG, indent=2), "utf-8")
    except Exception:
        pass
    return dict(_DEFAULT_CFG)


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text("utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), "utf-8")
    except Exception as e:
        log.warning("write %s failed: %s", path.name, e)


def _tg(category: str, message: str, level: str = "INFO", title: str | None = None) -> None:
    try:
        from trading_agents.telegram_hq import send
        send(category, message, level=level, title=title)
    except Exception as e:                       # never let notify break the loop
        log.warning("telegram notify failed: %s", e)


# ───────────────────────── incident model ─────────────────────────
@dataclass
class Incident:
    source_agent: str
    component:    str
    symptom:      str
    severity:     str = "HIGH"                   # LOW|MEDIUM|HIGH|CRITICAL
    detail:       dict = field(default_factory=dict)
    id:           str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    opened_at:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status:       str = "open"                   # open|fixing|resolved|failed|halted|deferred
    resolution:   str = ""
    closed_at:    str = ""


def _record(inc: Incident) -> None:
    hist = _read_json(_INCIDENTS, [])
    hist = [h for h in hist if h.get("id") != inc.id]      # upsert
    hist.append(asdict(inc))
    hist = hist[-_cfg()["history_cap"]:]
    _write_json(_INCIDENTS, hist)


def _feedback(inc: Incident) -> None:
    """Write back so the agent that raised this learns the outcome."""
    fb = _read_json(_FEEDBACK, {})
    fb.setdefault(inc.source_agent, [])
    fb[inc.source_agent] = ([{
        "incident_id": inc.id, "component": inc.component,
        "symptom": inc.symptom, "status": inc.status,
        "resolution": inc.resolution, "closed_at": inc.closed_at,
    }] + fb[inc.source_agent])[:20]
    _write_json(_FEEDBACK, fb)


def feedback_for(agent: str) -> list:
    """A detection agent calls this to see resolutions of issues it raised."""
    return _read_json(_FEEDBACK, {}).get(agent, [])


# ───────────────────────── circuit breakers ─────────────────────────
def _account_dd_pct() -> float:
    st = _read_json(_LIVESTATE, {})
    return float(st.get("account", {}).get("total_dd_pct", 0.0) or 0.0)


def _kill_switch(reason: str) -> str:
    """Enforceable halt: close every FxVault position + pending order via MT5,
    write a halt flag, fire a CRITICAL telegram. Survival rail."""
    cfg = _cfg()
    magics = set(cfg["fxvault_magics"])
    closed, errs = 0, []
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            for p in (mt5.positions_get() or []):
                if p.magic in magics:
                    try:
                        mt5.Close(p.symbol, ticket=p.ticket); closed += 1
                    except Exception as e:
                        errs.append(str(e))
            for o in (mt5.orders_get() or []):
                if o.magic in magics:
                    try:
                        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE,
                                        "order": o.ticket})
                    except Exception as e:
                        errs.append(str(e))
            mt5.shutdown()
    except Exception as e:
        errs.append(f"MT5 unavailable: {e}")

    _write_json(_KILLFLAG, {"halt": True, "reason": reason,
                            "ts": datetime.now(timezone.utc).isoformat()})
    msg = (f"KILL-SWITCH TRIPPED\nReason: {reason}\n"
           f"Closed {closed} FxVault position(s); trading halted.\n"
           f"{'Errors: ' + '; '.join(errs[:3]) if errs else ''}")
    _tg("critical", msg, level="CRITICAL", title="🚨 Auto Kill-Switch")
    _tg("ceo", msg, level="CRITICAL", title="🚨 Kill-Switch (CEO notified)")
    log.critical(msg)
    return msg


def _fix_attempts(component: str) -> int:
    cfg = _cfg()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["attempt_lookback_h"])
    n = 0
    for h in _read_json(_INCIDENTS, []):
        if h.get("component") != component:
            continue
        if h.get("status") not in ("failed", "fixing"):
            continue
        try:
            if datetime.fromisoformat(h["opened_at"]) >= cutoff:
                n += 1
        except Exception:
            pass
    return n


# ───────────────────────── CEO routing ─────────────────────────
def _ceo_resolve(inc: Incident) -> tuple[str, bool]:
    """The CEO's executive function: take ownership, delegate the fix to the
    dev team, return (resolution_text, ok). FULL AUTO."""
    inc.status = "fixing"; _record(inc)
    _tg("ceo",
        f"Incident `{inc.id}` from *{inc.source_agent}*\n"
        f"Component: `{inc.component}`\nSymptom: {inc.symptom}\n"
        f"→ Delegating fix to dev team (full-auto).",
        level="WARNING", title="🧭 CEO took an incident")

    task = (f"Incident {inc.id} from {inc.source_agent}. "
            f"Component: {inc.component}. Symptom: {inc.symptom}. "
            f"Detail: {json.dumps(inc.detail)[:800]}. "
            f"Diagnose root cause and APPLY the fix (full-auto), then report.")
    try:
        from trading_agents.dev_agents.dev_lead import run_task
        out = run_task(task)
        kw_ok = not any(w in str(out).lower()
                        for w in ("failed", "error:", "could not", "exception"))
        verified = _verify_resolved(inc.component)
        ok = kw_ok if verified is None else verified
        return (str(out)[:1500], ok)
    except Exception as e:
        return (f"dev team delegation error: {e}", False)


_ORCH_STATE = _BASE / "logs" / "_orchestrator_state.json"
# component substring -> (heartbeat file, max fresh minutes). Only files known
# to exist; absent means "process-alive is enough".
_STATE_FRESH = {
    "jtcc":     ("logs/jtcc/_jtcc_state.json", 5),
    "ea_coach": ("logs/ea_agents/_coach_state.json", 720),
}


def _verify_resolved(component):
    """Confirm a component is ACTUALLY healthy from real system state rather than
    trusting the wording of the dev-team report. Returns True/False when state is
    determinable, else None (caller falls back to the text heuristic)."""
    import os as _os, time as _time
    comp = (component or "").lower()
    proc_ok = None
    try:
        d = _read_json(_ORCH_STATE, {})
        for s in (d.get("services", []) if isinstance(d, dict) else []):
            sid = str(s.get("id", "")).lower()
            if sid and (sid in comp or comp in sid):
                proc_ok = s.get("status") in ("running", "starting") and bool(s.get("pid"))
                break
    except Exception:
        pass
    fresh_ok = None
    for key, (rel, max_min) in _STATE_FRESH.items():
        if key in comp:
            fp = _BASE / rel
            try:
                if fp.exists():
                    fresh_ok = ((_time.time() - _os.path.getmtime(fp)) / 60.0) <= max_min
            except Exception:
                pass
            break
    if proc_ok is None and fresh_ok is None:
        return None
    return all(v for v in (proc_ok, fresh_ok) if v is not None)


# ───────────────────────── public entrypoint ─────────────────────────
def report(source_agent: str, component: str, symptom: str,
           severity: str = "HIGH", detail: dict | None = None) -> dict:
    """Single entrypoint every detection agent calls instead of escalating
    directly. Routes through the CEO with hard circuit breakers."""
    inc = Incident(source_agent=source_agent, component=component,
                   symptom=symptom, severity=severity, detail=detail or {})
    cfg = _cfg()
    _record(inc)

    if not cfg["enabled"]:
        inc.status = "deferred"
        inc.resolution = "pipeline disabled in config — logged only"
        inc.closed_at = datetime.now(timezone.utc).isoformat()
        _record(inc); _feedback(inc)
        _tg("dev_team", f"Incident `{inc.id}` logged (pipeline disabled): "
            f"{inc.component} — {inc.symptom}", level="WARNING")
        return asdict(inc)

    # — circuit breaker 1: drawdown kill-switch —
    dd = _account_dd_pct()
    if dd >= cfg["halt_dd_pct"]:
        inc.status = "halted"
        inc.resolution = _kill_switch(
            f"account total_dd {dd:.1f}% ≥ {cfg['halt_dd_pct']}% "
            f"(triggered while handling: {inc.component})")
        inc.closed_at = datetime.now(timezone.utc).isoformat()
        _record(inc); _feedback(inc)
        return asdict(inc)

    # — circuit breaker 2: fix-loop guard —
    attempts = _fix_attempts(inc.component)
    if attempts >= cfg["max_fix_attempts"]:
        inc.status = "failed"
        inc.resolution = (f"fix-loop guard: {inc.component} failed "
                          f"{attempts}× in {cfg['attempt_lookback_h']}h — "
                          f"auto-fix STOPPED, human escalation required")
        inc.closed_at = datetime.now(timezone.utc).isoformat()
        _record(inc); _feedback(inc)
        _tg("critical", f"Incident `{inc.id}` — {inc.resolution}",
            level="CRITICAL", title="🚨 Fix-loop guard tripped")
        _tg("ceo", f"Repeated failure on `{inc.component}` — needs you.",
            level="CRITICAL")
        return asdict(inc)

    # — route to CEO -> dev team (full-auto) —
    resolution, ok = _ceo_resolve(inc)
    inc.resolution = resolution
    inc.status = "resolved" if ok else "failed"
    inc.closed_at = datetime.now(timezone.utc).isoformat()
    _record(inc); _feedback(inc)

    lvl = "SUCCESS" if ok else "CRITICAL"
    _tg("ceo",
        f"Incident `{inc.id}` *{inc.status.upper()}*\n"
        f"{inc.component}: {inc.symptom}\n— {resolution[:600]}",
        level=lvl, title="🧭 CEO incident outcome")
    if not ok:
        _tg("critical",
            f"Auto-fix did NOT verify for `{inc.component}` "
            f"(incident {inc.id}). Will retry until fix-loop guard.",
            level="CRITICAL")
    # close the loop back to the agent that reported it
    _tg(inc.source_agent if inc.source_agent in (
            "ea_guardian", "supervisor") else "dev_team",
        f"Your reported issue `{inc.id}` ({inc.component}) is now "
        f"*{inc.status}*. {resolution[:300]}", level=lvl)
    return asdict(inc)


# ───────────────────────── proactive watchdog ─────────────────────────
def watchdog_tick() -> dict:
    """Schedule this (e.g. every few min) so the DD kill-switch fires even
    when no incident is in flight. Returns a small status dict."""
    cfg = _cfg()
    dd = _account_dd_pct()
    if cfg["enabled"] and dd >= cfg["halt_dd_pct"] and not _read_json(
            _KILLFLAG, {}).get("halt"):
        _kill_switch(f"watchdog: account total_dd {dd:.1f}% "
                     f"≥ {cfg['halt_dd_pct']}%")
        return {"halted": True, "dd": dd}
    return {"halted": bool(_read_json(_KILLFLAG, {}).get("halt")), "dd": dd}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        print(json.dumps(report("ea_guardian", "selftest.component",
              "synthetic symptom for pipeline self-test",
              severity="LOW", detail={"note": "selftest"}), indent=2))
    else:
        print(json.dumps(watchdog_tick(), indent=2))
