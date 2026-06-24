"""Shared file I/O utilities for the dashboard backend.

Consolidates the duplicated `try: json.loads(path.read_text()) except Exception: return default`
pattern that appears across 20+ API files into a single tested helper.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

log = logging.getLogger("dashboard.file_utils")


def safe_read_json(path: str | Path, default: T = None) -> dict[str, Any] | T:
    """Read a JSON file and return the parsed dict, or *default* on any error.

    Silently returns *default* for missing files, parse errors, and I/O errors
    (all are normal in a multi-process system where agents write state files
    asynchronously). Logs at DEBUG level so the failure is visible when debugging
    but doesn't spam production logs.
    """
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("safe_read_json(%s) failed: %s", path, e)
        return default


def safe_read_jsonl(path: str | Path, n: int = 100) -> list[dict[str, Any]]:
    """Read the last *n* lines of a JSONL file. Returns [] on any error."""
    try:
        p = Path(path)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception as e:
        log.debug("safe_read_jsonl(%s) failed: %s", path, e)
        return []
