"""tv_layout — connection readiness + dedicated-layout helpers.

Keeps the user's working chart untouched by switching to a dedicated saved
layout (default "AUTOMATION") before the agent draws. All best-effort: if the
layout doesn't exist or switching fails, the run continues on the active chart
(it just clears its own old drawings each pass instead).
"""

from __future__ import annotations

import logging
import time

from . import config
from .tv_client import TVClient, TVError

log = logging.getLogger("tv_desk.layout")


# ── Session-reconnect (TradingView allows ONE active session; logging in on the
# user's own device bumps the VPS → the chart shows a "Reconnect"/"Try again"
# button while CDP stays connected). Each agent reconnects-then-works via this,
# so it grabs the shared session at the moment it needs to act. Mirrors the
# detect/click JS in connection_watchdog (kept inline to avoid a circular import).
_VIS = ("const vis = e => { const r = e.getBoundingClientRect(); "
        "return r.width > 1 && r.height > 1 && e.offsetParent !== null; };")

_DETECT_JS = r"""
(() => {
  %s
  const btns = [...document.querySelectorAll('button,[role="button"],a')];
  const rc = btns.find(e => /^(reconnect|try again)$/i.test((e.textContent||'').trim()) && vis(e));
  const txt = (document.body && document.body.innerText || '');
  const banner = /connection (lost|problem|error|interrupted)|trying to (re)?connect|signed in from another device|your session (has )?expired/i.test(txt);
  return { disconnected: !!rc || banner, hasButton: !!rc };
})()
""" % _VIS

_CLICK_JS = r"""
(() => {
  %s
  const btns = [...document.querySelectorAll('button,[role="button"],a')];
  const rc = btns.find(e => /^(reconnect|try again)$/i.test((e.textContent||'').trim()) && vis(e));
  if (!rc) return { clicked: false };
  const r = rc.getBoundingClientRect();
  const x = r.x + r.width / 2, y = r.y + r.height / 2;
  ['pointerover','pointerdown','mousedown','pointerup','mouseup','click'].forEach(t => {
    const E = t.startsWith('pointer') ? PointerEvent : MouseEvent;
    rc.dispatchEvent(new E(t, {bubbles:true, cancelable:true, view:window,
      clientX:x, clientY:y, pointerId:1, pointerType:'mouse', button:0}));
  });
  return { clicked: true };
})()
""" % _VIS


def _eval(tv: TVClient, js: str) -> dict:
    try:
        res = tv.call("ui_evaluate", {"expression": js}, timeout=20) or {}
        return res.get("result", res) if isinstance(res, dict) else {}
    except Exception as e:
        log.warning("ui_evaluate failed: %s", e)
        return {}


def reconnect_if_needed(tv: TVClient, *, attempts: int = 3) -> bool:
    """If the chart shows a Reconnect/session-bumped affordance, click it and wait
    until the session is live again. Returns True if connected (or never down)."""
    for i in range(attempts):
        det = _eval(tv, _DETECT_JS)
        if not det.get("disconnected"):
            return True
        log.warning("TV session dropped (signed in elsewhere?) — reconnecting (%d/%d)", i + 1, attempts)
        _eval(tv, _CLICK_JS)
        time.sleep(8)
    # Final check after the last click
    return not _eval(tv, _DETECT_JS).get("disconnected", False)


def ensure_connected(tv: TVClient, *, try_launch: bool = True) -> bool:
    """True if TradingView is reachable AND the live session is connected.
    Launches the app if needed, then reclaims the shared session (clicks
    Reconnect) so the agent connects-then-works rather than reading a dead chart."""
    cdp = False
    try:
        h = tv.health()
        cdp = bool(h.get("cdp_connected"))
    except TVError as e:
        log.warning("health check failed: %s", e)
    if not cdp and try_launch:
        log.info("TradingView not connected — attempting launch")
        try:
            tv.launch()
            time.sleep(3)
            cdp = bool(tv.health().get("cdp_connected"))
        except Exception as e:
            log.warning("launch failed: %s", e)
    if not cdp:
        return False
    # CDP is up — now make sure the live data session isn't in the bumped/Reconnect
    # state before the agent starts reading charts.
    return reconnect_if_needed(tv)


def switch_to_automation(tv: TVClient, name: str | None = None) -> bool:
    """Best-effort switch to the dedicated automation layout."""
    name = name or config.LAYOUT_NAME
    try:
        res = tv.call("layout_switch", {"name": name}, timeout=20)
        if isinstance(res, dict) and res.get("success"):
            log.info("switched to layout '%s'", name)
            return True
        log.info("layout '%s' not switched (%s) — using active chart", name, res)
    except Exception as e:
        log.info("layout switch unavailable (%s) — using active chart", e)
    return False


def prep_symbol(tv: TVClient, tv_symbol: str, timeframe: str, *,
                clear: bool = True) -> None:
    """Point the chart at a symbol+timeframe and clear prior agent drawings."""
    tv.set_symbol(tv_symbol)
    tv.set_timeframe(timeframe)
    if clear:
        try:
            tv.clear_drawings()
        except Exception as e:
            log.debug("clear_drawings failed (non-fatal): %s", e)
