"""
Claude Code Console runner — drives the Claude Agent SDK headlessly inside the
live repo and streams typed events to a callback (the WebSocket forwards them to
the browser).

Design:
  • cwd = repo root, permission_mode = bypassPermissions (full autonomous, per the
    approved plan). A short system-prompt append reminds Claude it is the LIVE
    trading VPS.
  • Sessions use the SDK's native on-disk store (list_sessions / get_session_messages
    / resume=session_id) so a chat resumes from any device/browser.
  • A bounded semaphore caps concurrent turns so heavy runs don't starve the
    trading stack (the box is RAM-tight).
  • Every turn + tool call is appended to logs/console/audit.jsonl.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("console.runner")

REPO_DIR = Path(__file__).resolve().parents[3]          # .../mt5-bot
AUDIT_DIR = REPO_DIR / "logs" / "console"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_PATH = AUDIT_DIR / "audit.jsonl"

MAX_CONCURRENT = int(os.getenv("CONSOLE_MAX_CONCURRENT", "2"))
_sem = asyncio.Semaphore(MAX_CONCURRENT)

LIVE_NOTE = (
    "You are running on the user's LIVE trading VPS (the mt5-bot repo), driving 20+ "
    "running trading services and a live MT5 demo account. Be careful with anything "
    "that restarts services, edits live agent code, or touches the bridge/orchestrator. "
    "Read docs/OPS_RUNBOOK.md before operational changes."
)

Sender = Callable[[dict], Awaitable[None]]


def _sdk():
    """Import the SDK lazily so this module loads on machines without it installed."""
    import claude_agent_sdk as sdk
    return sdk


def sdk_available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except Exception:
        return False


def _audit(event: dict) -> None:
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **event}, default=str) + "\n")
    except Exception:
        pass


def _options(sdk, session_id: str | None):
    return sdk.ClaudeAgentOptions(
        cwd=str(REPO_DIR),
        permission_mode="bypassPermissions",
        resume=session_id or None,
        include_partial_messages=False,
        system_prompt={"type": "preset", "preset": "claude_code", "append": LIVE_NOTE},
        setting_sources=["user", "project", "local"],
    )


def _block_events(msg, sdk) -> list[dict]:
    """Map one SDK message to a list of wire events."""
    out: list[dict] = []
    cls = type(msg).__name__
    if cls == "AssistantMessage":
        for b in getattr(msg, "content", []) or []:
            bt = type(b).__name__
            if bt == "TextBlock":
                out.append({"type": "assistant", "text": getattr(b, "text", "")})
            elif bt == "ThinkingBlock":
                out.append({"type": "thinking", "text": getattr(b, "thinking", "") or getattr(b, "text", "")})
            elif bt == "ToolUseBlock":
                out.append({"type": "tool_use", "id": getattr(b, "id", ""),
                            "name": getattr(b, "name", ""), "input": getattr(b, "input", {})})
    elif cls == "UserMessage":
        for b in getattr(msg, "content", []) or []:
            if type(b).__name__ == "ToolResultBlock":
                content = getattr(b, "content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        (c.get("text", "") if isinstance(c, dict) else str(c)) for c in content
                    )
                out.append({"type": "tool_result", "tool_use_id": getattr(b, "tool_use_id", ""),
                            "content": str(content)[:8000], "is_error": bool(getattr(b, "is_error", False))})
    elif cls == "SystemMessage":
        data = getattr(msg, "data", {}) or {}
        out.append({"type": "system", "subtype": getattr(msg, "subtype", ""),
                    "session_id": data.get("session_id")})
    elif cls == "ResultMessage":
        out.append({"type": "result", "session_id": getattr(msg, "session_id", None),
                    "is_error": bool(getattr(msg, "is_error", False)),
                    "cost_usd": getattr(msg, "total_cost_usd", None),
                    "result": getattr(msg, "result", None)})
    return out


async def run_turn(prompt: str, session_id: str | None, send: Sender, holder: dict) -> str | None:
    """Run one console turn. Streams events via `send`. `holder['client']` is set so
    the caller can interrupt(). Returns the (new) session_id."""
    sdk = _sdk()
    new_session = session_id
    _audit({"event": "turn_start", "session_id": session_id, "prompt": prompt[:2000]})
    async with _sem:
        client = sdk.ClaudeSDKClient(_options(sdk, session_id))
        await client.connect()
        holder["client"] = client
        try:
            await client.query(prompt)
            async for msg in client.receive_response():
                for ev in _block_events(msg, sdk):
                    if ev.get("type") == "system" and ev.get("session_id"):
                        new_session = ev["session_id"]
                    if ev.get("type") == "result" and ev.get("session_id"):
                        new_session = ev["session_id"]
                    if ev["type"] in ("tool_use", "result"):
                        _audit(ev)
                    await send(ev)
        finally:
            holder.pop("client", None)
            try:
                await client.disconnect()
            except Exception:
                pass
    _audit({"event": "turn_end", "session_id": new_session})
    return new_session


# ── Session management (native SDK store) ───────────────────────────────────
def list_console_sessions(limit: int = 50) -> list[dict]:
    sdk = _sdk()
    try:
        infos = sdk.list_sessions(str(REPO_DIR), limit=limit)
    except Exception as e:
        log.warning("list_sessions failed: %s", e)
        return []
    out = []
    for s in infos:
        out.append({
            "session_id": getattr(s, "session_id", None) or getattr(s, "id", None),
            "title": (getattr(s, "summary", None) or getattr(s, "title", None)
                      or getattr(s, "first_message", None) or "Untitled"),
            "updated_at": getattr(s, "updated_at", None) or getattr(s, "modified_at", None),
            "message_count": getattr(s, "message_count", None),
        })
    return [s for s in out if s["session_id"]]


def session_history(session_id: str) -> list[dict]:
    """Replay a session's transcript as wire events for the UI."""
    sdk = _sdk()
    try:
        msgs = sdk.get_session_messages(session_id, str(REPO_DIR))
    except TypeError:
        msgs = sdk.get_session_messages(session_id)
    except Exception as e:
        log.warning("get_session_messages failed: %s", e)
        return []
    events: list[dict] = []
    for m in msgs:
        # stored messages may be SDK message objects OR raw dicts
        if hasattr(m, "content") or type(m).__name__.endswith("Message"):
            events.extend(_block_events(m, sdk))
        elif isinstance(m, dict):
            role = m.get("role")
            if role == "user" and isinstance(m.get("content"), str):
                events.append({"type": "user", "text": m["content"]})
    return events


def rename(session_id: str, title: str) -> bool:
    sdk = _sdk()
    try:
        sdk.rename_session(session_id, title, str(REPO_DIR))
        return True
    except Exception as e:
        log.warning("rename_session failed: %s", e)
        return False


def delete(session_id: str) -> bool:
    sdk = _sdk()
    try:
        sdk.delete_session(session_id, str(REPO_DIR))
        return True
    except Exception as e:
        log.warning("delete_session failed: %s", e)
        return False
