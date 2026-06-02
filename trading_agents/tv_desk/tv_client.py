"""TVClient — drive the tradingview-mcp stdio server from Python.

The TradingView MCP server (node) speaks newline-delimited JSON-RPC over
stdin/stdout (same transport scripts/notebooklm_ask.mjs uses). This wraps it:
spawn the server, do the MCP handshake, then call tools synchronously.

Only ONE TradingView desktop exists, so the agents share it via a file lock
(`acquire_tv_lock`) — never two drivers at once.

Tool results come back as MCP `content` blocks whose `text` is the tool's JSON
payload; `call()` parses that and returns the dict the tool itself produced
(e.g. {"success": true, "bars": [...]}).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Optional

from . import config

log = logging.getLogger("tv_desk.client")


class TVError(RuntimeError):
    pass


class TVClient:
    def __init__(self, *, server: str | None = None, node: str | None = None,
                 env: dict | None = None, default_timeout: float = 60.0):
        self.server = server or config.TV_MCP_SERVER
        self.node = node or config.TV_NODE
        self.default_timeout = default_timeout
        self._id = 1
        self._resp: dict[int, dict] = {}
        self._events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

        proc_env = dict(os.environ)
        if env:
            proc_env.update(env)
        if not Path(self.server).exists():
            raise TVError(f"TV MCP server not found: {self.server}")

        self.proc = subprocess.Popen(
            [self.node, self.server],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=proc_env,
        )
        self._stderr_q: Queue[str] = Queue()
        threading.Thread(target=self._reader, daemon=True, name="tv-stdout").start()
        threading.Thread(target=self._drain_stderr, daemon=True, name="tv-stderr").start()
        self._handshake()

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _reader(self):
        for line in self.proc.stdout:                 # blocks until EOF
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mid = msg.get("id")
            if mid is None:
                continue                               # notification — ignore
            with self._lock:
                self._resp[mid] = msg
                ev = self._events.get(mid)
            if ev:
                ev.set()

    def _drain_stderr(self):
        for line in self.proc.stderr:
            self._stderr_q.put(line.rstrip())

    def _send(self, obj: dict):
        if self.proc.poll() is not None:
            raise TVError(f"TV MCP server exited (code {self.proc.returncode})")
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict | None, timeout: float) -> dict:
        with self._lock:
            mid = self._id
            self._id += 1
            ev = threading.Event()
            self._events[mid] = ev
        self._send({"jsonrpc": "2.0", "id": mid, "method": method,
                    "params": params or {}})
        if not ev.wait(timeout):
            raise TVError(f"timeout after {timeout}s on {method}")
        with self._lock:
            msg = self._resp.pop(mid, None)
            self._events.pop(mid, None)
        if msg is None:
            raise TVError(f"no response for {method}")
        if "error" in msg:
            raise TVError(f"{method} error: {msg['error']}")
        return msg.get("result", {})

    def _handshake(self):
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tv-desk", "version": "1.0"},
        }, timeout=20)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)

    # ── public API ───────────────────────────────────────────────────────────
    def call(self, name: str, arguments: dict | None = None,
             timeout: float | None = None) -> Any:
        """Call an MCP tool, return the parsed tool payload (dict/list)."""
        result = self._rpc("tools/call",
                            {"name": name, "arguments": arguments or {}},
                            timeout or self.default_timeout)
        content = result.get("content") or []
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        blob = "\n".join(texts).strip()
        if not blob:
            return result
        try:
            return json.loads(blob)
        except Exception:
            return {"raw": blob, "isError": result.get("isError", False)}

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

    # ── convenience wrappers ─────────────────────────────────────────────────
    def health(self) -> dict:
        return self.call("tv_health_check", timeout=20)

    def launch(self) -> dict:
        return self.call("tv_launch", timeout=90)

    def set_symbol(self, symbol: str) -> dict:
        return self.call("chart_set_symbol", {"symbol": symbol})

    def set_timeframe(self, tf: str) -> dict:
        return self.call("chart_set_timeframe", {"timeframe": tf})

    def get_ohlcv(self, count: int = 200, summary: bool = False) -> dict:
        return self.call("data_get_ohlcv", {"count": count, "summary": summary})

    def draw(self, shape: str, point: dict, point2: dict | None = None,
             text: str | None = None, overrides: dict | None = None) -> dict:
        args: dict[str, Any] = {"shape": shape, "point": point}
        if point2:
            args["point2"] = point2
        if text is not None:
            args["text"] = text
        if overrides is not None:
            args["overrides"] = json.dumps(overrides)
        return self.call("draw_shape", args)

    def clear_drawings(self) -> dict:
        return self.call("draw_clear")

    def set_visible_range(self, frm: int, to: int) -> dict:
        return self.call("chart_set_visible_range", {"from": frm, "to": to})

    def screenshot(self, filename: str, region: str = "chart") -> dict:
        return self.call("capture_screenshot",
                         {"filename": filename, "region": region}, timeout=45)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ── single-instance lock (two agents share one TradingView) ──────────────────
class TVLock:
    """Best-effort cross-process lock via an exclusive lock file."""

    def __init__(self, path: Path | None = None, *, wait: float = 240, poll: float = 2):
        self.path = path or config.TV_LOCK_PATH
        self.wait = wait
        self.poll = poll
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.wait
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self._fd, str(os.getpid()).encode())
                return True
            except FileExistsError:
                # stale lock? remove if older than 20 min.
                try:
                    if time.time() - self.path.stat().st_mtime > 1200:
                        self.path.unlink(missing_ok=True)
                        continue
                except Exception:
                    pass
                if time.time() > deadline:
                    return False
                time.sleep(self.poll)

    def release(self):
        try:
            if self._fd is not None:
                os.close(self._fd)
            self.path.unlink(missing_ok=True)
        except Exception:
            pass

    def __enter__(self):
        if not self.acquire():
            raise TVError("could not acquire TV lock (another agent is driving TradingView)")
        return self

    def __exit__(self, *exc):
        self.release()
