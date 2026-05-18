import asyncio
import json
import logging
from typing import Optional
from fastapi import WebSocket

log = logging.getLogger("ws_manager")


class WebSocketManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        try:
            await ws.send_text(json.dumps({
                "type": "connected",
                "data": {"server_time": _now_iso()}
            }))
        except Exception:
            pass

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    async def broadcast(self, message: dict):
        if not self._connections:
            return
        payload = json.dumps(message, default=str)
        dead = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    def broadcast_sync(self, message: dict):
        """Thread-safe broadcast from non-async threads (StatePoller, LogTailer)."""
        if self._loop is None or not self._connections:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


manager = WebSocketManager()
