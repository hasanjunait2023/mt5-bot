"""
Orchestrator — the single supervisor for the whole MT5 bot.

Reads configs/services.yaml, starts every enabled service in dependency order,
captures its logs, health-checks it on an interval, and auto-restarts it on
death/staleness with backoff. Writes logs/_orchestrator_state.json so the
dashboard can show what's up. Replaces the four old competing launchers.

    python -m trading_agents.orchestrator            # run (foreground, supervises forever)
    python -m trading_agents.orchestrator status     # print current supervised state
    python -m trading_agents.orchestrator stop       # stop all supervised services

Install it to survive sleep/logoff via scripts/install_service.ps1.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except Exception:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    raise

BASE_DIR = Path(__file__).resolve().parents[1]

# Load .env so DEPLOYMENT_MODE (and other config) is honoured even when the
# orchestrator is launched bare (`python -m trading_agents.orchestrator`). Without
# this, a bare launch on the local standby box defaulted to mode="vps" and started
# the entire live profile locally — duplicating the VPS stack and spamming false
# "trader offline / MT5 connection lost" alerts from a stale local _live_state.json.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

CONFIG = BASE_DIR / "configs" / "services.yaml"
STATE_FILE = BASE_DIR / "logs" / "_orchestrator_state.json"
RESTART_REQ = BASE_DIR / "logs" / "_restart_requests.json"
LOCK_FILE = BASE_DIR / "logs" / "_orchestrator.lock"
SVC_LOG_DIR = BASE_DIR / "logs" / "services"

_IS_WIN = os.name == "nt"
_CREATE_GROUP = subprocess.CREATE_NEW_PROCESS_GROUP if _IS_WIN else 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(msg: str) -> None:
    line = f"{_now().isoformat()}  {msg}"
    # Windows consoles default to cp1252, which can't encode emoji (e.g. ❌ in
    # alerts) and would raise UnicodeEncodeError — crashing the whole supervisor.
    # Degrade unencodable chars instead of dying.
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)


# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> tuple[list[dict], dict]:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    defaults = cfg.get("defaults", {})
    # DEPLOYMENT_MODE picks the machine profile. Each service lists the profiles
    # it belongs to (default ["vps"]); the VPS runs everything, while a box
    # started with DEPLOYMENT_MODE=local runs only services tagged "local" (none
    # by default → local PC stays a dev/standby box with no live agents).
    mode = os.getenv("DEPLOYMENT_MODE", "vps").strip().lower()
    services = []
    for s in cfg.get("services", []):
        if not s.get("enabled", True):
            continue
        profiles = [str(p).lower() for p in s.get("profiles", ["vps"])]
        if mode not in profiles:
            continue
        services.append(s)
    _log(f"DEPLOYMENT_MODE={mode} -> {len(services)} services in profile")
    return services, defaults


def topo_order(services: list[dict]) -> list[dict]:
    """Order services so dependencies start first (Kahn)."""
    by_id = {s["id"]: s for s in services}
    indeg = {s["id"]: 0 for s in services}
    for s in services:
        for dep in s.get("depends_on", []):
            if dep in by_id:
                indeg[s["id"]] += 1
    ready = [sid for sid, d in indeg.items() if d == 0]
    out = []
    while ready:
        sid = ready.pop(0)
        out.append(by_id[sid])
        for s in services:
            if sid in s.get("depends_on", []):
                indeg[s["id"]] -= 1
                if indeg[s["id"]] == 0:
                    ready.append(s["id"])
    # any cycle leftovers: append as-is
    for s in services:
        if s not in out:
            out.append(s)
    return out


# ── Health probes ───────────────────────────────────────────────────────────--
def probe(health: dict) -> bool:
    t = (health or {}).get("type", "process")
    try:
        if t == "process":
            return True  # caller already confirmed process alive
        if t == "http":
            req = urllib.request.Request(health["url"], method="GET")
            with urllib.request.urlopen(req, timeout=float(health.get("timeout", 5))) as r:
                return r.status < 400
        if t == "tcp":
            host = health.get("host") or os.getenv("MT5_BRIDGE_HOST", "localhost")
            with socket.create_connection((host, int(health["port"])), timeout=float(health.get("timeout", 4))):
                return True
        if t == "file":
            p = BASE_DIR / health["path"]
            if not p.exists():
                return False
            age = time.time() - p.stat().st_mtime
            return age < float(health.get("max_age", 300))
    except Exception:
        return False
    return False


def grace_for(health: dict) -> float:
    """Seconds after (re)start during which we only require the process to be alive.

    Covers slow cold starts (e.g. an agent that does a synchronous LLM/NVIDIA
    heartbeat before its first state write). Override per service with
    `health.grace` in services.yaml.
    """
    h = health or {}
    if "grace" in h:
        return float(h["grace"])
    t = h.get("type", "process")
    if t == "file":
        return max(120.0, float(h.get("max_age", 300)) * 0.5)
    return 30.0


def port_of(health: dict) -> int | None:
    """The TCP port a service listens on, if any (for http/tcp health checks)."""
    t = (health or {}).get("type")
    if t == "tcp":
        try:
            return int(health["port"])
        except Exception:
            return None
    if t == "http":
        try:
            from urllib.parse import urlparse
            u = urlparse(health["url"])
            return u.port or (443 if u.scheme == "https" else 80)
        except Exception:
            return None
    return None


def free_port(port: int) -> None:
    """Kill any process currently LISTENing on `port` (clears leaked/orphaned servers)."""
    try:
        if _IS_WIN:
            ps = (f"Get-NetTCPConnection -LocalPort {port} -State Listen "
                  f"-ErrorAction SilentlyContinue | "
                  f"Select-Object -ExpandProperty OwningProcess -Unique")
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=15)
            for pid in res.stdout.split():
                pid = pid.strip()
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/T", "/F", "/PID", pid],
                                   capture_output=True)
                    _log(f"freed port {port}: killed pid {pid}")
        else:
            res = subprocess.run(["lsof", "-ti", f":{port}"],
                                 capture_output=True, text=True, timeout=15)
            for pid in res.stdout.split():
                if pid.strip().isdigit():
                    os.kill(int(pid), signal.SIGKILL)
    except Exception as e:
        _log(f"free_port({port}) failed: {e}")


# ── Supervised service ──────────────────────────────────────────────────────--
class Service:
    def __init__(self, spec: dict, defaults: dict):
        self.spec = spec
        self.id = spec["id"]
        self.name = spec.get("name", self.id)
        self.cmd = [str(c) for c in spec["cmd"]]
        # Services declare "python" generically; launch them with the SAME
        # interpreter running the orchestrator (the venv python, which has the
        # deps). On Linux there is often no bare "python", only "python3".
        if self.cmd and self.cmd[0] in ("python", "python3"):
            self.cmd[0] = sys.executable
        self.cwd = BASE_DIR / spec["cwd"] if spec.get("cwd") else BASE_DIR
        self.health = spec.get("health", {"type": "process"})
        r = {**defaults.get("restart", {}), **spec.get("restart", {})}
        self.restart_enabled = r.get("enabled", True)
        self.max_retries = int(r.get("max_retries", 5))
        self.backoff = float(r.get("backoff_seconds", 15))
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0
        self.fails = 0
        self.restarts = 0
        self.status = "stopped"
        self._logf = None

    def start(self) -> None:
        # Clear any leaked/orphaned listener so a port-bound service can bind.
        p = port_of(self.health)
        if p:
            free_port(p)
        SVC_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._logf = open(SVC_LOG_DIR / f"{self.id}.log", "a", encoding="utf-8")
        self._logf.write(f"\n===== start {_now().isoformat()} =====\n")
        self._logf.flush()
        self.proc = subprocess.Popen(
            self.cmd, cwd=str(self.cwd),
            stdout=self._logf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=_CREATE_GROUP,
        )
        self.started_at = time.time()
        self.status = "starting"
        _log(f"[{self.id}] started pid {self.proc.pid}")

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if not self.alive():
            return
        pid = self.proc.pid
        try:
            if _IS_WIN:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                               capture_output=True)
            else:
                self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.status = "stopped"
        _log(f"[{self.id}] stopped pid {pid}")

    def check(self) -> None:
        """One health evaluation; restart if needed."""
        if not self.alive():
            self.status = "dead"
            self._handle_unhealthy("process exited")
            return
        # within grace window → process-alive is enough
        if time.time() - self.started_at < grace_for(self.health):
            self.status = "starting"
            return
        if probe(self.health):
            if self.status != "running":
                _log(f"[{self.id}] healthy")
            self.status = "running"
            self.fails = 0
        else:
            self.status = "unhealthy"
            self._handle_unhealthy("health probe failed")

    def _handle_unhealthy(self, reason: str) -> None:
        self.fails += 1
        _log(f"[{self.id}] UNHEALTHY ({reason}) fail={self.fails}/{self.max_retries}")
        if not self.restart_enabled:
            return
        # Past max_retries we do NOT abandon the service forever. A trading agent
        # whose MT5 link blips (terminal IPC drop) would otherwise stay dead until
        # a human notices — exactly what kept the stack down after the 2026-06-02
        # MT5 outage. Instead we keep restarting on a capped exponential cooldown,
        # so the service self-recovers the moment MT5/the bridge comes back.
        # fails resets to 0 as soon as a health probe passes again (see check()).
        if self.fails > self.max_retries:
            if self.status != "failed":
                self.status = "failed"
                _alert(f"❌ {self.name} unhealthy after {self.max_retries} restarts "
                       f"({reason}) — retrying on cooldown until it recovers")
            cooldown = min(self.backoff * (2 ** (self.fails - self.max_retries)), 300.0)
        else:
            cooldown = self.backoff
        self.stop()
        time.sleep(cooldown)
        self.start()
        self.restarts += 1

    def snapshot(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "pid": self.proc.pid if self.alive() else None,
            "status": self.status, "fails": self.fails,
            "restarts": self.restarts,
            "health_type": self.health.get("type"),
        }


# ── Telegram (best-effort) ───────────────────────────────────────────────────-
def _alert(msg: str) -> None:
    _log("ALERT: " + msg)
    try:
        from trading_agents import telegram_hq
        for fn in ("send_supervisor", "send", "notify"):
            if hasattr(telegram_hq, fn):
                getattr(telegram_hq, fn)(msg)
                return
    except Exception:
        pass


# ── Lock ─────────────────────────────────────────────────────────────────────-
def _pid_alive(pid: int) -> bool:
    try:
        if _IS_WIN:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True)
            return str(pid) in out.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_lock() -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text().strip())
            if _pid_alive(old):
                _log(f"another orchestrator already running (pid {old}) — exiting")
                return False
        except Exception:
            pass
    LOCK_FILE.write_text(str(os.getpid()))
    return True


# ── Main supervise loop ──────────────────────────────────────────────────────-
class Orchestrator:
    def __init__(self):
        specs, self.defaults = load_config()
        self.interval = float(self.defaults.get("health_interval", 30))
        self.services = [Service(s, self.defaults) for s in topo_order(specs)]
        self._stop = False

    def run(self) -> None:
        if not acquire_lock():
            sys.exit(1)
        signal.signal(signal.SIGINT, self._sig)
        signal.signal(signal.SIGTERM, self._sig)
        _log(f"orchestrator up — {len(self.services)} services")
        for svc in self.services:
            for dep in svc.spec.get("depends_on", []):
                pass  # already ordered; start sequentially
            svc.start()
            time.sleep(2)  # stagger so deps settle
        try:
            while not self._stop:
                for svc in self.services:
                    if self._stop:
                        break
                    svc.check()
                self._process_restart_requests()
                self._write_state()
                for _ in range(int(self.interval)):
                    if self._stop:
                        break
                    time.sleep(1)
        finally:
            self._shutdown()

    def _sig(self, *_):
        _log("shutdown signal received")
        self._stop = True

    def _shutdown(self):
        for svc in reversed(self.services):
            svc.stop()
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        _log("orchestrator down")

    def _process_restart_requests(self) -> None:
        """Honour external restart requests (dev-team incident pipeline writes
        logs/_restart_requests.json: a list of {"service": <id>}). Fail-safe:
        any error is swallowed so the supervise loop never dies."""
        try:
            if not RESTART_REQ.exists():
                return
            raw = RESTART_REQ.read_text(encoding="utf-8").strip()
            RESTART_REQ.unlink(missing_ok=True)  # consume immediately
            reqs = json.loads(raw) if raw else []
        except Exception as e:
            _log(f"restart-request read failed: {e}")
            try:
                RESTART_REQ.unlink(missing_ok=True)
            except Exception:
                pass
            return
        if not isinstance(reqs, list):
            return
        wanted = {str(r.get("service")) for r in reqs
                  if isinstance(r, dict) and r.get("service")}
        for svc in self.services:
            if svc.id in wanted:
                try:
                    _log(f"[{svc.id}] external restart requested")
                    svc.stop()
                    svc.fails = 0
                    svc.start()
                    svc.restarts += 1
                except Exception as e:
                    _log(f"[{svc.id}] external restart failed: {e}")

    def _write_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": _now().isoformat(),
            "orchestrator_pid": os.getpid(),
            "services": [s.snapshot() for s in self.services],
        }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)


def cmd_status() -> None:
    if not STATE_FILE.exists():
        print("orchestrator not running (no state file)")
        return
    d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    age = time.time() - STATE_FILE.stat().st_mtime
    print(f"orchestrator pid {d.get('orchestrator_pid')} — state age {int(age)}s")
    for s in d.get("services", []):
        pid = s["pid"] or "-"
        print(f"  {s['status']:<10} {s['name']:<32} pid={pid} restarts={s['restarts']}")


def cmd_stop() -> None:
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            if _IS_WIN:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"sent stop to orchestrator pid {pid}")
        except Exception as e:
            print(f"stop failed: {e}")
    else:
        print("no orchestrator lock found")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "run"
    if arg == "status":
        cmd_status()
    elif arg == "stop":
        cmd_stop()
    else:
        Orchestrator().run()


if __name__ == "__main__":
    main()
