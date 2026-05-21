"""Signal delivery control — time windows + per-channel on/off.

A single JSON config governs whether a signal of a given category is delivered
(Telegram + dashboard WS) right now. Detection / logging / paper-tracking always
run regardless — this gate only controls *delivery* so the user isn't spammed
outside their chosen hours.

All window times are Bangladesh time (Asia/Dhaka, UTC+6, no DST).

Defaults (user-chosen 2026-05-21):
  Morning  07:00–10:00 BD
  Noon     12:00–15:00 BD
  Evening  18:30–22:00 BD
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR    = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "logs" / "signals" / "_delivery_config.json"
BD_TZ       = ZoneInfo("Asia/Dhaka")

# Canonical channel keys (match telegram_hq categories)
CHANNELS = [
    "signal_alignment", "signal_cross", "signal_touch",   # classic
    "signal_improved",                                     # improved
    "alpha_signal", "alpha_confluence", "alpha_brief",     # alpha desk
]

DEFAULT_CONFIG = {
    "master_enabled": True,
    "windows_mode": True,        # True = restrict to windows; False = 24/5
    "brief_ignores_windows": True,  # session briefs fire at their scheduled time
    "windows": [
        {"id": "morning", "label": "Morning", "start": "07:00", "end": "10:00", "enabled": True},
        {"id": "noon",    "label": "Noon",    "start": "12:00", "end": "15:00", "enabled": True},
        {"id": "evening", "label": "Evening", "start": "18:30", "end": "22:00", "enabled": True},
    ],
    "channels": {c: True for c in CHANNELS},
}

_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime: float = 0.0


# ── persistence ──────────────────────────────────────────────────────────────

def _heal(cfg: dict) -> dict:
    base = json.loads(json.dumps(DEFAULT_CONFIG))   # deep copy
    for k, v in base.items():
        cfg.setdefault(k, v)
    # ensure every channel key exists
    for c in CHANNELS:
        cfg["channels"].setdefault(c, True)
    return cfg


def load_config() -> dict:
    global _cache, _cache_mtime
    with _lock:
        try:
            if CONFIG_PATH.exists():
                mtime = CONFIG_PATH.stat().st_mtime
                if _cache is not None and mtime == _cache_mtime:
                    return _cache
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                cfg = _heal(cfg)
                _cache, _cache_mtime = cfg, mtime
                return cfg
        except Exception:
            pass
        # first run / corrupt → write defaults
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(cfg)
        return cfg


def save_config(cfg: dict) -> dict:
    global _cache, _cache_mtime
    cfg = _heal(cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    with _lock:
        _cache = cfg
        _cache_mtime = CONFIG_PATH.stat().st_mtime
    return cfg


# ── gating ───────────────────────────────────────────────────────────────────

def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _in_active_window(cfg: dict, now_bd: datetime | None = None) -> bool:
    now = (now_bd or datetime.now(BD_TZ)).time()
    enabled = [w for w in cfg.get("windows", []) if w.get("enabled", True)]
    if not enabled:
        return False                 # all windows off → deliver nothing
    for w in enabled:
        try:
            start = _parse_hhmm(w["start"])
            end   = _parse_hhmm(w["end"])
        except Exception:
            continue
        if start <= end:
            if start <= now <= end:
                return True
        else:                        # window crosses midnight
            if now >= start or now <= end:
                return True
    return False


def should_deliver(category: str, now_bd: datetime | None = None) -> bool:
    """Master decision: deliver a signal of `category` (Telegram + WS) now?"""
    cfg = load_config()
    if not cfg.get("master_enabled", True):
        return False
    if not cfg.get("channels", {}).get(category, True):
        return False
    if category == "alpha_brief" and cfg.get("brief_ignores_windows", True):
        return True
    if not cfg.get("windows_mode", True):
        return True                  # no time restriction
    return _in_active_window(cfg, now_bd)


def status() -> dict:
    """Snapshot for the API: config + whether each channel would deliver now."""
    cfg = load_config()
    now_bd = datetime.now(BD_TZ)
    return {
        "config": cfg,
        "now_bd": now_bd.strftime("%H:%M:%S"),
        "in_window": _in_active_window(cfg, now_bd),
        "live": {c: should_deliver(c, now_bd) for c in CHANNELS},
    }
