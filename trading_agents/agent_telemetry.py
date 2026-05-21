"""
Per-call agent telemetry — append-only JSONL the dashboard reads.

Every resilient LLM call records: agent label, model/backend that served it,
whether it was a Claude→NVIDIA fallback, latency, ok/error. This is how you
see degradation (fallback rate climbing, latencies rising) BEFORE something
fails loudly. Fail-silent by design — telemetry must never break an agent.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("AgentTelemetry")

BASE_DIR = Path(__file__).resolve().parent.parent
METRICS_FILE = BASE_DIR / "logs" / "agent_metrics.jsonl"
_MAX_LINES = 5000  # rotate so the file can't grow unbounded
_lock = threading.Lock()


def record(agent: str, *, model: str, backend: str, latency_ms: int,
           ok: bool, error: str | None = None) -> None:
    """
    Append one telemetry event. `backend` is "claude" or "nvidia" (which
    actually served the call); `model` is the concrete model id.
    Never raises.
    """
    try:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "model": model,
            "backend": backend,          # claude | nvidia
            "latency_ms": int(latency_ms),
            "ok": bool(ok),
            "error": (error or "")[:300],
        }
        with _lock:
            METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with METRICS_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            _maybe_rotate()
    except Exception as e:  # telemetry is best-effort, never fatal
        log.debug("telemetry record failed: %s", e)


def _maybe_rotate() -> None:
    """Trim the file to the last _MAX_LINES lines (cheap, infrequent)."""
    try:
        if not METRICS_FILE.exists():
            return
        # only do the (slightly costly) line count occasionally
        if int(time.time()) % 50 != 0:
            return
        lines = METRICS_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > _MAX_LINES:
            keep = "\n".join(lines[-_MAX_LINES:]) + "\n"
            METRICS_FILE.write_text(keep, encoding="utf-8")
    except Exception:
        pass
