import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

from .config import LIVE_LOG_PATH, LOG_TAIL_LINES, LOG_TAIL_SEC
from .ws_manager import manager as ws_manager

log = logging.getLogger("log_tailer")

_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(INFO|WARNING|ERROR|DEBUG)\s+(.+)$"
)


class LogTailer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="LogTailer")
        self._stop  = threading.Event()
        self._lock  = threading.Lock()
        self._buf: deque = deque(maxlen=LOG_TAIL_LINES)
        self._pos   = 0

    def stop(self):
        self._stop.set()

    def run(self):
        # Seek to near end of existing file so we don't flood with old lines on startup
        if LIVE_LOG_PATH.exists():
            self._pos = max(0, LIVE_LOG_PATH.stat().st_size - 8192)

        while not self._stop.is_set():
            try:
                self._tail()
            except Exception as e:
                log.debug(f"tail error: {e}")
            self._stop.wait(LOG_TAIL_SEC)

    def _tail(self):
        if not LIVE_LOG_PATH.exists():
            return
        size = LIVE_LOG_PATH.stat().st_size
        if size <= self._pos:
            if size < self._pos:
                self._pos = 0   # file was rotated / truncated
            return

        with open(LIVE_LOG_PATH, "rb") as f:
            f.seek(self._pos)
            chunk = f.read(size - self._pos).decode("utf-8", errors="replace")
            self._pos = size

        for raw_line in chunk.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            entry = self._parse(raw_line)
            with self._lock:
                self._buf.append(entry)
            ws_manager.broadcast_sync({"type": "log", "data": entry})

    def _parse(self, line: str) -> dict:
        m = _LINE_RE.match(line)
        if m:
            ts, level, msg = m.group(1), m.group(2), m.group(3)
            return {"timestamp": ts, "level": level, "message": msg.strip(), "raw": line}
        return {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "level": "INFO",
            "message": line,
            "raw": line,
        }

    def get_recent(self, n: int = 200, level: str | None = None) -> list:
        with self._lock:
            lines = list(self._buf)
        if level:
            lines = [l for l in lines if l["level"] == level.upper()]
        return lines[-n:]


tailer = LogTailer()
