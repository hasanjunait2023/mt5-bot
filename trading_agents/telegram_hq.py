"""
Telegram HQ — single routing hub for all system notifications.

Every team posts to its own forum *topic* in one Telegram supergroup. This
module is the only place that talks to the Telegram sendMessage API for
notifications; `dev_agents/notifier.py` and the dashboard backend delegate
here. Pure `requests` + `dotenv` — zero heavy deps, safe to import anywhere
(agents, FastAPI backend, the bot).

Setup is automatic: the bot, once admin in the group, runs `ensure_topics()`
(triggered by /hq_setup) which creates every topic via createForumTopic and
persists the chat id + thread map into telegram_hq_config.json.

Env:
  TELEGRAM_BOT_TOKEN      required (reused, already in .env)
  TELEGRAM_GROUP_CHAT_ID  optional override for the supergroup id
  TELEGRAM_CHAT_ID        legacy private-chat fallback
  TELEGRAM_HQ_DRYRUN=1    log to outbox, do not call Telegram (tests)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("TelegramHQ")

BASE_DIR    = Path(__file__).parent.parent          # project root ("mt5 bot/")
CONFIG_PATH = Path(__file__).parent / "telegram_hq_config.json"
OUTBOX_PATH = BASE_DIR / "logs" / "telegram" / "outbox.jsonl"
OUTBOX_MAX  = 500                                    # keep last N lines

API = "https://api.telegram.org/bot{token}/{method}"

Level = Literal["INFO", "WARNING", "CRITICAL"]

LEVEL_EMOJI = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}

# Telegram only accepts these six forum-topic icon colors.
_ICON_COLORS = [7322096, 16766590, 13338331, 9367192, 16749490, 16478047]

# Category key → default topic label. Order = topic creation order.
DEFAULT_CATEGORIES = {
    "ceo":            "🧭 CEO · Maic",
    "live_trading":   "💹 Live Trading",
    "ea_guardian":    "🛡️ EA Guardian",
    "ea_coach":       "🎓 EA Coach · Approvals",
    "ea_validator":   "🧪 EA Validator",
    "dev_team":       "🛠️ Dev Team",
    "strategy_scout": "🔭 Strategy Scout",
    "supervisor":     "🧭 Supervisor",
    "digest":         "📊 Daily Digest · Reminders",
    "critical":       "🚨 Critical Alerts",
    # Signal feeds — multi-TF EMA-200 alignment scanner
    "signal_alignment": "🧭 Signals · 4TF Alignment",
    "signal_cross":     "⚡ Signals · 9/15 Cross",
    "signal_touch":     "🎯 Signals · 200EMA Touch (M3)",
    # Improved signal feed — Phase 1 quality gates + sequence detection
    "signal_improved":  "💎 Signals · IMPROVED (Phase 1)",
    # Alpha Desk — institutional confluence
    "alpha_brief":      "📰 Alpha · Session Briefs",
    "alpha_signal":     "🌊 Alpha · Live Signals",
    "alpha_confluence": "💎 Alpha · CONFLUENCE STACK 🔥🔥",
}

CATEGORIES = list(DEFAULT_CATEGORIES.keys())

_lock = threading.Lock()
_dedupe: dict[str, float] = {}      # "cat|text" -> last sent ts
DEDUPE_SEC = 60                     # drop identical message within this window

# Per-category dedupe overrides. Signal feeds need a much wider window so we
# don't spam Telegram every tick when the same condition stays true.
SIGNAL_DEDUPE_SEC = 900             # 15 min per (symbol, side, signal type)
_SIGNAL_CATS = {"signal_alignment", "signal_cross", "signal_touch", "signal_improved",
                "alpha_brief", "alpha_signal", "alpha_confluence"}


# ───────────────────────── config ─────────────────────────

def _default_config() -> dict:
    return {
        "group_chat_id": None,
        "setup_complete": False,
        "categories": {
            k: {"label": v, "thread_id": None, "enabled": True,
                "icon_color": _ICON_COLORS[i % len(_ICON_COLORS)]}
            for i, (k, v) in enumerate(DEFAULT_CATEGORIES.items())
        },
        "mirror_critical": True,
        "digest": {"enabled": True, "hour_utc": 6, "reminder_hours": 6},
        "quiet_hours": {"enabled": False, "start_utc": 22, "end_utc": 6},
    }


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        cfg = _default_config()
        save_config(cfg)
        return cfg
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = _default_config()
    # Heal missing keys / newly added categories without losing the thread map.
    base = _default_config()
    for k, v in base.items():
        cfg.setdefault(k, v)
    for ck, cv in base["categories"].items():
        cfg["categories"].setdefault(ck, cv)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def _group_chat_id(cfg: dict) -> Optional[str]:
    return (
        os.getenv("TELEGRAM_GROUP_CHAT_ID")
        or cfg.get("group_chat_id")
        or os.getenv("TELEGRAM_CHAT_ID")     # legacy private fallback
    )


def category_for_thread(thread_id: Optional[int]) -> Optional[str]:
    """Reverse-lookup: which category owns this forum topic thread id."""
    cfg = load_config()
    for key, c in cfg.get("categories", {}).items():
        if c.get("thread_id") and int(c["thread_id"]) == int(thread_id or 0):
            return key
    return None


# ───────────────────────── outbox ─────────────────────────

def _append_outbox(entry: dict) -> None:
    try:
        OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if OUTBOX_PATH.exists():
            lines = OUTBOX_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(json.dumps(entry, ensure_ascii=False))
        OUTBOX_PATH.write_text("\n".join(lines[-OUTBOX_MAX:]) + "\n", encoding="utf-8")
    except Exception as e:
        log.debug("outbox write failed: %s", e)


def read_outbox(n: int = 100) -> list[dict]:
    if not OUTBOX_PATH.exists():
        return []
    out: list[dict] = []
    for ln in OUTBOX_PATH.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


# ───────────────────────── telegram api ─────────────────────────

def _token() -> Optional[str]:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _api(method: str, payload: dict) -> dict:
    token = _token()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
    try:
        r = requests.post(API.format(token=token, method=method),
                           json=payload, timeout=15)
        data = r.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", str(data))}
        return {"ok": True, "result": data.get("result")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _send_message(chat_id, text: str, thread_id: Optional[int]) -> dict:
    payload: dict = {"chat_id": chat_id, "text": text,
                     "parse_mode": "Markdown", "disable_web_page_preview": True}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    res = _api("sendMessage", payload)
    if not res["ok"] and "parse" in str(res.get("error", "")).lower():
        # Markdown choked on the body — resend as plain text.
        payload.pop("parse_mode", None)
        res = _api("sendMessage", payload)
    return res


def _send_photo(chat_id, photo_bytes: bytes, caption: str,
                thread_id: Optional[int]) -> dict:
    """Send an image with caption via multipart/form-data (sendPhoto)."""
    token = _token()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
    data: dict = {"chat_id": str(chat_id), "caption": caption,
                  "parse_mode": "Markdown"}
    if thread_id:
        data["message_thread_id"] = str(int(thread_id))
    files = {"photo": ("chart.png", photo_bytes, "image/png")}
    try:
        r = requests.post(API.format(token=token, method="sendPhoto"),
                          data=data, files=files, timeout=30)
        j = r.json()
        if not j.get("ok"):
            # Markdown parse fail → retry plain
            if "parse" in str(j.get("description", "")).lower():
                data.pop("parse_mode", None)
                r = requests.post(API.format(token=token, method="sendPhoto"),
                                  data=data, files=files, timeout=30)
                j = r.json()
            if not j.get("ok"):
                return {"ok": False, "error": j.get("description", str(j))}
        return {"ok": True, "result": j.get("result")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ───────────────────────── public: send ─────────────────────────

def send(category: str,
         message: str,
         level: Level = "INFO",
         title: Optional[str] = None) -> bool:
    """Route a notification to its team's topic. Always records to the outbox."""
    cfg = load_config()
    category = category if category in cfg["categories"] else "dev_team"
    cat = cfg["categories"][category]
    chat_id = _group_chat_id(cfg)
    dryrun = os.getenv("TELEGRAM_HQ_DRYRUN") == "1"

    emoji = LEVEL_EMOJI.get(level, "ℹ️")
    head = title or cat.get("label", category)
    text = f"{emoji} *{head}*\n{message}"

    base_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category, "level": level,
        "title": head, "text": message,
        "thread_id": cat.get("thread_id"),
    }

    with _lock:
        # dedupe identical spam (mainly from log tailer)
        key = f"{category}|{message}"
        now = time.time()
        last = _dedupe.get(key, 0)
        if now - last < DEDUPE_SEC:
            _append_outbox({**base_entry, "ok": False, "skipped": "deduped"})
            return False
        _dedupe[key] = now

    if not cat.get("enabled", True):
        _append_outbox({**base_entry, "ok": False, "skipped": "category_disabled"})
        return False

    if not chat_id:
        _append_outbox({**base_entry, "ok": False, "skipped": "no_chat_id"})
        log.warning("No group chat id — run /hq_setup. Dropped: %s", head)
        return False

    if dryrun:
        _append_outbox({**base_entry, "ok": True, "skipped": "dryrun"})
        return True

    res = _send_message(chat_id, text, cat.get("thread_id"))
    ok = res["ok"]
    _append_outbox({**base_entry, "ok": ok,
                    "message_id": (res.get("result") or {}).get("message_id") if ok else None,
                    "error": None if ok else res.get("error")})

    # Mirror every CRITICAL into the dedicated Critical topic.
    if level == "CRITICAL" and cfg.get("mirror_critical") and category != "critical":
        crit = cfg["categories"].get("critical", {})
        if crit.get("enabled", True) and crit.get("thread_id") is not None:
            mirror = f"🚨 *Critical — {head}*\n{message}"
            mres = _send_message(chat_id, mirror, crit.get("thread_id"))
            _append_outbox({**base_entry, "category": "critical",
                            "title": f"Critical — {head}",
                            "ok": mres["ok"],
                            "error": None if mres["ok"] else mres.get("error")})

    if not ok:
        log.error("Telegram send failed [%s]: %s", category, res.get("error"))
    return ok


def send_photo(category: str,
               photo_bytes: bytes,
               caption: str,
               dedupe_key: Optional[str] = None,
               title: Optional[str] = None) -> bool:
    """Send a photo (chart, etc.) to a category's topic with a Markdown caption.

    `dedupe_key` lets the caller scope dedupe to (symbol, side, kind) rather
    than the whole caption — useful for signal feeds where caption timestamps
    differ but the signal is the same.
    """
    cfg = load_config()
    category = category if category in cfg["categories"] else "dev_team"
    cat = cfg["categories"][category]
    chat_id = _group_chat_id(cfg)
    dryrun = os.getenv("TELEGRAM_HQ_DRYRUN") == "1"

    head = title or cat.get("label", category)
    base_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category, "level": "INFO",
        "title": head, "text": caption[:200],
        "thread_id": cat.get("thread_id"), "kind": "photo",
    }

    with _lock:
        key = f"{category}|{dedupe_key or caption}"
        now = time.time()
        last = _dedupe.get(key, 0)
        window = SIGNAL_DEDUPE_SEC if category in _SIGNAL_CATS else DEDUPE_SEC
        if now - last < window:
            _append_outbox({**base_entry, "ok": False, "skipped": "deduped"})
            return False
        _dedupe[key] = now

    if not cat.get("enabled", True):
        _append_outbox({**base_entry, "ok": False, "skipped": "category_disabled"})
        return False
    if not chat_id:
        _append_outbox({**base_entry, "ok": False, "skipped": "no_chat_id"})
        return False
    if dryrun:
        _append_outbox({**base_entry, "ok": True, "skipped": "dryrun"})
        return True

    res = _send_photo(chat_id, photo_bytes, caption, cat.get("thread_id"))
    ok = res["ok"]
    _append_outbox({**base_entry, "ok": ok,
                    "error": None if ok else res.get("error")})
    if not ok:
        log.error("Telegram send_photo failed [%s]: %s", category, res.get("error"))
    return ok


# ───────────────────────── public: setup ─────────────────────────

def ensure_topics(chat_id) -> dict:
    """Create every missing forum topic in `chat_id` and persist the map.

    Returns {"created": [...], "existing": [...], "errors": [...]}.
    Requires the bot to be an admin with can_manage_topics in a forum group.
    """
    cfg = load_config()
    cfg["group_chat_id"] = str(chat_id)
    created, existing, errors = [], [], []

    for key in CATEGORIES:
        cat = cfg["categories"][key]
        label = cat.get("label", key)
        if cat.get("thread_id"):
            existing.append(label)
            continue
        res = _api("createForumTopic", {
            "chat_id": chat_id,
            "name": label[:128],
            "icon_color": cat.get("icon_color", _ICON_COLORS[0]),
        })
        if res["ok"]:
            tid = res["result"]["message_thread_id"]
            cat["thread_id"] = tid
            created.append(label)
            _api("sendMessage", {
                "chat_id": chat_id, "message_thread_id": tid,
                "text": f"✅ *{label}* is live. This topic now receives "
                        f"`{key}` notifications.",
                "parse_mode": "Markdown",
            })
        else:
            errors.append(f"{label}: {res.get('error')}")

    cfg["setup_complete"] = len(errors) == 0 and not any(
        c.get("thread_id") is None for c in cfg["categories"].values()
    )
    save_config(cfg)
    return {"created": created, "existing": existing, "errors": errors,
            "setup_complete": cfg["setup_complete"]}


if __name__ == "__main__":
    # Smoke test: TELEGRAM_HQ_DRYRUN=1 python -m trading_agents.telegram_hq
    logging.basicConfig(level=logging.INFO)
    for c in CATEGORIES:
        send(c, f"dry-run test for `{c}`", level="INFO")
    send("dev_team", "critical mirror test", level="CRITICAL")
    print(f"Wrote {len(read_outbox(999))} outbox entries -> {OUTBOX_PATH}")
