"""Universal state schema — reads + normalizes per-agent state files."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("registry.schema")

STALE_SECONDS = 120  # state file older than this → stale


def _rj(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("read_json %s: %s", path, e)
    return default if default is not None else {}


def _age_seconds(ts_str: str | None) -> float | None:
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - ts).total_seconds()
    except Exception:
        return None


def _is_stale(ts_str: str | None) -> bool:
    age = _age_seconds(ts_str)
    if age is None:
        return True
    return age > STALE_SECONDS


def normalize(manifest: dict, base_dir: Path) -> dict:
    """Convert raw agent state → universal schema dict."""
    agent_id = manifest["id"]
    state_path = base_dir / manifest["state_file"]
    raw = _rj(state_path)

    adapter = _ADAPTERS.get(agent_id, _generic_adapter)
    return adapter(manifest, raw, base_dir)


# ── Per-agent adapters ──────────────────────────────────────────────────────

def _mtf_adapter(manifest: dict, raw: dict, base_dir: Path) -> dict:
    ts = raw.get("timestamp")
    acct = raw.get("account", {})
    daily_trades = raw.get("daily_trades", {})
    positions = raw.get("positions", [])

    running = raw.get("trader_running", False)
    mt5_ok = raw.get("mt5_connected", False)
    stale = _is_stale(ts)

    if stale:
        status = "stale"
    elif not running:
        status = "stopped"
    elif acct.get("daily_dd_pct", 0) >= manifest.get("risk", {}).get("daily_dd_pct", 20):
        status = "halted"
    else:
        status = "running"

    trades_today = sum(daily_trades.values()) if daily_trades else 0

    return _build(
        manifest=manifest,
        status=status,
        timestamp=ts,
        stale=stale,
        account={
            "balance": acct.get("balance"),
            "equity": acct.get("equity"),
            "daily_pnl": acct.get("daily_pnl"),
            "daily_dd_pct": acct.get("daily_dd_pct"),
        },
        performance={
            "total_trades": trades_today,
            "win_rate_pct": None,
            "profit_factor": None,
            "total_pnl": acct.get("daily_pnl"),
        },
        health={
            "mt5_connected": mt5_ok,
            "open_positions": len(positions),
            "issues": [] if mt5_ok else [{"severity": "WARNING", "msg": "MT5 disconnected"}],
        },
        paper_gate=None,
    )


def _jtcc_adapter(manifest: dict, raw: dict, base_dir: Path) -> dict:
    ts = raw.get("last_heartbeat")
    stale = _is_stale(ts)
    raw_status = raw.get("status", "stopped")

    if stale:
        status = "stale"
    elif raw_status == "running":
        status = "running"
    elif raw_status in ("halted", "stopped"):
        status = raw_status
    else:
        status = "idle"

    mode = "dry-run" if raw.get("dry_run") else manifest.get("mode", "live")

    # Read performance file
    perf_path = base_dir / "logs" / "jtcc" / "_jtcc_performance.json"
    perf = _rj(perf_path)

    return _build(
        manifest=manifest,
        status=status,
        timestamp=ts,
        stale=stale,
        account={
            "balance": None,
            "equity": None,
            "daily_pnl": perf.get("total_pnl"),
            "daily_dd_pct": None,
        },
        performance={
            "total_trades": perf.get("total_trades", 0),
            "win_rate_pct": perf.get("win_rate_pct"),
            "profit_factor": None,
            "total_pnl": perf.get("total_pnl"),
        },
        health={
            "mt5_connected": True,
            "open_positions": 0,
            "issues": [],
        },
        paper_gate=None,
        mode_override=mode,
    )


def _iconic_adapter(manifest: dict, raw: dict, base_dir: Path) -> dict:
    ts = raw.get("updated_at")
    stale = _is_stale(ts)
    raw_mode = raw.get("mode", "STOPPED")
    live_mode = raw.get("live_mode", False)

    mode = "live" if live_mode else "paper"
    if stale:
        status = "stale"
    elif raw_mode == "SCANNING":
        status = "running"
    elif raw_mode == "HALTED":
        status = "halted"
    else:
        status = "stopped"

    paper_trades = raw.get("paper_trades", 0)
    paper_pf = raw.get("paper_pf", 0.0)
    gate_cfg = manifest.get("paper_gate", {})
    min_t = gate_cfg.get("min_trades", 20)
    min_pf = gate_cfg.get("min_pf", 1.3)

    return _build(
        manifest=manifest,
        status=status,
        timestamp=ts,
        stale=stale,
        account={
            "balance": raw.get("equity"),
            "equity": raw.get("equity"),
            "daily_pnl": None,
            "daily_dd_pct": raw.get("daily_loss_pct"),
        },
        performance={
            "total_trades": paper_trades,
            "win_rate_pct": None,
            "profit_factor": paper_pf,
            "total_pnl": None,
        },
        health={
            "mt5_connected": True,
            "open_positions": len(raw.get("paper_pending", [])),
            "issues": [],
        },
        paper_gate={
            "trades_done": paper_trades,
            "trades_needed": min_t,
            "pf_current": paper_pf,
            "pf_needed": min_pf,
            "ready": paper_trades >= min_t and paper_pf >= min_pf,
        },
        mode_override=mode,
    )


def _scalp_adapter(manifest: dict, raw: dict, base_dir: Path) -> dict:
    ts = raw.get("updated_at")
    stale = _is_stale(ts)
    raw_mode = raw.get("mode", "STOPPED")

    if stale:
        status = "stale"
    elif raw_mode == "SCANNING":
        status = "running"
    elif raw_mode == "HALTED":
        status = "halted"
    else:
        status = "stopped"

    paper_trades = raw.get("paper_trades", 0)
    paper_pf = raw.get("paper_pf", 0.0)
    gate_cfg = manifest.get("paper_gate", {})
    min_t = gate_cfg.get("min_trades", 20)
    min_pf = gate_cfg.get("min_pf", 1.3)

    # Aggregate strategy stats
    strat_stats = raw.get("strat_stats", {})
    any_live = any(v.get("live", False) for v in strat_stats.values())
    mode = "live" if any_live else "paper"

    return _build(
        manifest=manifest,
        status=status,
        timestamp=ts,
        stale=stale,
        account={
            "balance": raw.get("equity"),
            "equity": raw.get("equity"),
            "daily_pnl": None,
            "daily_dd_pct": raw.get("daily_loss_pct"),
        },
        performance={
            "total_trades": paper_trades,
            "win_rate_pct": None,
            "profit_factor": paper_pf,
            "total_pnl": None,
        },
        health={
            "mt5_connected": True,
            "open_positions": len(raw.get("paper_pending", [])),
            "issues": [],
        },
        paper_gate={
            "trades_done": paper_trades,
            "trades_needed": min_t,
            "pf_current": paper_pf,
            "pf_needed": min_pf,
            "ready": paper_trades >= min_t and paper_pf >= min_pf,
        },
        mode_override=mode,
    )


def _generic_adapter(manifest: dict, raw: dict, base_dir: Path) -> dict:
    ts = raw.get("updated_at") or raw.get("timestamp") or raw.get("last_heartbeat")
    stale = _is_stale(ts)
    return _build(
        manifest=manifest,
        status="stale" if stale else raw.get("status", "unknown"),
        timestamp=ts,
        stale=stale,
        account={"balance": None, "equity": None, "daily_pnl": None, "daily_dd_pct": None},
        performance={"total_trades": 0, "win_rate_pct": None, "profit_factor": None, "total_pnl": None},
        health={"mt5_connected": True, "open_positions": 0, "issues": []},
        paper_gate=None,
    )


_ADAPTERS = {
    "mtf_live": _mtf_adapter,
    "jtcc": _jtcc_adapter,
    "iconic": _iconic_adapter,
    "scalp_gs11": _scalp_adapter,
}


def _build(
    manifest: dict,
    status: str,
    timestamp: str | None,
    stale: bool,
    account: dict,
    performance: dict,
    health: dict,
    paper_gate: dict | None,
    mode_override: str | None = None,
) -> dict:
    return {
        "name": manifest["name"],
        "id": manifest["id"],
        "mode": mode_override or manifest.get("mode", "unknown"),
        "status": status,
        "color": manifest.get("dashboard", {}).get("color", "neutral"),
        "group": manifest.get("dashboard", {}).get("group", "other"),
        "description": manifest.get("dashboard", {}).get("description", ""),
        "dashboard_page": manifest.get("dashboard_page", f"/{manifest['id']}"),
        "symbols": manifest.get("symbols", []),
        "account": account,
        "performance": performance,
        "health": {**health, "stale": stale, "last_heartbeat": timestamp},
        "paper_gate": paper_gate,
        "risk": manifest.get("risk", {}),
    }
