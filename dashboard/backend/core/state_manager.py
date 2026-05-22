import json
import logging
import threading
import time
import os
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    LIVE_STATE_PATH, KNOWLEDGE_BASE, PERF_LOG, SYSTEM_CONFIG,
    POLL_INTERVAL, MAX_EQUITY_HIST, STALE_SECONDS,
)
from .ws_manager import manager as ws_manager

log = logging.getLogger("state_manager")

_OFFLINE_STATE = {
    "trader_running": False,
    "mt5_connected": False,
    "account": {
        "login": 0, "server": "—", "balance": 0.0, "equity": 0.0,
        "margin": 0.0, "free_margin": 0.0, "daily_pnl": 0.0,
        "daily_dd_pct": 0.0, "total_dd_pct": 0.0, "start_balance": 0.0,
    },
    "positions": [],
    "daily_trades": {},
    "last_signals": {},
    "symbols": [],
}


class StatePoller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="StatePoller")
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state: dict = deepcopy(_OFFLINE_STATE)
        self._equity_history: deque = deque(maxlen=MAX_EQUITY_HIST)
        self._knowledge_base: dict = {}
        self._perf_log: dict = {}
        self._sys_config: dict = {}
        self._alerted: set = set()      # rising-edge debounce for HQ alerts
        self._stale_streak: int = 0     # consecutive stale/disconnected polls
        self._last_good_cfg: dict = {}  # cached config so intermittent read failures don't clear edges

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception as e:
                log.debug(f"poll error: {e}")
            self._stop.wait(POLL_INTERVAL)

    def _poll(self):
        state = self._read_live_state()
        kb    = self._read_json(KNOWLEDGE_BASE)
        pl    = self._read_json(PERF_LOG)
        cfg   = self._read_json(SYSTEM_CONFIG)

        if state.get("mt5_connected") and state.get("account"):
            eq = state["account"].get("equity", 0.0)
            self._equity_history.append({
                "t": _now_iso(),
                "equity": eq,
            })

        agents = self._build_agents(kb, pl)

        payload = {
            **state,
            "equity_history": list(self._equity_history)[-120:],
            "agents": agents,
        }

        prev = self._state
        with self._lock:
            self._state = payload
            self._knowledge_base = kb
            self._perf_log = pl
            self._sys_config = cfg

        try:
            self._check_alerts(prev, payload, cfg)
        except Exception as e:
            log.debug(f"alert check error: {e}")

        ws_manager.broadcast_sync({"type": "state", "data": payload})

    def _check_alerts(self, prev: dict, new: dict, cfg: dict):
        """Push live-trading transitions to the Telegram HQ once per edge."""
        from .notifier import send

        # Cache config — intermittent read failures must not clear edge state
        if cfg:
            self._last_good_cfg = cfg

        def edge(key: str, active: bool, msg: str, level: str):
            if active and key not in self._alerted:
                self._alerted.add(key)
                send("live_trading", msg, level=level, title="Live Trading")
            elif not active:
                self._alerted.discard(key)

        # Trader went offline (was running, now not / stale)
        edge("trader_offline",
             prev.get("trader_running") and not new.get("trader_running"),
             "🔌 Live trader is *offline* (state stale or stopped).", "WARNING")

        # MT5 link dropped — require 2 consecutive down polls to avoid false
        # alarms from a single stale read during DD-branch sleep
        if not new.get("mt5_connected"):
            self._stale_streak += 1
        else:
            self._stale_streak = 0
            self._alerted.discard("mt5_down")   # auto-clear when back online

        if self._stale_streak >= 2 and "mt5_down" not in self._alerted:
            self._alerted.add("mt5_down")
            send("live_trading", "❌ MT5 connection *lost*.", level="CRITICAL",
                 title="Live Trading")

        # Daily DD alert removed — live trader sends it directly with a
        # one-shot guard (_daily_dd_alerted flag).  Keeping it here caused
        # double-alerts and cycling whenever cfg read returned {}.

    def _read_live_state(self) -> dict:
        if not LIVE_STATE_PATH.exists():
            return deepcopy(_OFFLINE_STATE)
        try:
            mtime = os.path.getmtime(LIVE_STATE_PATH)
            age   = time.time() - mtime
            raw   = json.loads(LIVE_STATE_PATH.read_text(encoding="utf-8"))
            if age > STALE_SECONDS:
                raw["trader_running"] = False
                raw["mt5_connected"]  = False
            return raw
        except Exception:
            return deepcopy(_OFFLINE_STATE)

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _build_agents(self, kb: dict, pl: dict) -> dict:
        perf_stats = kb.get("performance_stats", {})
        adaptations = pl.get("system_adaptations", [])
        daily_perf  = pl.get("daily_performance", [])

        return {
            "strategy_researcher": {
                "total_strategies": perf_stats.get("total_strategies_tested", 0),
                "successful": perf_stats.get("successful_strategies", 0),
                "failed": perf_stats.get("failed_strategies", 0),
                "last_updated": kb.get("last_updated", None),
                "symbols": list(kb.get("symbols", {}).keys()),
            },
            "performance_optimizer": {
                "total_adaptations": len(adaptations),
                "last_adaptation": adaptations[-1] if adaptations else None,
                "monthly_cycles": len(pl.get("monthly_performance", [])),
            },
            "execution_manager": {
                "daily_records": len(daily_perf),
                "last_day": daily_perf[-1] if daily_perf else None,
            },
        }

    def get_snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def get_equity_history(self, n: int = MAX_EQUITY_HIST) -> list:
        with self._lock:
            return list(self._equity_history)[-n:]

    def get_perf_log(self) -> dict:
        with self._lock:
            return deepcopy(self._perf_log)

    def get_knowledge_base(self) -> dict:
        with self._lock:
            return deepcopy(self._knowledge_base)

    def get_sys_config(self) -> dict:
        with self._lock:
            return deepcopy(self._sys_config)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


poller = StatePoller()
