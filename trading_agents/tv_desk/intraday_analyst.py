"""Intraday Analyst — once/day TradingView day-trade plan for the 7 favorites.

Runs at NY-close (configurable BD hour). For each symbol it reads D1(bias)+H4+H1
+M15 from TradingView, builds the institutional structure, synthesizes 3 INTRADAY
day-trade entries (1:2 & 1:3, open+close within the day), marks the chart, and
publishes to the dashboard + Telegram.

  python -m trading_agents.tv_desk.intraday_analyst --once
  python -m trading_agents.tv_desk.intraday_analyst --loop
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from . import config, _common, store, tracker, news
from .tv_client import TVClient, TVLock, TVError
from . import tv_layout

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s")
log = logging.getLogger("tv_desk.intraday")

MODE = "intraday"
AGENT_DIR = config.INTRADAY_DIR


def run_once(symbols: list[dict] | None = None) -> dict:
    symbols = symbols or config.SYMBOLS
    store.write_state(AGENT_DIR, {"running": True, "idle": False,
                                  "phase": "starting", "mode": MODE})
    results, errors = [], []
    with TVLock():
        tv = TVClient()
        try:
            if not tv_layout.ensure_connected(tv):
                msg = "TradingView not reachable (CDP). Skipping run."
                log.error(msg)
                store.write_state(AGENT_DIR, {"running": True, "idle": True,
                                              "error": msg, "mode": MODE})
                _alert(msg)
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
                                            topic=config.TOPIC_INTRADAY)
                    results.append({"symbol": ev["symbol"], "entries": len(ev["entries"])})
                    store.write_state(AGENT_DIR, {
                        "running": True, "idle": False, "mode": MODE,
                        "phase": f"done {ev['symbol']}",
                        "last_results": results,
                        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    log.exception("symbol failed: %s", sym.get("tv"))
                    errors.append({"symbol": sym.get("base"), "error": str(e)[:200]})
        finally:
            tv.close()

    store.write_state(AGENT_DIR, {
        "running": True, "idle": True, "mode": MODE,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_results": results, "errors": errors,
        "symbols": [s["base"] for s in symbols],
    })
    log.info("intraday run complete: %d ok, %d errors", len(results), len(errors))
    return {"ok": True, "results": results, "errors": errors}


def _alert(msg: str):
    try:
        from .. import telegram_hq
        telegram_hq.send(config.TOPIC_INTRADAY, f"⚠️ Intraday Analyst: {msg}", level="WARNING")
    except Exception:
        pass


def loop():
    base_state = {"mode": MODE, "symbols": [s["base"] for s in config.SYMBOLS]}
    while True:
        target = _common.next_daily_bd(config.ANALYST_RUN_BD_HOUR)
        log.info("next intraday run at %s UTC (%02d:00 BD)",
                 target.isoformat(timespec="minutes"), config.ANALYST_RUN_BD_HOUR)
        _common.sleep_until(target, heartbeat_dir=AGENT_DIR, heartbeat_state=base_state)
        try:
            run_once()
        except Exception:
            log.exception("intraday run_once crashed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single pass and exit")
    ap.add_argument("--loop", action="store_true", help="run forever on the daily schedule")
    ap.add_argument("--symbol", action="append", help="restrict to base symbol(s), e.g. BTCUSD")
    args = ap.parse_args()

    syms = config.SYMBOLS
    if args.symbol:
        want = {s.upper() for s in args.symbol}
        syms = [s for s in config.SYMBOLS if s["base"].upper() in want] or config.SYMBOLS

    if args.loop:
        loop()
    else:
        run_once(syms)


if __name__ == "__main__":
    main()
