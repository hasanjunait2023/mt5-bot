"""store — per-agent persistence (state + events + chart PNGs).

Mirrors the dashboard wiring convention used by signals/alpha/scalp:
  logs/<agent>/_state.json     live snapshot
  logs/<agent>/_events.jsonl   append-only analysis log
  logs/<agent>/charts/<id>.png annotated TradingView screenshots
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("tv_desk.store")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure(agent_dir: Path) -> None:
    (agent_dir / "charts").mkdir(parents=True, exist_ok=True)


def write_state(agent_dir: Path, state: dict) -> None:
    ensure(agent_dir)
    state = {**state, "updated_at": _now()}
    tmp = agent_dir / "_state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(agent_dir / "_state.json")


def append_event(agent_dir: Path, event: dict) -> None:
    ensure(agent_dir)
    event = {**event, "logged_at": _now()}
    with (agent_dir / "_events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def save_chart(agent_dir: Path, event_id: str, png_bytes: bytes) -> str:
    ensure(agent_dir)
    safe = "".join(c for c in event_id if c.isalnum() or c in "-_")
    f = agent_dir / "charts" / f"{safe}.png"
    f.write_bytes(png_bytes)
    # relative path from project root for the dashboard
    root = agent_dir.parents[1]
    return str(f.relative_to(root)).replace("\\", "/")
