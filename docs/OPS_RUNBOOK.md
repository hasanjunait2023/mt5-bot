# OPS RUNBOOK — single source of operational truth

Every session (human or AI) reads this first for "how/where/what" of running the
system. **No secrets live here** — only where to find them (see the bottom).
Keep this current; if a fact changes, edit it here so the next session inherits it.

---

## VPS (the live runner)

| Fact | Value |
|------|-------|
| Host | `72.62.228.196` |
| Users | `root` (admin) · `trader` (runs our stack) |
| Repo path on VPS | `/home/trader/mt5-bot` (GitHub secret `VPS_DEPLOY_PATH`) |
| Python (native) | system python3 — most agents (bridge_client HTTP shim) |
| Python (wine) | `/home/trader/.wine/drive_c/py311/python.exe` — bridge only (MetaTrader5 is Windows-only) |
| Headless X | `DISPLAY=:10` (xrdp) — MT5 terminal + xdotool guard render here |
| Swap | 4G (added 2026-06-02, holds all services) |

This VPS is the **live trader**. The local Windows box is a dev/standby box
(`DEPLOYMENT_MODE=local` → runs no live agents, avoids double-trading).

## Account (current)

| Fact | Value |
|------|-------|
| Broker / server | Exness — `Exness-MT5Trial14` |
| Login | `415733764` |
| Type | **DEMO** (Trial) — not real money |
| Balance | ~$742 |

All execution agents trade this demo account. See `memory/project_demo_execution_model.md`.

## Services

One supervisor runs everything: `trading_agents/orchestrator.py` reads
`configs/services.yaml` (26 services), starts each in dependency order,
health-checks, and auto-restarts on death. To see "who trades & why not":
`python scripts/triage.py`.

Key ports / endpoints:
- Bridge (MT5 over HTTP): `http://localhost:8090` — `/health`, `/reconciler/status`
- Dashboard backend: port `8000`/`8010`
- systemd units restarted on deploy: `mt5-dashboard`, `mt5-telegram`

## Deploy

Push to `master` → `.github/workflows/deploy-vps.yml` runs:
SSH to VPS → `git pull` → `pip install -r requirements-server.txt` →
`npm ci && npm run build` (frontend) → `systemctl restart mt5-dashboard mt5-telegram`.

**Gotcha:** deploy restarts the dashboard + telegram units, **not the bridge or
the agent orchestrator**. After a change to the bridge/agents you must restart
them on the VPS yourself (see below).

## Common procedures (on the VPS)

```bash
ssh mt5vps                         # see SSH config alias below
cd /home/trader/mt5-bot

# restart the whole stack (orchestrator re-reads services.yaml)
#   find + restart however the orchestrator is supervised (systemd unit or start_vps.sh)
# restart just the bridge (after bridge code change — picks up reconciler/self-heal):
pkill -f api_server.py             # orchestrator auto-restarts it
curl -s localhost:8090/reconciler/status   # verify reconciler running (closed_total rising)
curl -s localhost:8090/health

# stalled-agent check (work not progressing):
python scripts/pending_tracker.py --once   # writes logs/_stalled_agents.json + PENDING.md

# send the EOD trade report now (normally auto at 23:00 BD / 17:00 UTC):
python -m trading_agents.daily_trade_report --once
```

## Where state / logs live

- Live account snapshot: `mt5_bridge/_live_state.json`
- Per-agent state (health source): `logs/<agent>/_*_state.json`
- Trade journal (per-agent shards): written by agents + bridge reconciler
- Stalled agents: `logs/_stalled_agents.json` + `PENDING.md`
- Deferred work + stalled board: `PENDING.md`

## Dashboard

Served same-origin as the FastAPI backend on the VPS. Auth: when
`DASHBOARD_PASSWORD` is set, every `/api` route + WS needs a bearer token
(login screen). CORS locked via `DASHBOARD_ALLOWED_ORIGINS`. **Both default
OPEN if unset** — verify they're set on the VPS `.env`.

---

## SSH access (fixes "one session has the key, another doesn't")

Add this once to each machine's `~/.ssh/config` so `ssh mt5vps` works everywhere:

```
Host mt5vps
    HostName 72.62.228.196
    User root
    IdentityFile ~/.ssh/mt5vps_key
```

The private key (`~/.ssh/mt5vps_key`) must be present on the machine. How it gets
there across sessions/machines is the **secrets mechanism** — see below.

## Secrets — where they live, NOT what they are

Secrets are **never committed**. They live in the gitignored `.env` (per machine)
and `~/.ssh/` (SSH key). Inventory (names only; values in `.env`):

`SUPABASE_*`, `ANTHROPIC_API_KEY`, `NVIDIA_API_KEY`, `NOTION_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET`,
`FIRECRAWL_API_KEY`, `MAIC_ALLOWED_USER_IDS`. MT5 login is the broker terminal's
saved login (not in `.env`).

> **Cross-session sharing of secrets is an open decision** — see PENDING.md.
> Until then: a new machine is provisioned by copying `.env` + the SSH key from a
> trusted machine (out-of-band), or pulling them from the chosen secrets store.
