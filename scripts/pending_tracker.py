"""Pending + stalled-work tracker.

One board (PENDING.md) holds two things:

  1. Pending tasks — work deferred on purpose. Curated by hand in the
     "Pending tasks" section of PENDING.md.

  2. Stalled agents — services whose state file has gone stale past its
     configured `max_age (+ grace)` in configs/services.yaml, i.e. the agent's
     work is no longer progressing. Auto-detected and written into the
     "Stalled agents" section (between the STALLED markers).

The freshness rule reuses what the orchestrator already trusts: every working
agent writes a state file every loop, and services.yaml declares how stale that
file may get. If now - mtime(state) > max_age + grace, the agent is stalled.

Usage:
  python scripts/pending_tracker.py --once
  python scripts/pending_tracker.py --loop --interval 300
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

log = logging.getLogger("pending_tracker")

REPO = Path(__file__).resolve().parents[1]
SERVICES = REPO / "configs" / "services.yaml"
PENDING_MD = REPO / "PENDING.md"
STALLED_JSON = REPO / "logs" / "_stalled_agents.json"

STALL_START = "<!-- STALLED:START -->"
STALL_END = "<!-- STALLED:END -->"


# ── Pure logic (unit-tested) ──────────────────────────────────────────────────

def evaluate_stalled(services: list[dict], mtimes: dict[str, float | None],
                     now: float, mode: str = "vps") -> list[dict]:
    """Return the stalled services. Pure: no filesystem access.

    Args:
        services: parsed services.yaml `services` list.
        mtimes:   {state_path: mtime_epoch or None if the file is missing}.
        now:      current epoch seconds.
        mode:     DEPLOYMENT_MODE — only services whose profiles include it are
                  checked (matches the orchestrator's selection).
    """
    stalled: list[dict] = []
    for svc in services:
        profiles = [str(p).lower() for p in svc.get("profiles", ["vps"])]
        if mode not in profiles:
            continue
        health = svc.get("health", {}) or {}
        if health.get("type") != "file":
            continue  # http/tcp/process liveness is the orchestrator's job
        path = health.get("path")
        if not path:
            continue
        max_age = float(health.get("max_age", 0))
        grace = float(health.get("grace", 0))
        threshold = max_age + grace
        mt = mtimes.get(path)
        if mt is None:
            stalled.append({
                "id": svc.get("id"), "name": svc.get("name"), "path": path,
                "age_s": None, "threshold_s": int(threshold),
                "reason": "no state file (never started or never wrote)",
            })
            continue
        age = now - mt
        if age > threshold:
            stalled.append({
                "id": svc.get("id"), "name": svc.get("name"), "path": path,
                "age_s": int(age), "threshold_s": int(threshold),
                "reason": f"state stale {int(age)}s > {int(threshold)}s allowed",
            })
    return stalled


def render_stalled_md(stalled: list[dict], scanned_at: str) -> str:
    if not stalled:
        body = "_No stalled agents. All supervised agents are progressing._"
    else:
        rows = ["| Agent | Why | Stale for | Allowed |",
                "|-------|-----|-----------|---------|"]
        for s in stalled:
            age = "—" if s["age_s"] is None else f"{s['age_s']}s"
            rows.append(f"| `{s['id']}` ({s['name']}) | {s['reason']} | "
                        f"{age} | {s['threshold_s']}s |")
        body = "\n".join(rows)
    return f"{body}\n\n_Last scan: {scanned_at}_"


# ── Filesystem wrapper ────────────────────────────────────────────────────────

def _gather_mtimes(services: list[dict]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for svc in services:
        health = svc.get("health", {}) or {}
        if health.get("type") == "file" and health.get("path"):
            p = REPO / health["path"]
            out[health["path"]] = p.stat().st_mtime if p.exists() else None
    return out


def _update_pending_md(section_md: str) -> None:
    if not PENDING_MD.exists():
        log.warning("PENDING.md missing — skipping board update (JSON still written)")
        return
    text = PENDING_MD.read_text(encoding="utf-8")
    if STALL_START not in text or STALL_END not in text:
        log.warning("STALLED markers missing in PENDING.md — skipping board update")
        return
    pre = text.split(STALL_START)[0]
    post = text.split(STALL_END)[1]
    PENDING_MD.write_text(f"{pre}{STALL_START}\n{section_md}\n{STALL_END}{post}",
                          encoding="utf-8")


def scan_once(mode: str | None = None) -> list[dict]:
    mode = (mode or os.getenv("DEPLOYMENT_MODE", "vps")).strip().lower()
    cfg = yaml.safe_load(SERVICES.read_text(encoding="utf-8")) or {}
    services = cfg.get("services", [])
    mtimes = _gather_mtimes(services)
    now = time.time()
    stalled = evaluate_stalled(services, mtimes, now, mode)

    scanned_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STALLED_JSON.parent.mkdir(parents=True, exist_ok=True)
    STALLED_JSON.write_text(json.dumps(
        {"scanned_at": scanned_at, "mode": mode, "count": len(stalled),
         "stalled": stalled}, indent=2), encoding="utf-8")
    _update_pending_md(render_stalled_md(stalled, scanned_at))

    if stalled:
        log.warning("%d stalled agent(s): %s", len(stalled),
                    ", ".join(s["id"] for s in stalled))
    else:
        log.info("no stalled agents")
    return stalled


def main() -> None:
    ap = argparse.ArgumentParser(description="Pending + stalled-agent tracker")
    ap.add_argument("--once", action="store_true", help="single scan (default)")
    ap.add_argument("--loop", action="store_true", help="run forever")
    ap.add_argument("--interval", type=int, default=300, help="loop seconds")
    ap.add_argument("--mode", default=None, help="DEPLOYMENT_MODE override")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    if args.loop:
        log.info("stalled-agent tracker loop started (interval %ss)", args.interval)
        while True:
            try:
                scan_once(args.mode)
            except Exception as e:  # never let the loop die
                log.error("scan error: %s", e)
            time.sleep(args.interval)
    else:
        scan_once(args.mode)


if __name__ == "__main__":
    main()
