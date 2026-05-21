"""Performance tracker — logs trades, tracks P&L, win rate, DD. Writes to Supabase + local JSON."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("jtcc.perf")
BD_TZ = ZoneInfo("Asia/Dhaka")

BASE_DIR = Path(__file__).parent.parent.parent.parent
PERF_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_performance.json"
TRADE_LOG = BASE_DIR / "logs" / "jtcc" / "_jtcc_trades.jsonl"


def _ensure_dirs() -> None:
    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_perf() -> dict:
    try:
        if PERF_FILE.exists():
            return json.loads(PERF_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "total_trades": 0, "wins": 0, "losses": 0, "breakeven": 0,
        "total_pnl": 0.0, "max_dd_pct": 0.0,
        "best_strategy": None, "strategy_stats": {},
        "updated_at": None,
    }


def _save_perf(data: dict) -> None:
    _ensure_dirs()
    data["updated_at"] = datetime.now(tz=BD_TZ).isoformat()
    PERF_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_signal(signal: dict) -> None:
    """Log a detected signal (before execution)."""
    _ensure_dirs()
    entry = {
        "type": "signal",
        "ts": datetime.now(tz=BD_TZ).isoformat(),
        **{k: v for k, v in signal.items() if k not in ("ob_zones", "fvg_zones")},
    }
    with open(TRADE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_trade_open(trade_result: dict, decision: dict) -> None:
    """Log a trade opening."""
    _ensure_dirs()
    entry = {
        "type": "trade_open",
        "ts": datetime.now(tz=BD_TZ).isoformat(),
        "ticket": trade_result.get("ticket"),
        "symbol": decision.get("symbol"),
        "direction": decision.get("decision"),
        "entry": decision.get("entry_price"),
        "sl": decision.get("stop_loss"),
        "tp": decision.get("take_profit"),
        "rr": decision.get("rr_ratio"),
        "confidence": decision.get("confidence"),
        "strategies": decision.get("strategies_agreed", []),
    }
    with open(TRADE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    _push_supabase(entry)


def log_trade_close(ticket: int, pnl: float, symbol: str, strategy: str = "") -> None:
    """Log a trade close and update performance stats."""
    _ensure_dirs()
    entry = {
        "type": "trade_close",
        "ts": datetime.now(tz=BD_TZ).isoformat(),
        "ticket": ticket,
        "pnl": pnl,
        "symbol": symbol,
        "strategy": strategy,
    }
    with open(TRADE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    perf = _load_perf()
    perf["total_trades"] += 1
    perf["total_pnl"] = round(perf["total_pnl"] + pnl, 2)
    if pnl > 0:
        perf["wins"] += 1
    elif pnl < 0:
        perf["losses"] += 1
    else:
        perf["breakeven"] += 1

    # Strategy stats
    if strategy:
        s = perf["strategy_stats"].setdefault(strategy, {"trades": 0, "wins": 0, "pnl": 0.0})
        s["trades"] += 1
        s["pnl"] = round(s["pnl"] + pnl, 2)
        if pnl > 0:
            s["wins"] += 1

    _save_perf(perf)
    _push_supabase(entry)
    _notify_close(pnl, symbol, strategy)


def get_stats() -> dict:
    perf = _load_perf()
    total = perf["total_trades"]
    wins = perf["wins"]
    win_rate = round(wins / total * 100, 1) if total > 0 else 0.0
    return {**perf, "win_rate_pct": win_rate}


def _push_supabase(data: dict) -> None:
    """Push to Supabase tradevault table."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return
    try:
        import requests
        headers = {"apikey": key, "Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}
        requests.post(f"{url}/rest/v1/jtcc_trades", json=data,
                      headers=headers, timeout=5)
    except Exception as e:
        log.debug("Supabase push failed: %s", e)


def _notify_close(pnl: float, symbol: str, strategy: str) -> None:
    try:
        from trading_agents.telegram_hq import send as tg_send
        emoji = "✅" if pnl > 0 else "❌"
        msg = f"{emoji} Trade closed | {symbol} | P&L: {pnl:+.2f} | Strategy: {strategy}"
        tg_send("live_trading", msg, level="INFO", title="Trade Closed")
    except Exception:
        pass
