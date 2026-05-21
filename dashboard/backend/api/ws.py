import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.ws_manager import manager
from core.state_manager import poller
from core.auth import auth_enabled, verify_token

router = APIRouter()
log = logging.getLogger("ws")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Browsers can't set headers on a WebSocket, so the token rides as ?token=
    if auth_enabled() and not verify_token(ws.query_params.get("token")):
        await ws.close(code=4401)  # 4401 = application "unauthorized"
        return
    await manager.connect(ws)
    try:
        snapshot = poller.get_snapshot()
        await ws.send_text(json.dumps({"type": "state", "data": snapshot}, default=str))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "refresh":
                snapshot = poller.get_snapshot()
                await ws.send_text(json.dumps({"type": "state", "data": snapshot}, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug(f"ws error: {e}")
    finally:
        manager.disconnect(ws)
