"""
Triage — one-shot health diagnostic for every trading agent.

Answers the core question: "which agent is trading, which isn't, and WHY?"

It reuses the registry (trading_agents/registry) so it always reflects the same
systems the dashboard Hub shows, then layers on two things the Hub can't see:

  1. PROCESS liveness — is the agent's python process actually running right now?
     (the #1 reason agents stop trading is the process died on PC sleep)
  2. A plain-English "why not trading" verdict + the exact command to fix it.

Usage:
    python scripts/triage.py                 # print report
    python scripts/triage.py --json          # machine-readable
    python scripts/triage.py --restart-dead  # relaunch any DEAD registry agent
    python scripts/triage.py --telegram      # also push summary to Telegram HQ
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ── Agent → process pattern + how to (re)launch ────────────────────────────────
# pattern: substring(s) matched against a process command line.
# launch:  command run (cwd = project root) to bring it back up.
AGENT_PROC = {
    "mtf_live":   {"patterns": ["mtf_live_trader"],
                   "launch": ["cmd", "/c", "start", "MTF Trader", "START_LIVE_TRADER.bat"]},
    "jtcc":       {"patterns": ["jtcc.main"],
                   "launch": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "start_jtcc_agents.ps1"]},
    "iconic":     {"patterns": ["trading_agents.iconic.agent"],
                   "launch": ["cmd", "/c", "start", "Iconic Agent", "START_ICONIC_AGENT.bat"]},
    "scalp_gs11": {"patterns": ["trading_agents.scalp.agent"],
                   "launch": ["cmd", "/c", "start", "Scalp Agent", "START_SCALP_AGENT.bat"]},
}

# Infrastructure that the registry doesn't list but the system needs to trade.
INFRA_PROC = {
    "bridge":    {"name": "MT5 Bridge (api_server)",
                  "patterns": ["mt5_bridge.api_server"],
                  "launch": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "start_mt5_bridge.ps1"]},
    "dashboard": {"name": "Dashboard backend (hub/signals/alpha)",
                  "patterns": ["dashboard.backend.main", "uvicorn main:app", "main:app"],
                  "launch": ["cmd", "/c", "start", "Dashboard", "START_DASHBOARD.bat"]},
    "mt5_term":  {"name": "MetaTrader 5 terminal",
                  "patterns": ["terminal64.exe"],
                  "launch": None},
}


# ── Process listing (psutil if present, else PowerShell CIM) ───────────────────
def list_processes() -> list[tuple[int, str]]:
    try:
        import psutil  # type: ignore
        out = []
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cl = " ".join(p.info.get("cmdline") or []) or (p.info.get("name") or "")
                out.append((p.info["pid"], cl))
            except Exception:
                continue
        return out
    except Exception:
        pass
    # Fallback: PowerShell
    ps = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(res.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
        return [(int(d["ProcessId"]), d.get("CommandLine") or d.get("Name") or "")
                for d in data]
    except Exception:
        return []


def find_proc(patterns: list[str], procs: list[tuple[int, str]]) -> int | None:
    for pid, cl in procs:
        low = cl.lower()
        if any(pat.lower() in low for pat in patterns):
            return pid
    return None


# ── State helpers ─────────────────────────────────────────────────────────────
def read_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def age_str(ts_str: str | None) -> str:
    if not ts_str:
        return "—"
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - ts).total_seconds()
        if secs < 90:
            return f"{int(secs)}s"
        if secs < 5400:
            return f"{int(secs/60)}m"
        return f"{secs/3600:.1f}h"
    except Exception:
        return "?"


def diagnose(entry: dict, raw: dict, pid: int | None) -> tuple[str, str]:
    """Return (verdict, action)."""
    alive = pid is not None
    mode = entry.get("mode", "?")
    status = entry.get("status", "?")
    gate = entry.get("paper_gate")
    raw_status = str(raw.get("status", "")).lower()

    if not alive:
        return ("DEAD — process not running", "restart")

    # process alive below
    if entry["health"].get("stale"):
        return ("ALIVE but state STALE — writer stuck / wrong state_file path",
                "investigate state writer")

    if status == "halted":
        return ("HALTED — daily drawdown limit hit", "wait for daily reset / review risk")

    if "off_session" in raw_status or raw.get("off_session"):
        return ("RUNNING — off-session (market/kill-zone closed), no signals", "none — will trade at session open")

    if mode in ("paper", "dry-run") and gate and not gate.get("ready"):
        return (f"PAPER — gate {gate['trades_done']}/{gate['trades_needed']} trades, "
                f"PF {gate['pf_current']:.2f}/{gate['pf_needed']} (not live yet)",
                "let paper trades accumulate")

    if status == "running":
        return ("OK — running", "none")

    return (f"status={status}", "review")


# ── Main ──────────────────────────────────────────────────────────────────────
def build_report() -> dict:
    from trading_agents.registry.manifest import load_all
    from trading_agents.registry.schema import normalize

    procs = list_processes()
    rows = []

    # Registry agents
    for m in load_all():
        try:
            entry = normalize(m, BASE_DIR)
        except Exception as e:
            entry = {"name": m.get("name"), "id": m.get("id"), "mode": m.get("mode"),
                     "status": "error", "health": {"stale": True, "last_heartbeat": None},
                     "paper_gate": None, "_err": str(e)}
        agent_id = entry["id"]
        proc = AGENT_PROC.get(agent_id, {})
        pid = find_proc(proc.get("patterns", [agent_id]), procs) if proc else None
        raw = read_json(BASE_DIR / m["state_file"])
        verdict, action = diagnose(entry, raw, pid)
        rows.append({
            "kind": "agent",
            "id": agent_id,
            "name": entry["name"],
            "mode": entry.get("mode"),
            "status": entry.get("status"),
            "pid": pid,
            "alive": pid is not None,
            "state_age": age_str(entry.get("health", {}).get("last_heartbeat")),
            "open_positions": entry.get("health", {}).get("open_positions"),
            "paper_gate": entry.get("paper_gate"),
            "verdict": verdict,
            "action": action,
            "launch": proc.get("launch"),
        })

    # Infra
    for inf_id, inf in INFRA_PROC.items():
        pid = find_proc(inf["patterns"], procs)
        rows.append({
            "kind": "infra",
            "id": inf_id,
            "name": inf["name"],
            "mode": "infra",
            "status": "running" if pid else "DEAD",
            "pid": pid,
            "alive": pid is not None,
            "state_age": "—",
            "verdict": "OK — running" if pid else "DEAD — process not running",
            "action": "none" if pid else "restart",
            "launch": inf.get("launch"),
        })

    dead = [r for r in rows if not r["alive"] and r["action"] == "restart"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "summary": {
            "total": len(rows),
            "alive": sum(1 for r in rows if r["alive"]),
            "dead": len(dead),
            "dead_ids": [r["id"] for r in dead],
        },
    }


def print_report(rep: dict) -> None:
    print("=" * 78)
    print(f"  MT5 BOT TRIAGE   {rep['generated_at']}")
    print("=" * 78)
    for r in rep["rows"]:
        flag = "OK " if r["alive"] else "DED"
        pid = f"pid {r['pid']}" if r["pid"] else "no proc"
        print(f"[{flag}] {r['name']:<34} {str(r['mode']):<7} {pid:<10} age={r['state_age']:>5}")
        print(f"      -> {r['verdict']}")
        if r["action"] not in ("none",):
            print(f"        action: {r['action']}")
    s = rep["summary"]
    print("-" * 78)
    print(f"  {s['alive']}/{s['total']} alive · {s['dead']} dead: {', '.join(s['dead_ids']) or 'none'}")
    print("=" * 78)


def restart_dead(rep: dict) -> None:
    import os
    for r in rep["rows"]:
        if r["alive"] or r["action"] != "restart" or not r.get("launch"):
            continue
        print(f"  starting {r['id']} … ({' '.join(r['launch'])})")
        try:
            subprocess.Popen(
                r["launch"], cwd=str(BASE_DIR),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                close_fds=True,
            )
        except Exception as e:
            print(f"    FAILED: {e}")


def push_telegram(rep: dict) -> None:
    try:
        from trading_agents import telegram_hq
    except Exception as e:
        print(f"  telegram unavailable: {e}")
        return
    s = rep["summary"]
    lines = [f"🧭 *Triage* — {s['alive']}/{s['total']} alive, {s['dead']} dead"]
    for r in rep["rows"]:
        flag = "✅" if r["alive"] else "❌"
        lines.append(f"{flag} {r['name']}: {r['verdict']}")
    msg = "\n".join(lines)
    for fn in ("send_supervisor", "send", "notify"):
        if hasattr(telegram_hq, fn):
            try:
                getattr(telegram_hq, fn)(msg)
                print("  telegram sent")
                return
            except Exception:
                continue
    print("  telegram: no compatible send fn found")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--restart-dead", action="store_true")
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    try:  # Windows consoles default to cp1252 — force utf-8 for glyphs
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    rep = build_report()
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    (BASE_DIR / "logs" / "_triage_report.json").write_text(
        json.dumps(rep, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)
    if args.restart_dead:
        print("\nRestarting dead agents…")
        restart_dead(rep)
    if args.telegram:
        push_telegram(rep)


if __name__ == "__main__":
    main()
