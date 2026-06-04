"""
EAGuardian — Live execution watchdog for all running EAs.

Polls _live_state.json every 60s. Detects soft anomalies (warn Junait) and hard
anomalies (possible bug → auto-escalate to dev team's DebugInvestigator).

Run alongside the live trader:
  python -m trading_agents.ea_agents.ea_guardian
  python -m trading_agents.ea_agents.ea_guardian --once
  python -m trading_agents.ea_agents.ea_guardian --ea S6
"""

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("EAGuardian")

BASE_DIR = Path(__file__).parent.parent.parent
LIVE_STATE = BASE_DIR / "mt5_bridge" / "_live_state.json"
LIVE_LOG   = BASE_DIR / "mt5_bridge" / "_live_log.txt"
CONFIG_FILE = Path(__file__).parent / "ea_agents_config.json"
GUARDIAN_STATE = BASE_DIR / "logs" / "ea_agents" / "_guardian_state.json"

_NOTIFIER = None

def _get_notifier():
    global _NOTIFIER
    if _NOTIFIER is None:
        from trading_agents.dev_agents.notifier import notify as _n
        _NOTIFIER = _n
    return _NOTIFIER


def notify(msg: str, level: str = "INFO") -> None:
    try:
        _get_notifier()(msg, level=level, category="ea_guardian")
    except Exception as e:
        log.warning("Notify failed: %s", e)


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_live_state() -> dict:
    try:
        return json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tail_log(lines: int = 100) -> str:
    try:
        text = LIVE_LOG.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        return ""


def _load_guardian_state() -> dict:
    if GUARDIAN_STATE.exists():
        try:
            return json.loads(GUARDIAN_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_guardian_state(state: dict) -> None:
    GUARDIAN_STATE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    GUARDIAN_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _analyze_ea_positions(ea_name: str, positions: list, thresholds: dict, history: dict) -> list[dict]:
    """Return list of detected anomalies for a given EA's current positions."""
    anomalies = []
    if not positions:
        return anomalies

    # consecutive losses from recent closed trades (approximated via profit values)
    losses = [p for p in positions if p.get("profit", 0) < 0]
    cons_losses = 0
    for p in reversed(positions):
        if p.get("profit", 0) < 0:
            cons_losses += 1
        else:
            break

    hard_cons = thresholds.get("hard_max_consecutive_losses", 5)
    soft_cons = thresholds.get("soft_max_consecutive_losses", 3)
    if cons_losses >= hard_cons:
        anomalies.append({
            "severity": "HARD",
            "type": "consecutive_losses",
            "detail": f"{cons_losses} consecutive losing positions open",
        })
    elif cons_losses >= soft_cons:
        anomalies.append({
            "severity": "SOFT",
            "type": "consecutive_losses",
            "detail": f"{cons_losses} consecutive losses — monitoring",
        })

    # single position stuck too long (> 4 hours open)
    now = datetime.now(timezone.utc).timestamp()
    for pos in positions:
        open_time = pos.get("open_time", "")
        try:
            opened = datetime.fromisoformat(open_time).timestamp()
            hours_open = (now - opened) / 3600
            if hours_open > 4:
                anomalies.append({
                    "severity": "SOFT",
                    "type": "position_stuck",
                    "detail": f"Position {pos.get('ticket')} open {hours_open:.1f}h — possible execution issue",
                })
        except Exception:
            pass

    return anomalies


def _analyze_account(account: dict, thresholds: dict) -> list[dict]:
    """Detect account-level anomalies."""
    anomalies = []
    dd = account.get("daily_dd_pct", 0)
    total_dd = account.get("total_dd_pct", 0)

    hard_dd = thresholds.get("hard_dd_pct", 15)
    soft_dd = thresholds.get("soft_dd_pct", 10)

    if total_dd >= hard_dd:
        anomalies.append({
            "severity": "HARD",
            "type": "drawdown_critical",
            "detail": f"Total drawdown {total_dd:.1f}% — at risk of max DD breach",
        })
    elif total_dd >= soft_dd:
        anomalies.append({
            "severity": "SOFT",
            "type": "drawdown_warning",
            "detail": f"Total drawdown {total_dd:.1f}% — approaching limit",
        })
    return anomalies


def _escalate_to_dev(ea_name: str, symptom: str) -> str:
    """Auto-escalate a HARD anomaly to the dev team's DebugInvestigator."""
    try:
        from trading_agents.dev_agents.debug_investigator import investigate
        # Construct with a sentinel when no key is set so the SDK doesn't raise here;
        # investigate() routes through chat_resilient, which falls back to the claude
        # CLI (OAuth subscription) / NVIDIA when this client's key is bad/missing.
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or "sk-ant-noop")
        result = investigate(ea_name, symptom, client)
        hypothesis = result.get("hypothesis", "Unknown")
        confidence = result.get("confidence", "?")
        fix = result.get("suggested_fix", "See debug report")
        return f"DevTeam hypothesis ({confidence}): {hypothesis}\nFix: {fix}"
    except Exception as e:
        return f"Dev team escalation failed: {e}"


def _is_active_session() -> bool:
    """Return True if current UTC hour is within London or NY trading session."""
    hour = datetime.now(timezone.utc).hour
    return (7 <= hour < 12) or (13 <= hour < 17)


def run_once(filter_ea: str | None = None) -> dict:
    """Single check pass. Returns {ea_name: [anomalies]}."""
    cfg = _load_config()
    thresholds = cfg.get("guardian_thresholds", {})
    state = _read_live_state()
    history = _load_guardian_state()
    results = {}

    # Proactive DD kill-switch — runs every guardian poll (~60s) even when no
    # incident is in flight. Deterministic survival rail; only acts if account
    # total_dd >= halt_dd_pct (20%). Wrapped so it can never break the loop.
    try:
        from trading_agents.incident_pipeline import watchdog_tick
        wt = watchdog_tick()
        if wt.get("halted"):
            log.critical("watchdog: KILL-SWITCH ACTIVE (dd=%s%%)", wt.get("dd"))
    except Exception as e:
        log.warning("watchdog_tick failed: %s", e)

    # account-level check
    account = state.get("account", {})
    acct_anomalies = _analyze_account(account, thresholds)
    if acct_anomalies:
        results["ACCOUNT"] = acct_anomalies

    # per-EA checks (JTCC magic 20260600 is owned by JTCC system, skip here)
    JTCC_MAGIC = 20260600
    ea_positions = state.get("ea_positions", {})
    if not ea_positions:
        # fall back to flat positions list, excluding JTCC-owned positions
        all_pos = [p for p in state.get("positions", [])
                   if p.get("magic") != JTCC_MAGIC]
        ea_positions = {"ALL": all_pos}
    else:
        # Filter JTCC positions out of each EA bucket (defensive)
        ea_positions = {
            ea: [p for p in pos if p.get("magic") != JTCC_MAGIC]
            for ea, pos in ea_positions.items()
        }

    for ea_name, positions in ea_positions.items():
        if filter_ea and filter_ea.upper() not in ea_name.upper():
            continue
        anomalies = _analyze_ea_positions(ea_name, positions, thresholds, history)
        if anomalies:
            results[ea_name] = anomalies

    # no trades during active session
    if _is_active_session():
        last_trades = state.get("daily_trades", {})
        total_today = sum(last_trades.values())
        hour = datetime.now(timezone.utc).hour
        if total_today == 0 and hour >= 9:
            results.setdefault("SYSTEM", []).append({
                "severity": "SOFT",
                "type": "no_trades",
                "detail": f"0 trades placed today during active session (hour {hour} UTC)",
            })

    # ── Notify with STATE-BASED DEDUP ─────────────────────────────────────────
    # Telegram should only get: urgent (HARD escalations), first occurrence of
    # a real SOFT issue, and resolution confirmations. NOT the same warning
    # every 60s heartbeat. Key each anomaly by ea:type (stable across cycles)
    # and only message on a state CHANGE.
    prev_active = history.get("active_alerts", {}) if isinstance(history, dict) else {}
    new_active: dict = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    for ea_name, anomalies in results.items():
        for anomaly in anomalies:
            severity = anomaly["severity"]
            detail   = anomaly["detail"]
            atype    = anomaly["type"]
            key      = f"{ea_name}:{atype}"
            prev     = prev_active.get(key)
            log.warning("[%s] %s anomaly: %s", ea_name, severity, detail)

            if severity == "HARD":
                if prev is not None and prev.get("severity") == "HARD":
                    # same incident still open — do NOT re-escalate every cycle
                    new_active[key] = {"severity": "HARD", "detail": detail,
                                       "notified": True,
                                       "since": prev.get("since", now_iso)}
                    continue
                # new HARD (or escalated from SOFT) → CEO incident pipeline once
                try:
                    from trading_agents.incident_pipeline import report as _report
                    inc = _report(
                        source_agent="ea_guardian", component=ea_name,
                        symptom=detail, severity="CRITICAL", detail=anomaly,
                    )
                    log.warning("[%s] incident %s -> %s", ea_name,
                                inc.get("id"), inc.get("status"))
                except Exception as e:
                    log.error("incident pipeline unavailable (%s); fallback", e)
                    dev_report = _escalate_to_dev(ea_name, detail)
                    notify(
                        f"*EAGuardian CRITICAL [{ea_name}]*\n"
                        f"Issue: {detail}\n\n{dev_report}\n\n"
                        f"Dev team notified (pipeline fallback).",
                        level="CRITICAL")
                new_active[key] = {"severity": "HARD", "detail": detail,
                                   "notified": True, "since": now_iso}
            else:
                # SOFT: 'no_trades' is pure heartbeat noise → log only, never
                # Telegram. Other SOFT → alert ONCE when it first appears.
                notified = bool(prev and prev.get("notified"))
                if atype != "no_trades" and prev is None:
                    notify(f"*EAGuardian [{ea_name}]*\nWarning: {detail}",
                           level="WARNING")
                    notified = True
                new_active[key] = {"severity": "SOFT", "detail": detail,
                                   "notified": notified,
                                   "since": (prev or {}).get("since", now_iso)}

    # Resolution confirmation — only for alerts we actually notified about.
    for key, rec in prev_active.items():
        if key not in new_active and rec.get("notified"):
            notify(
                f"*EAGuardian* ✅ Resolved — {key.split(':', 1)[0]}: "
                f"{rec.get('detail', 'issue')} — no longer present.",
                level="INFO")

    _save_guardian_state({
        "last_check": now_iso,
        "anomalies_found": sum(len(v) for v in results.values()),
        "details": results,
        "active_alerts": new_active,
        "account": {
            "equity": account.get("equity"),
            "daily_dd_pct": account.get("daily_dd_pct"),
            "total_dd_pct": account.get("total_dd_pct"),
        },
    })
    return results


def run_loop(filter_ea: str | None = None) -> None:
    cfg = _load_config()
    interval = cfg.get("guardian_poll_seconds", 60)
    log.info("EAGuardian started — polling every %ds", interval)
    while True:
        try:
            results = run_once(filter_ea)
            if not results:
                log.info("All EAs healthy")
        except Exception as e:
            log.error("Guardian check failed: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    filter_ea = None
    if "--ea" in sys.argv:
        filter_ea = sys.argv[sys.argv.index("--ea") + 1]
    if "--once" in sys.argv:
        results = run_once(filter_ea)
        print(json.dumps(results, indent=2, default=str))
    else:
        run_loop(filter_ea)
