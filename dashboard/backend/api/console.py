"""
Claude Code Console API — browser-driven Claude Code on the live VPS.

Auth is enforced here (IP allowlist + dedicated console token), NOT via the
dashboard's require_auth — see core/console_auth.py. Fail-closed: every route
404s when CONSOLE_PASSWORD is unset.
"""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core import console_auth as ca
from core import console_runner as runner

router = APIRouter()
log = logging.getLogger("console.api")

_CONSOLE_FAILS: dict[str, list[float]] = {}
_CONSOLE_WINDOW_S = 300
_CONSOLE_MAX_FAILS = 5


class LoginBody(BaseModel):
    password: str


class RenameBody(BaseModel):
    title: str


@router.post("/console/login")
def login(body: LoginBody, request: Request):
    ca.guard_ip(request)  # IP gate even on login
    client_ip = (request.client.host if request.client else None) or "unknown"
    now = time.time()
    fails = [t for t in _CONSOLE_FAILS.get(client_ip, []) if now - t < _CONSOLE_WINDOW_S]
    if len(fails) >= _CONSOLE_MAX_FAILS:
        raise HTTPException(status_code=429, detail="Too many attempts — wait a few minutes")
    if not ca.check_password(body.password):
        fails.append(now)
        _CONSOLE_FAILS[client_ip] = fails
        raise HTTPException(status_code=401, detail="Wrong password")
    _CONSOLE_FAILS.pop(client_ip, None)
    return ca.mint_token()


@router.get("/console/status")
def status(request: Request):
    ca.guard_ip(request)
    return {"enabled": True, "sdk": runner.sdk_available(), "cwd": str(runner.REPO_DIR)}


@router.get("/console/sessions", dependencies=[Depends(ca.require_console)])
def sessions():
    return {"sessions": runner.list_console_sessions()}


@router.get("/console/sessions/{session_id}/messages", dependencies=[Depends(ca.require_console)])
def messages(session_id: str):
    return {"events": runner.session_history(session_id)}


@router.post("/console/sessions/{session_id}/rename", dependencies=[Depends(ca.require_console)])
def rename(session_id: str, body: RenameBody):
    return {"ok": runner.rename(session_id, body.title)}


@router.delete("/console/sessions/{session_id}", dependencies=[Depends(ca.require_console)])
def delete(session_id: str):
    return {"ok": runner.delete(session_id)}


@router.websocket("/console/ws")
async def console_ws(ws: WebSocket):
    # IP + token gate (token rides as ?token= since browsers can't set WS headers).
    if not ca.ws_authorized(ws, ws.query_params.get("token")):
        await ws.close(code=4401)
        return
    if not runner.sdk_available():
        await ws.accept()
        await ws.send_json({"type": "error", "message": "claude-agent-sdk not installed on the server"})
        await ws.close()
        return

    await ws.accept()
    holder: dict = {}
    turn_task: asyncio.Task | None = None
    # session_id for THIS chat — client sends it back on every message to continue.
    await ws.send_json({"type": "ready", "cwd": str(runner.REPO_DIR)})

    async def send(ev: dict):
        await ws.send_json(ev)

    async def run(prompt: str, session_id: str | None):
        try:
            new_id = await runner.run_turn(prompt, session_id, send, holder)
            await ws.send_json({"type": "session", "session_id": new_id})
        except asyncio.CancelledError:
            await ws.send_json({"type": "aborted"})
            raise
        except Exception as e:
            log.exception("console turn failed")
            await ws.send_json({"type": "error", "message": str(e)})
        finally:
            await ws.send_json({"type": "turn_end"})

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mtype = msg.get("type")

            if mtype == "user":
                if turn_task and not turn_task.done():
                    await ws.send_json({"type": "error", "message": "A turn is already running"})
                    continue
                prompt = (msg.get("text") or "").strip()
                if not prompt:
                    continue
                turn_task = asyncio.create_task(run(prompt, msg.get("session_id")))

            elif mtype == "stop":
                client = holder.get("client")
                if client:
                    try:
                        await client.interrupt()
                    except Exception as e:
                        log.debug("interrupt failed: %s", e)
                if turn_task and not turn_task.done():
                    turn_task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("console ws error: %s", e)
    finally:
        if turn_task and not turn_task.done():
            turn_task.cancel()
