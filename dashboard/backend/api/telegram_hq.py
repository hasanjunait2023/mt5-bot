"""Telegram HQ dashboard API — view routing, toggle topics, send test pings."""

from fastapi import APIRouter, HTTPException
from typing import Any

from core.notifier import hq

router = APIRouter()


@router.get("/telegram-hq")
def get_hq():
    if hq is None:
        raise HTTPException(503, "Telegram HQ hub unavailable")
    cfg = hq.load_config()
    return {
        "group_chat_id": cfg.get("group_chat_id"),
        "setup_complete": cfg.get("setup_complete", False),
        "mirror_critical": cfg.get("mirror_critical", True),
        "digest": cfg.get("digest", {}),
        "quiet_hours": cfg.get("quiet_hours", {}),
        "categories": cfg.get("categories", {}),
        "outbox": hq.read_outbox(120),
    }


@router.put("/telegram-hq")
def put_hq(body: dict[str, Any]):
    """Update only safe prefs. Never touches thread_id / group_chat_id
    (those are owned by /hq_setup)."""
    if hq is None:
        raise HTTPException(503, "Telegram HQ hub unavailable")
    cfg = hq.load_config()

    if "mirror_critical" in body:
        cfg["mirror_critical"] = bool(body["mirror_critical"])

    if "categories" in body and isinstance(body["categories"], dict):
        for key, patch in body["categories"].items():
            if key in cfg["categories"] and isinstance(patch, dict) and "enabled" in patch:
                cfg["categories"][key]["enabled"] = bool(patch["enabled"])

    if "digest" in body and isinstance(body["digest"], dict):
        d = cfg.setdefault("digest", {})
        if "enabled" in body["digest"]:
            d["enabled"] = bool(body["digest"]["enabled"])
        if "hour_utc" in body["digest"]:
            d["hour_utc"] = max(0, min(23, int(body["digest"]["hour_utc"])))
        if "reminder_hours" in body["digest"]:
            d["reminder_hours"] = max(1, min(48, int(body["digest"]["reminder_hours"])))

    if "quiet_hours" in body and isinstance(body["quiet_hours"], dict):
        q = cfg.setdefault("quiet_hours", {})
        if "enabled" in body["quiet_hours"]:
            q["enabled"] = bool(body["quiet_hours"]["enabled"])
        if "start_utc" in body["quiet_hours"]:
            q["start_utc"] = max(0, min(23, int(body["quiet_hours"]["start_utc"])))
        if "end_utc" in body["quiet_hours"]:
            q["end_utc"] = max(0, min(23, int(body["quiet_hours"]["end_utc"])))

    hq.save_config(cfg)
    return cfg


@router.post("/telegram-hq/test")
def test_send(body: dict[str, Any]):
    if hq is None:
        raise HTTPException(503, "Telegram HQ hub unavailable")
    category = body.get("category", "dev_team")
    ok = hq.send(category,
                 "Test ping from the dashboard. If you see this, routing works.",
                 level="INFO", title="Dashboard Test")
    return {"ok": ok, "category": category}
