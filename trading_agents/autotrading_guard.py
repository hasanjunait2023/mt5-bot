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


def _trade_allowed() -> bool | None:
    try:
        r = requests.get(f"{BRIDGE}/health", timeout=10)
        if r.status_code >= 400:
            return None
        return r.json().get("trade_allowed")
    except Exception as e:
        log.warning("health check failed: %s", e)
        return None


def run_once() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ta = _trade_allowed()
    now = datetime.now(timezone.utc).isoformat()
    action = "ok"
    if ta is False:
        log.warning("Algo Trading is OFF — re-enabling")
        # Toggle, wait, re-check. A single Ctrl+E flips OFF→ON.
        if _enable_autotrading():
            time.sleep(4)
            if _trade_allowed():
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
