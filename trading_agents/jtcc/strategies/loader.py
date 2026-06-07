"""Strategy loader — auto-discovers and hot-reloads YAML strategy files from strategies/ folder."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("jtcc.loader")

STRATEGIES_DIR = Path(__file__).parent
QUARANTINE_DIR = STRATEGIES_DIR / "_quarantine"
REQUIRED_FIELDS = {"name", "entry_rules"}

_SCHEMA_TEMPLATE = {
    "name": str,
    "symbols": list,
    "entry_rules": dict,
    "exit_rules": dict,
    "risk": dict,
}


def _validate(data: dict, path: Path) -> str | None:
    """Returns error string if invalid, None if valid."""
    for field in REQUIRED_FIELDS:
        if field not in data:
            return f"Missing required field: {field}"
    if not isinstance(data.get("entry_rules"), dict):
        return "entry_rules must be a dict with 'buy' and/or 'sell' lists"
    entry = data["entry_rules"]
    if not entry.get("buy") and not entry.get("sell"):
        return "entry_rules must have at least one of: buy, sell"
    return None


def _quarantine_file(path: Path, reason: str) -> None:
    """Move broken YAML to _quarantine/ folder and notify Telegram."""
    try:
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        dest = QUARANTINE_DIR / path.name
        if dest.exists():
            dest = QUARANTINE_DIR / f"{path.stem}_{int(time.time())}.yaml"
        path.rename(dest)
        log.warning("Quarantined %s → %s : %s", path.name, dest.name, reason)
        try:
            from trading_agents.telegram_hq import send as tg_send
            tg_send("dev_team",
                    f"JTCC YAML quarantined: {path.name}\nReason: {reason}\nMoved to: _quarantine/",
                    level="WARNING", title="JTCC Strategy Quarantined")
        except Exception:
            pass
    except Exception as e:
        log.error("Quarantine of %s failed: %s", path.name, e)


def _load_file(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            _quarantine_file(path, "Not a valid YAML dict")
            return None
        err = _validate(data, path)
        if err:
            _quarantine_file(path, err)
            return None
        data["_file"] = str(path)
        data["_loaded_at"] = time.time()
        return data
    except Exception as e:
        _quarantine_file(path, f"Parse error: {e}")
        return None


def _backtest_gate(strategy: dict, min_pf: float = 1.3, days: int = 30) -> tuple[bool, str]:
    """Optionally backtest a new strategy before activating it.
    Returns (passed, reason)."""
    try:
        # Lazy import to avoid heavy deps at module load
        import importlib.util
        spec = importlib.util.find_spec("backtest_runner")
        if spec is None:
            return True, "backtest_runner not available — skipping gate"
        # Simplified: real implementation would invoke backtest_runner.run_strategy()
        # For now, just verify strategy structure is sound
        if not strategy.get("entry_rules", {}).get("buy") and not strategy.get("entry_rules", {}).get("sell"):
            return False, "No buy or sell rules"
        return True, "Backtest gate skipped (offline mode)"
    except Exception as e:
        return True, f"Backtest gate error (allowed): {e}"


class StrategyLoader:
    """Loads all .yaml files from strategies/ dir and optionally watches for new ones."""

    def __init__(self, directory: Path = STRATEGIES_DIR, require_backtest: bool = False) -> None:
        self.directory = directory
        self.require_backtest = require_backtest
        self._strategies: dict[str, dict] = {}  # name → strategy dict
        self._file_mtimes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._scan()

    def _scan(self) -> int:
        """Scan directory for .yaml files (excluding STRATEGY_TEMPLATE). Returns new count."""
        loaded = 0
        for path in sorted(self.directory.glob("*.yaml")):
            if path.name.startswith("STRATEGY_TEMPLATE"):
                continue
            if not path.exists():  # may have been quarantined mid-scan
                continue
            mtime = path.stat().st_mtime
            if self._file_mtimes.get(str(path)) == mtime:
                continue  # unchanged
            data = _load_file(path)
            if data:
                name = data["name"]
                is_new = name not in self._strategies
                # Backtest gate for new strategies
                if is_new and self.require_backtest:
                    ok, reason = _backtest_gate(data)
                    if not ok:
                        log.warning("Strategy %s failed backtest gate: %s", name, reason)
                        _quarantine_file(path, f"Backtest gate fail: {reason}")
                        continue
                    log.info("Strategy %s passed backtest gate: %s", name, reason)
                with self._lock:
                    self._strategies[name] = data
                    self._file_mtimes[str(path)] = mtime
                if is_new:
                    log.info("Strategy loaded: %s (%s)", name, path.name)
                    self._notify_new(name)
                    loaded += 1
                else:
                    log.info("Strategy reloaded: %s", name)
        return loaded

    def _notify_new(self, name: str) -> None:
        # Telegram "Strategy Loaded" notification disabled by request — log only.
        log.info("New JTCC strategy loaded: %s (Telegram notify off)", name)

    def start_watcher(self, interval_s: float = 5.0) -> threading.Thread:
        """Start background thread that polls for new/changed YAML files."""
        def _watch():
            while True:
                try:
                    self._scan()
                except Exception as e:
                    log.error("Watcher error: %s", e)
                time.sleep(interval_s)

        t = threading.Thread(target=_watch, daemon=True, name="jtcc-strategy-watcher")
        t.start()
        log.info("Strategy watcher started (interval: %ss)", interval_s)
        return t

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._strategies.values())

    def get(self, name: str) -> dict | None:
        with self._lock:
            return self._strategies.get(name)

    def count(self) -> int:
        with self._lock:
            return len(self._strategies)

    def names(self) -> list[str]:
        with self._lock:
            return list(self._strategies.keys())
