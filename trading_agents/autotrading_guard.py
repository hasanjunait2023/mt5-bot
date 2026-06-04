"""AutoTrading Guard — keep MT5 "Algo Trading" enabled on the headless VPS.

MT5's Algo Trading toolbar toggle resets to OFF whenever the terminal restarts
or crashes. While OFF, every order is rejected with retcode 10027
("AutoTrading disabled by client") — so the agents scan but silently never
trade. There is no MetaTrader5 API to flip it; it's a GUI toggle (Ctrl+E).

This guard polls the bridge /health (trade_allowed, sourced from
terminal_info().trade_allowed). When it reads False, it finds the MT5 window on
the xrdp X display and sends Ctrl+E via xdotool to re-enable it, then verifies.

  python -m trading_agents.autotrading_guard --loop --interval 60

Linux/VPS only (needs the xrdp X session + xdotool). Best-effort + never fatal.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("autotrading_guard")

BRIDGE = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090").rstrip("/")
DISPLAY = os.getenv("DISPLAY", ":10")
XAUTHORITY = os.getenv("XAUTHORITY", "/home/trader/.Xauthority")
# Window title substrings that identify the MT5 terminal (account + server).
WIN_MATCH = os.getenv("MT5_WINDOW_MATCH", "MetaTrader|MetaQuotes|Exness|Demo Account")
STATE_DIR = Path(os.getenv("LOG_ROOT", "logs")) / "autotrading_guard"
TOPIC = os.getenv("AUTOTRADING_GUARD_TOPIC", "tv_status")

# Hung-terminal recovery: when the bridge reports MT5 down (status != "ok",
# e.g. "IPC send failed") for several consecutive cycles, the wine terminal is
# stuck and the bridge can't re-initialise against it — so we kill + relaunch it.
# This is the root-cause fix for the 2026-06-02 outage, where a hung terminal
# left every agent unable to reconnect.
WINE_BIN = os.getenv("WINE_BIN", "/opt/wine-staging/bin/wine")
WINEPREFIX = os.getenv("WINEPREFIX", "/home/trader/.wine")
TERMINAL_EXE = os.getenv("MT5_TERMINAL_EXE", r"C:\Program Files\MetaTrader 5\terminal64.exe")
TERM_RESTART_AFTER = int(os.getenv("MT5_TERM_RESTART_AFTER", "4"))   # consecutive down cycles
TERM_RESTART_COOLDOWN = int(os.getenv("MT5_TERM_RESTART_COOLDOWN", "600"))  # min secs between restarts

_down_streak = 0
_last_term_restart = 0.0


def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from . import telegram_hq
        telegram_hq.send(TOPIC, f"⚙️ AutoTrading: {msg}", level=level)
    except Exception:
        log.info("notify (%s): %s", level, msg)


def _xenv() -> dict:
    e = dict(os.environ)
    e["DISPLAY"] = DISPLAY
    e["XAUTHORITY"] = XAUTHORITY
    return e


def _find_mt5_window() -> str | None:
    try:
        ids = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", "."],
            capture_output=True, text=True, env=_xenv(), timeout=15,
        ).stdout.split()
    except Exception as e:
        log.warning("xdotool search failed: %s", e)
        return None
    import re
    pat = re.compile(WIN_MATCH, re.I)
    for wid in ids:
        try:
            name = subprocess.run(["xdotool", "getwindowname", wid],
                                  capture_output=True, text=True,
                                  env=_xenv(), timeout=5).stdout.strip()
        except Exception:
            continue
        if name and pat.search(name):
            return wid
    return None


def _enable_autotrading() -> bool:
    wid = _find_mt5_window()
    if not wid:
        log.warning("MT5 window not found — cannot toggle Algo Trading")
        return False
    try:
        subprocess.run(["xdotool", "windowactivate", "--sync", wid],
                       env=_xenv(), timeout=10)
        time.sleep(1)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "--window", wid, "ctrl+e"],
                       env=_xenv(), timeout=10)
        log.info("sent Ctrl+E to MT5 window %s", wid)
        return True
    except Exception as e:
        log.warning("xdotool toggle failed: %s", e)
        return False


def _health() -> dict | None:
    """Full bridge /health dict, or None if the bridge itself is unreachable
    (that case is the orchestrator's job — it restarts the bridge process)."""
    try:
        r = requests.get(f"{BRIDGE}/health", timeout=10)
        return r.json()
    except Exception as e:
        log.warning("health check failed: %s", e)
        return None


def _restart_terminal() -> bool:
    """Kill a hung wine MT5 terminal and relaunch it. The bridge's _ensure_mt5
    re-initialises against the fresh terminal on its next call (auto-login is
    saved in the terminal profile)."""
    env = _xenv()
    env["WINEPREFIX"] = WINEPREFIX
    try:
        subprocess.run(["pkill", "-9", "-f", "terminal64.exe"],
                       env=env, capture_output=True, timeout=15)
    except Exception as e:
        log.warning("pkill terminal64 failed: %s", e)
    time.sleep(5)
    try:
        subprocess.Popen([WINE_BIN, TERMINAL_EXE, "/portable"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        log.info("relaunched MT5 terminal under wine")
        return True
    except Exception as e:
        log.error("relaunch terminal failed: %s", e)
        return False


def run_once() -> dict:
    global _down_streak, _last_term_restart
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    h = _health()
    status = h.get("status") if isinstance(h, dict) else None

    # Bridge reachable but MT5 link is down (hung terminal / IPC drop). The
    # orchestrator can't see this (the /health HTTP call still returns 200), so
    # recover the terminal here after it stays down for a few cycles.
    if status is not None and status != "ok":
        _down_streak += 1
        log.warning("MT5 link down (status=%s) streak=%d/%d",
                    status, _down_streak, TERM_RESTART_AFTER)
        action = "mt5_down"
        if _down_streak >= TERM_RESTART_AFTER and (time.time() - _last_term_restart) > TERM_RESTART_COOLDOWN:
            _notify(f"MT5 link down {_down_streak}× (status={status}) — restarting terminal", "ERROR")
            if _restart_terminal():
                _last_term_restart = time.time()
                _down_streak = 0
                action = "terminal_restarted"
            else:
                action = "terminal_restart_failed"
        state = {"ts": now, "trade_allowed": None, "mt5_status": status,
                 "down_streak": _down_streak, "action": action, "running": True}
        try:
            (STATE_DIR / "_state.json").write_text(__import__("json").dumps(state))
        except Exception:
            pass
        return state
    _down_streak = 0

    ta = h.get("trade_allowed") if isinstance(h, dict) else None
    action = "ok"
    if ta is False:
        log.warning("Algo Trading is OFF — re-enabling")
        # Toggle, wait, re-check. A single Ctrl+E flips OFF→ON.
        if _enable_autotrading():
            time.sleep(4)
            h2 = _health()
            if isinstance(h2, dict) and h2.get("trade_allowed"):
                action = "re-enabled"
                _notify("Algo Trading was OFF — re-enabled ✅", "WARNING")
            else:
                action = "toggle_failed"
                _notify("Algo Trading OFF — Ctrl+E did not re-enable it; needs manual check", "ERROR")
        else:
            action = "window_not_found"
    elif ta is None:
        action = "unknown"
    state = {"ts": now, "trade_allowed": ta, "action": action, "running": True}
    try:
        (STATE_DIR / "_state.json").write_text(__import__("json").dumps(state))
    except Exception:
        pass
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=60.0)
    args = ap.parse_args()
    if args.loop:
        log.info("AutoTrading guard loop — every %.0fs", args.interval)
        while True:
            try:
                st = run_once()
                if st["action"] != "ok":
                    log.info("guard: %s", st)
            except Exception:
                log.exception("guard cycle failed")
            time.sleep(args.interval)
    else:
        print(run_once())


if __name__ == "__main__":
    main()
