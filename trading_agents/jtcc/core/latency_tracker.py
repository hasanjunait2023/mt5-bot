"""Latency tracker — context manager to time L1/L2/L3 calls and aggregate stats.
Writes p50/p95/p99 to _jtcc_latency.json which dashboard reads."""

from __future__ import annotations

import json
import statistics
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent.parent
LATENCY_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_latency.json"
MAX_SAMPLES = 500  # rolling window


class LatencyTracker:
    def __init__(self) -> None:
        self._samples: dict[str, deque[float]] = {}
        self._errors: dict[str, int] = {}
        self._calls: dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_save = 0.0

    @contextmanager
    def measure(self, label: str):
        """Use as: with tracker.measure('l1_momentum'): ..."""
        t0 = time.perf_counter()
        had_error = False
        try:
            yield
        except Exception:
            had_error = True
            raise
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            with self._lock:
                if label not in self._samples:
                    self._samples[label] = deque(maxlen=MAX_SAMPLES)
                    self._errors[label] = 0
                    self._calls[label] = 0
                self._samples[label].append(elapsed_ms)
                self._calls[label] += 1
                if had_error:
                    self._errors[label] += 1
            # auto-save every 30s
            if time.time() - self._last_save > 30:
                self._last_save = time.time()
                self.save()

    def record_error(self, label: str) -> None:
        with self._lock:
            self._errors[label] = self._errors.get(label, 0) + 1
            self._calls[label] = self._calls.get(label, 0) + 1

    def record_call(self, label: str) -> None:
        with self._lock:
            self._calls[label] = self._calls.get(label, 0) + 1

    def stats(self) -> dict:
        with self._lock:
            result = {}
            for label, samples in self._samples.items():
                if not samples:
                    continue
                vals = list(samples)
                vals.sort()
                p50 = statistics.median(vals)
                p95 = vals[int(len(vals) * 0.95)] if len(vals) > 1 else vals[0]
                p99 = vals[int(len(vals) * 0.99)] if len(vals) > 1 else vals[0]
                calls = self._calls.get(label, 0)
                errors = self._errors.get(label, 0)
                error_rate = round(errors / calls * 100, 2) if calls > 0 else 0
                result[label] = {
                    "samples": len(vals),
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "p99_ms": round(p99, 2),
                    "mean_ms": round(statistics.mean(vals), 2),
                    "max_ms": round(max(vals), 2),
                    "calls": calls,
                    "errors": errors,
                    "error_rate_pct": error_rate,
                }
            return result

    def save(self) -> None:
        try:
            LATENCY_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"updated_at": time.time(), "stats": self.stats()}
            LATENCY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._errors.clear()
            self._calls.clear()


# Global singleton
tracker = LatencyTracker()
