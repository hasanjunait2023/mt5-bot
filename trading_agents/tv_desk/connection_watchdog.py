"""TV Connection Watchdog — keep the VPS TradingView session alive.

TradingView paid plans allow ONE active session. The account is shared across
the user's devices, so logging in elsewhere bumps the VPS session → the chart
shows "Reconnect"/"Connect" and the tv_desk agents go blind until it's clicked.

This watchdog (runs only on the VPS) detects that state via CDP and clicks
Reconnect so the agents keep working — UNLESS paused, so the user can use
TradingView on their own device without a tug-of-war over the single session.

  python -m trading_agents.tv_desk.connection_watchdog --loop --interval 45
  python -m trading_agents.tv_desk.connection_watchdog --pause 30   # pause 30 min
  python -m trading_agents.tv_desk.connection_watchdog --resume

Pause is also honoured from a Telegram command (/tv_pause) by writing the same
flag file, and from env TV_WATCHDOG_PAUSE=1 (rolling 1h).
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone

from . import config, store
from .tv_client import TVClient, TVLock, TVError

log = logging.getLogger("tv_desk.watchdog")

AGENT_DIR = config.LOG_ROOT / "tv_watchdog"
PAUSE_FILE = AGENT_DIR / "_pause_until"   # unix ts until which auto-reconnect is paused
DEFAULT_INTERVAL = int(os.getenv("TV_WATCHDOG_INTERVAL", "45"))
TOPIC = os.getenv("TV_WATCHDOG_TOPIC", "tv_status")


# ── Telegram (best-effort, never fatal) ──────────────────────────────────────
def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from .. import telegram_hq
        telegram_hq.send(TOPIC, f"🖥️ TV Watchdog: {msg}", level=level)
    except Exception:
        log.info("notify (%s): %s", level, msg)


# ── Pause control ────────────────────────────────────────────────────────────
def _paused_until() -> float:
    if os.getenv("TV_WATCHDOG_PAUSE", "").strip().lower() in ("1", "true", "yes"):
        return time.time() + 3600  # env pause = rolling 1h
    try:
        if PAUSE_FILE.exists():
            return float(PAUSE_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    return 0.0


def pause_for(minutes: int) -> float:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    until = time.time() + minutes * 60
    PAUSE_FILE.write_text(str(until), encoding="utf-8")
    return until


def resume() -> None:
    try:
        PAUSE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── Disconnect detection + reconnect (run in the TV page via CDP) ─────────────
# A normally-connected TradingView chart has NO "Reconnect"/"Try again" button,
# but DOES have ubiquitous "Connect" controls (broker/account) — so match only a
# VISIBLE Reconnect/Try-again button, or an explicit datafeed-loss banner phrase.
# Never the bare word "Connect" (that caused false reconnect clicks).
_VISIBLE = ("const vis = e => { const r = e.getBoundingClientRect(); "
            "return r.width > 1 && r.height > 1 && e.offsetParent !== null; };")

_DETECT_JS = r"""
(() => {
  %s
  const btns = [...document.querySelectorAll('button,[role="button"],a')];
  const rc = btns.find(e => /^(reconnect|try again)$/i.test((e.textContent||'').trim()) && vis(e));
  const txt = (document.body && document.body.innerText || '');
  const banner = /connection (lost|problem|error|interrupted)|trying to (re)?connect|signed in from another device|your session (has )?expired/i.test(txt);
  return { disconnected: !!rc || banner, hasButton: !!rc,
           buttonText: rc ? rc.textContent.trim() : null, banner };
})()
""" % _VISIBLE

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
  return { clicked: true, text: rc.textContent.trim() };
})()
""" % _VISIBLE


def _eval(tv: TVClient, js: str) -> dict:
    res = tv.call("ui_evaluate", {"expression": js}, timeout=20) or {}
    return res.get("result", res) if isinstance(res, dict) else {}


def _connection_state(tv: TVClient) -> dict:
    """Return {connected, disconnected, detail}. DOM 'reconnect' affordance is the
    primary signal (health 'unknown' alone just means no chart open, not down)."""
    health = {}
    try:
        health = tv.health() or {}
    except Exception as e:
        health = {"success": False, "error": str(e)}
    det = {}
    try:
        det = _eval(tv, _DETECT_JS)
    except Exception as e:
        det = {"error": str(e)}
    disconnected = bool(det.get("disconnected"))
    connected = (not disconnected) and bool(health.get("api_available", False))
    return {"connected": connected, "disconnected": disconnected,
            "health_api": health.get("api_available"), "detect": det}


# ── One cycle ────────────────────────────────────────────────────────────────
_tv: TVClient | None = None


def _get_tv() -> TVClient:
    global _tv
    if _tv is not None and _tv.proc.poll() is None:
        return _tv
    if _tv is not None:
        try:
            _tv.close()
        except Exception:
            pass
    _tv = TVClient()
    return _tv


def run_once() -> dict:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    paused = time.time() < _paused_until()
    state = {"mode": "watchdog", "running": True, "idle": True,
             "paused": paused, "ts": now_iso}

    if paused:
        state["action"] = "paused"
        store.write_state(AGENT_DIR, state)
        return state

    try:
        tv = _get_tv()
        chk = _connection_state(tv)
        state.update({"connected": chk["connected"], "disconnected": chk["disconnected"]})

        if not chk["disconnected"]:
            state["action"] = "ok"
            store.write_state(AGENT_DIR, state)
            return state

        # Disconnected → reclaim the session (drive action: take the shared TV lock
        # briefly; if an agent holds it, TV is in use/connected → skip this cycle).
        lock = TVLock(wait=8, poll=2)
        if not lock.acquire():
            state["action"] = "skip_locked"
            store.write_state(AGENT_DIR, state)
            return state
        try:
            _notify("session dropped (likely signed in elsewhere) — reconnecting…", "WARNING")
            try:
                _eval(tv, _CLICK_JS)
            except Exception as e:
                log.warning("reconnect click error: %s", e)
            time.sleep(8)
            chk2 = _connection_state(tv)
            if not chk2["disconnected"]:
                _notify("reconnected ✅ — agents resumed.", "INFO")
                state.update({"action": "reconnected", "connected": True, "disconnected": False})
            else:
                _notify("reconnect attempt did not restore the session — will retry.", "WARNING")
                state.update({"action": "reconnect_failed", "connected": False})
        finally:
            lock.release()
    except TVError as e:
        log.warning("TV unavailable: %s", e)
        state.update({"action": "tv_error", "error": str(e), "idle": False})
    except Exception as e:
        log.exception("watchdog cycle error")
        state.update({"action": "error", "error": str(e), "idle": False})

    store.write_state(AGENT_DIR, state)
    return state


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="run forever")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    ap.add_argument("--pause", type=int, metavar="MIN",
                    help="pause auto-reconnect for N minutes, then exit")
    ap.add_argument("--resume", action="store_true", help="clear any pause, then exit")
    args = ap.parse_args()

    if args.resume:
        resume()
        print("TV watchdog resumed")
        return
    if args.pause:
        until = pause_for(args.pause)
        print(f"TV watchdog paused for {args.pause} min (until {datetime.fromtimestamp(until)})")
        return

    if args.loop:
        log.info("TV connection watchdog loop (interval %ss)", args.interval)
        while True:
            try:
                run_once()
            except Exception:
                log.exception("run_once failed")
            time.sleep(args.interval)
    else:
        print(run_once())


if __name__ == "__main__":
    main()
