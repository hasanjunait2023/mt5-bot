"""
Auto-remediation — SAFE BY DEFAULT.

This is a *framework*, deliberately inert until Junait opts in. On a live
real-money trading system, an agent must not autonomously restart the bridge
or re-arm an EA on its own judgement. So:

  • Detectors call suggest(action, reason, detail) → a PROPOSAL is posted to
    Telegram and recorded as pending. NOTHING is executed.
  • execute_if_approved(action, token) runs an action ONLY if ALL hold:
        1. action is registered in ACTIONS (code-reviewed handlers only)
        2. action is in the allowlist  (configs/remediation.json)
        3. remediation is globally enabled (same config, default False)
        4. token matches an outstanding pending proposal
  • Ships with an EMPTY allowlist, enabled=False, and NO destructive
    handlers registered. Turning any of this on is a deliberate human act.

To enable a specific action later: add a code-reviewed handler to ACTIONS,
add its name to configs/remediation.json {"enabled": true,
"allowlist": ["..."]}, and wire the Telegram approval token round-trip.
"""

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("Remediation")

_BASE = Path(__file__).resolve().parent.parent
_CONFIG = _BASE / "configs" / "remediation.json"
_PENDING = _BASE / "logs" / "_remediation_pending.json"


def _config() -> dict:
    try:
        return json.loads(_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "allowlist": []}   # safe default


def _notify(msg: str, level: str = "WARNING") -> None:
    try:
        from trading_agents.dev_agents.notifier import notify
        notify(msg, level=level, category="critical")
    except Exception as e:
        log.warning("Notify failed: %s", e)


# ── Registered handlers ──────────────────────────────────────────────────────
# Intentionally empty of destructive actions. Add code-reviewed callables here
# (signature: (detail: dict) -> str) only when a specific remediation is
# approved for automation. Example shape kept for documentation:
#
#   def _restart_bridge(detail: dict) -> str: ...
#   ACTIONS = {"restart_bridge": _restart_bridge}
ACTIONS: dict = {}


def suggest(action: str, reason: str, detail: dict | None = None) -> str:
    """
    Propose a remediation. Posts a Telegram proposal and records it pending.
    NEVER executes. Returns the proposal token (for an approval round-trip).
    """
    token = f"{action}-{int(time.time())}"
    try:
        pending = json.loads(_PENDING.read_text(encoding="utf-8")) if _PENDING.exists() else {}
    except Exception:
        pending = {}
    pending[token] = {"action": action, "reason": reason,
                      "detail": detail or {}, "ts": time.time()}
    try:
        _PENDING.parent.mkdir(parents=True, exist_ok=True)
        _PENDING.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Could not persist pending proposal: %s", e)

    _notify(f"*Remediation proposed* (NOT executed)\n"
            f"Action: `{action}`\nReason: {reason}\n"
            f"Approve manually if appropriate — auto-exec is disabled.",
            level="WARNING")
    log.info("Proposed remediation %s (%s) — awaiting human action", action, token)
    return token


def execute_if_approved(action: str, token: str) -> str:
    """
    Run a remediation ONLY if every safety condition holds. Refuses loudly
    otherwise. This is the single execution chokepoint.
    """
    cfg = _config()
    if not cfg.get("enabled", False):
        return "REFUSED: remediation globally disabled (configs/remediation.json)"
    if action not in cfg.get("allowlist", []):
        return f"REFUSED: '{action}' not in allowlist"
    if action not in ACTIONS:
        return f"REFUSED: no registered handler for '{action}'"
    try:
        pending = json.loads(_PENDING.read_text(encoding="utf-8"))
        if token not in pending or pending[token]["action"] != action:
            return "REFUSED: no matching pending proposal for this token"
    except Exception:
        return "REFUSED: cannot verify pending proposal"

    try:
        result = ACTIONS[action](pending[token].get("detail", {}))
        del pending[token]
        _PENDING.write_text(json.dumps(pending, indent=2), encoding="utf-8")
        _notify(f"*Remediation executed*: `{action}` → {result}", level="WARNING")
        return f"EXECUTED: {result}"
    except Exception as e:
        _notify(f"*Remediation FAILED*: `{action}` → {e}", level="CRITICAL")
        return f"FAILED: {e}"
