"""Session Scalper — 3×/day TradingView scalp plan, ~30 min before each open.

Fires before each session (Asia / London / New York) using the Alpha Desk
DST-aware schedule. Reads prior sessions' data (H1 context + M15/M5) from
TradingView for the 7 favorites and produces 2-3 scalp setups for the UPCOMING
session only, marks the chart, and publishes to the dashboard + Telegram.

  python -m trading_agents.tv_desk.session_scalper --once --session london
  python -m trading_agents.tv_desk.session_scalper --loop
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from . import config, _common, store, tracker, news
from ..alpha_desk import sessions as sess
from .tv_client import TVClient, TVLock
from . import tv_layout

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s")
log = logging.getLogger("tv_desk.scalper")

MODE = "scalp"
AGENT_DIR = config.SCALP_DIR


def run_once(session: str, symbols: list[dict] | None = None) -> dict:
    symbols = symbols or config.SYMBOLS
    topic = config.TOPIC_SCALP.get(session)
    store.write_state(AGENT_DIR, {"running": True, "idle": False, "mode": MODE,
                                  "session": session, "phase": "starting"})
    results, errors = [], []
    with TVLock():
        tv = TVClient()
        try:
            if not tv_layout.ensure_connected(tv):
                msg = "TradingView not reachable (CDP). Skipping scalp run."
                log.error(msg)
                store.write_state(AGENT_DIR, {"running": True, "idle": True,
                                              "mode": MODE, "error": msg})
                return {"ok": False, "error": msg}
            tv_layout.switch_to_automation(tv)
            try:
                tracker.resolve(tv, AGENT_DIR)   # close out prior setups from price
            except Exception:
                log.exception("tracker.resolve failed")
            for sym in symbols:
                nb = news.blackout(sym["base"])
                if nb:
                    log.info("skip %s — news blackout: %s (%s)", sym["base"], nb["title"], nb["at"])
                    errors.append({"symbol": sym["base"], "error": f"news blackout: {nb['title']}"})
                    continue
                try:
                    ev = _common.run_symbol(tv, sym, mode=MODE, agent_dir=AGENT_DIR,
                                            topic=topic, session=session)
                    results.append({"symbol": ev["symbol"], "entries": len(ev["entries"])})
                    store.write_state(AGENT_DIR, {
                        "running": True, "idle": False, "mode": MODE, "session": session,
                        "phase": f"done {ev['symbol']}", "last_results": results,
                        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    log.exception("scalp symbol failed: %s", sym.get("tv"))
                    errors.append({"symbol": sym.get("base"), "error": str(e)[:200]})
        finally:
            tv.close()

    store.write_state(AGENT_DIR, {
        "running": True, "idle": True, "mode": MODE, "session": session,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_results": results, "errors": errors,
        "symbols": [s["base"] for s in symbols],
    })
    log.info("scalp run (%s) complete: %d ok, %d errors", session, len(results), len(errors))
    return {"ok": True, "session": session, "results": results, "errors": errors}


def loop():
    base_state = {"mode": MODE, "symbols": [s["base"] for s in config.SYMBOLS]}
    while True:
        session, brief_at = sess.next_brief()
        log.info("next scalp run: %s session, brief at %s UTC",
                 session, brief_at.isoformat(timespec="minutes"))
        _common.sleep_until(brief_at, heartbeat_dir=AGENT_DIR,
                            heartbeat_state={**base_state, "next_session": session})
        try:
            run_once(session)
        except Exception:
            log.exception("scalp run_once crashed")
        time.sleep(60)   # avoid double-firing within the same brief minute


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--session", choices=["asia", "london", "ny"],
                    help="session to plan for (default: current/next)")
    ap.add_argument("--symbol", action="append")
    args = ap.parse_args()

    syms = config.SYMBOLS
    if args.symbol:
        want = {s.upper() for s in args.symbol}
        syms = [s for s in config.SYMBOLS if s["base"].upper() in want] or config.SYMBOLS

    if args.loop:
        loop()
    else:
        session = args.session
        if not session:
            session, _ = sess.next_brief()
        run_once(session, syms)


if __name__ == "__main__":
    main()
