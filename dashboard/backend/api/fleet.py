"""
Fleet API — the live trading-agent fleet for the dashboard /fleet page.

`GET /api/fleet/overview?period=today|yesterday|7d|30d|all` (or from/to unix)
joins state files + the broker into a per-agent record a trader reads:
  • orchestrator state  → is the agent process alive (status/pid/restarts)
  • per-agent state file → mode/activity, the pairs it scans, per-strategy stats
  • magic_registry      → magic ↔ agent (so positions/deals attribute correctly)
  • bridge /positions   → OPEN positions grouped by magic → floating P&L (current)
  • bridge /history/deals → trades in the PERIOD grouped by magic → realized P&L

The period blotter is computed over an explicit [since, until] window (default =
today, i.e. since 00:00 UTC — the agents' daily-reset boundary), never a rolling
24h window. Open/floating P&L is always "now" and period-independent.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import requests
from fastapi import APIRouter, Query

from core.config import BASE_DIR, LIVE_STATE_PATH

sys.path.insert(0, str(BASE_DIR))
try:
    from trading_agents.magic_registry import agent_for_magic  # noqa: F401
except Exception:  # pragma: no cover
    def agent_for_magic(_m):  # type: ignore
        return None

router = APIRouter()

ORCH_STATE = BASE_DIR / "logs" / "_orchestrator_state.json"
BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090").rstrip("/")
_BRIDGE_HDRS = (
    {"X-API-Key": os.getenv("MT5_BRIDGE_SECRET", "")}
    if os.getenv("MT5_BRIDGE_SECRET") else {}
)

AGENTS = [
    {"id": "mtf_live",  "name": "MTF Scalper",   "strategy": "MTF EMA Alignment (M1/M3/M15)",
     "magic": 20260100, "orch_id": "mtf_live",   "state": LIVE_STATE_PATH,                 "pairs": []},
    {"id": "jtcc",      "name": "JTCC",          "strategy": "JTCC ICT / SMC confluence",
     "magic": 20260600, "orch_id": "jtcc",       "state": BASE_DIR / "logs/jtcc/_jtcc_state.json",        "pairs": []},
    {"id": "iconic",    "name": "Iconic Board",  "strategy": "Urban Forex Iconic — Whole-Board (28 G7)",
     "magic": 20260700, "orch_id": "iconic",     "state": BASE_DIR / "logs/iconic/_agent_state.json",     "pairs": []},
    {"id": "scalp",     "name": "Gold Scalp",    "strategy": "Gold Scalp (GS11/07/01/12)",
     "magic": 20260522, "orch_id": "scalp_gs11", "state": BASE_DIR / "logs/scalp/_agent_state.json",      "pairs": ["XAUUSD"]},
    {"id": "gsvp",      "name": "GS-VP",         "strategy": "Adaptive Volume Profile",
     "magic": 20260603, "orch_id": "gsvp",       "state": BASE_DIR / "logs/scalp/_gsvp_agent_state.json", "pairs": []},
    {"id": "asia_fade", "name": "Asia Desk",     "strategy": "Asian Range Fade (S1)",
     "magic": 20260800, "orch_id": "asia_fade",  "state": BASE_DIR / "logs/asia_desk/_state.json",        "pairs": []},
    {"id": "confluence", "name": "Confluence Desk", "strategy": "S13 5-Way + S19 Pullback",
     "magic": 20261300, "orch_id": "confluence", "state": BASE_DIR / "logs/confluence/_agent_state.json", "pairs": ["XAUUSD", "GBPUSD", "USDJPY"]},
]

_CACHE_TTL_S = 2.0
_lock = threading.Lock()
_cache: dict = {}          # keyed by window signature → (data, ts)


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _age_sec(path: Path):
    try:
        return round(time.time() - Path(path).stat().st_mtime, 1)
    except Exception:
        return None


def _bridge_get(path: str):
    try:
        r = requests.get(BRIDGE_URL + path, headers=_BRIDGE_HDRS, timeout=6)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


def _midnight_utc() -> float:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _window(period: str, from_: Optional[int], to: Optional[int]):
    """Return (since, until, label) for the requested report window."""
    now = time.time()
    if from_ or to:
        return (float(from_) if from_ else 0.0, float(to) if to else now, "Custom")
    mid = _midnight_utc()
    p = (period or "today").lower()
    if p == "yesterday":
        return (mid - 86400, mid, "Yesterday")
    if p == "7d":
        return (now - 7 * 86400, now, "Last 7 days")
    if p == "30d":
        return (now - 30 * 86400, now, "Last 30 days")
    if p == "all":
        return (now - 90 * 86400, now, "Last 90 days")
    return (mid, now, "Today")


def _blotter(deals: list, since: float, until: float) -> dict:
    """Per-magic window blotter: opened / closed / realized P&L / wins / losses."""
    out: dict[int, dict] = {}
    for x in deals:
        t = x.get("time") or 0
        if t < since or t >= until:
            continue
        m = int(x.get("magic", 0))
        rec = out.setdefault(m, {"opened": 0, "closed": 0, "realized": 0.0, "wins": 0, "losses": 0})
        entry = x.get("entry")
        if entry == 0:
            rec["opened"] += 1
        elif entry == 1:
            rec["closed"] += 1
            p = (x.get("profit", 0) or 0) + (x.get("swap", 0) or 0) + (x.get("commission", 0) or 0)
            rec["realized"] += p
            if p > 0:
                rec["wins"] += 1
            elif p < 0:
                rec["losses"] += 1
    for rec in out.values():
        rec["realized"] = round(rec["realized"], 2)
    return out


def _pairs(state: dict, fallback: list) -> list:
    if not state:
        return fallback
    syms = state.get("symbols")
    if isinstance(syms, list) and syms:
        return syms
    one = state.get("symbol") or state.get("last_tick_symbol")
    return [one] if one else fallback


def _mode(state: dict) -> str:
    if not state:
        return "UNKNOWN"
    m = state.get("mode") or state.get("status")
    if m:
        return str(m).upper()
    if state.get("trader_running") in (True, "True"):
        return "RUNNING"
    return "UNKNOWN"


def _strategies(state: dict) -> list:
    if not state:
        return []
    ss = state.get("strat_stats")
    if isinstance(ss, dict):
        out = []
        for name, v in ss.items():
            if not isinstance(v, dict):
                continue
            out.append({
                "name": name, "trades": v.get("trades", 0),
                "pf": v.get("pf"), "wr": v.get("wr"), "live": bool(v.get("live", True)),
            })
        return out
    return []


def _build(period: str, from_: Optional[int], to: Optional[int]):
    since, until, label = _window(period, from_, to)
    orch = _read_json(ORCH_STATE) or {}
    orch_by_id = {s.get("id"): s for s in orch.get("services", [])}

    positions_by_magic: dict[int, list] = {}
    pos_resp = _bridge_get("/positions/open")
    if pos_resp:
        for p in pos_resp.get("positions", []):
            positions_by_magic.setdefault(int(p.get("magic", 0)), []).append({
                "symbol": p.get("symbol"), "type": p.get("type"),
                "volume": p.get("volume"), "profit": round(p.get("profit", 0.0), 2),
            })

    now = time.time()
    days = min(90, max(1, int((now - since) / 86400) + 2))
    deals = _bridge_get(f"/history/deals?days={days}")
    blotter = _blotter(deals.get("deals", []) if deals else [], since, until)

    acct = _bridge_get("/account/info") or {}
    bridge_up = bool(pos_resp is not None or acct)

    agents_out = []
    tot_live = tot_pos = tot_opened = tot_closed = day_wins = 0
    tot_open_pnl = tot_realized = 0.0

    for a in AGENTS:
        state = _read_json(a["state"]) or {}
        age = _age_sec(a["state"])
        svc = orch_by_id.get(a["orch_id"], {})
        orch_status = svc.get("status", "unknown")
        # A fresh state file (<120s) means the agent's loop is alive and writing —
        # trust that as "live" even for standalone (non-orchestrator) agents like
        # asia_fade / confluence. Orchestrator status is the fallback signal.
        fresh = age is not None and age < 120
        health = "live" if fresh else \
                 "warning" if orch_status in ("running", "starting") else "offline"

        magic = a["magic"]
        positions = positions_by_magic.get(magic, [])
        open_count = len(positions)
        if not bridge_up:
            sc = state.get("open_positions")
            open_count = sc if isinstance(sc, int) else len(sc) if isinstance(sc, list) else 0
        open_pnl = round(sum(p["profit"] for p in positions), 2)

        b = blotter.get(magic, {"opened": 0, "closed": 0, "realized": 0.0, "wins": 0, "losses": 0})
        win_rate = round(b["wins"] / b["closed"] * 100, 0) if b["closed"] else None

        mode = _mode(state)
        if open_count > 0 and mode in ("RUNNING", "SCANNING"):
            mode = "IN TRADE"

        agents_out.append({
            "id": a["id"], "name": a["name"], "strategy": a["strategy"],
            "magic": magic, "health": health, "orch_status": orch_status,
            "restarts": svc.get("restarts", 0), "pid": svc.get("pid"), "mode": mode,
            "pairs": _pairs(state, a["pairs"]),
            "open_count": open_count, "open_pnl": open_pnl, "positions": positions,
            "stats": {
                "opened": b["opened"], "closed": b["closed"],
                "realized_pnl": round(b["realized"], 2),
                "wins": b["wins"], "losses": b["losses"], "win_rate": win_rate,
            },
            "strategies": _strategies(state),
            "daily_dd_pct": state.get("daily_loss_pct"),
            "equity": state.get("equity"), "state_age_sec": age,
        })

        if health == "live":
            tot_live += 1
        tot_pos += open_count
        tot_opened += b["opened"]
        tot_closed += b["closed"]
        tot_open_pnl += open_pnl
        tot_realized += b["realized"]
        day_wins += b["wins"]

    account = {}
    if acct:
        account = {"login": acct.get("login"), "server": acct.get("server"),
                   "balance": acct.get("balance"), "equity": acct.get("equity")}

    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "period": (period or "today").lower(), "period_label": label,
        "since": int(since), "until": int(until),
        "bridge_up": bridge_up, "account": account,
        "totals": {
            "agents": len(AGENTS), "live": tot_live,
            "open_positions": tot_pos, "open_pnl": round(tot_open_pnl, 2),
            "opened": tot_opened, "closed": tot_closed,
            "realized_pnl": round(tot_realized, 2),
            "win_rate": round(day_wins / tot_closed * 100, 0) if tot_closed else None,
        },
        "agents": agents_out,
    }


@router.get("/fleet/overview")
def fleet_overview(
    period: str = "today",
    from_: Optional[int] = Query(None, alias="from"),
    to: Optional[int] = None,
):
    key = f"{period}:{from_}:{to}"
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and (now - hit[1]) < _CACHE_TTL_S:
            return hit[0]
    data = _build(period, from_, to)
    with _lock:
        _cache[key] = (data, time.time())
    return data
