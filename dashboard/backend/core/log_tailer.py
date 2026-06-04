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

# Alert hygiene — don't page CRITICAL for a self-healing blip.
# The bridge (wine api_server) exits occasionally and the orchestrator restarts
# it within ~15-30s; during that window traders log connection ERRORs that
# resolve on their own. Those are "transient": we only page if they're STILL
# erroring past a grace window, and only as WARNING. Hard errors page at once.
_TRANSIENT_RE = re.compile(
    r"HTTPConnectionPool|Connection refused|Max retries|NewConnectionError|"
    r"MT5 init failed|MT5 disconnected|reconnect", re.I)
ALERT_COOLDOWN_SEC   = 900   # same error won't re-page within 15 min
TRANSIENT_GRACE_SEC  = 120   # a transient error must persist this long to page
TRANSIENT_RESET_SEC  = 600   # silence this long → treat the next sighting as new


class LogTailer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="LogTailer")
        self._stop  = threading.Event()
        self._lock  = threading.Lock()
        self._buf: deque = deque(maxlen=LOG_TAIL_LINES)
        self._pos   = 0
        self._alert_state: dict = {}   # signature -> timing/debounce state

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
            if entry["level"] == "ERROR":
                self._maybe_alert(entry["message"])

    def _maybe_alert(self, msg: str):
        """Page Telegram on real, persistent errors — not self-healing blips."""
        # Normalize volatile bits (numbers, hex) so repeats of the same error
        # collapse to one signature for debouncing.
        sig = re.sub(r"[0-9a-fx]+", "#", msg)[:120]
        now = time.time()
        st  = self._alert_state.get(sig)
        transient = bool(_TRANSIENT_RE.search(msg))

        if transient:
            # Stale sighting → start fresh. First sighting of a new blip stays
            # silent; the orchestrator restarts the bridge and it self-heals.
            if st is None or now - st.get("last_seen", 0) > TRANSIENT_RESET_SEC:
                self._alert_state[sig] = {"first": now, "last_seen": now, "sent": False}
                return
            st["last_seen"] = now
            # Still erroring past the grace window → not self-healing, page once.
            if not st.get("sent") and now - st["first"] >= TRANSIENT_GRACE_SEC:
                st["sent"] = True
                self._send(msg, "WARNING", "Live Trader (bridge unstable)")
            return

        # Hard error — page immediately, then cooldown repeats.
        if st and now - st.get("last_sent", 0) < ALERT_COOLDOWN_SEC:
            return
        self._alert_state[sig] = {"last_sent": now}
        self._send(msg, "CRITICAL", "Live Trader Error")

    def _send(self, msg: str, level: str, title: str):
        try:
            from .notifier import send
            send("live_trading", f"`{msg[:300]}`", level=level, title=title)
        except Exception as e:
            log.debug(f"hq notify error: {e}")

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
