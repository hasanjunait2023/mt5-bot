"""
trade_journal.py — Persistent, agent-attributed trade journal.

Records every trade open → close with full context:
  strategy names, agent, confluence score, rationale, outcome, PnL,
  hold time, actual RR achieved.

Storage : logs/trade_journal.jsonl  (one JSON per line, append-only open,
           full rewrite on close to update the record in-place)

Thread-safe: all public functions acquire a single module-level lock.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BASE = Path(__file__).parent.parent
JOURNAL_PATH = _BASE / "logs" / "trade_journal.jsonl"
JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_index: dict[int, dict] = {}   # ticket → record (in-memory mirror)
_loaded = False


# ── internal helpers ──────────────────────────────────────────────────────────

def _load() -> None:
    global _loaded
    if _loaded:
        return
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                tk = rec.get("ticket")
                if tk is not None:
                    _index[int(tk)] = rec
            except Exception:
                pass
    _loaded = True


def _flush() -> None:
    """Rewrite entire journal from the in-memory index (after updates)."""
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        for rec in sorted(_index.values(), key=lambda r: r.get("open_time", "")):
            f.write(json.dumps(rec) + "\n")


def _append(rec: dict) -> None:
    """Append a single record (for new opens — avoids rewriting on every open)."""
    with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ── public API ────────────────────────────────────────────────────────────────

def open_trade(
    ticket: int,
    symbol: str,
    direction: str,           # "BUY" | "SELL"
    entry_price: float,
    sl: float,
    tp: float,
    volume: float,
    source: str,              # "MTF_EMA" | "JTCC" | "CPP"
    strategies: list[str] | None = None,
    agent: str = "",
    backend: str = "",
    confluence_score: float = 0.0,
    rationale: str = "",
) -> None:
    with _lock:
        _load()
        rec: dict[str, Any] = {
            "ticket":           ticket,
            "symbol":           symbol,
            "direction":        direction,
            "entry_price":      entry_price,
            "sl":               sl,
            "tp":               tp,
            "volume":           volume,
            "source":           source,
            "strategies":       strategies or [],
            "agent":            agent,
            "backend":          backend,
            "confluence_score": confluence_score,
            "rationale":        rationale,
            "open_time":        datetime.now(timezone.utc).isoformat(),
            "close_time":       None,
            "exit_price":       None,
            "pnl":              None,
            "outcome":          "OPEN",
            "hold_minutes":     None,
            "actual_rr":        None,
        }
        _index[ticket] = rec
        _append(rec)


def close_trade(
    ticket: int,
    exit_price: float,
    pnl: float,
    outcome: str,             # "TP_HIT" | "SL_HIT" | "MANUAL"
    close_time: str | None = None,
) -> bool:
    with _lock:
        _load()
        rec = _index.get(ticket)
        if rec is None:
            return False

        ct = close_time or datetime.now(timezone.utc).isoformat()
        rec["exit_price"]  = exit_price
        rec["pnl"]         = round(pnl, 2)
        rec["outcome"]     = outcome
        rec["close_time"]  = ct

        try:
            ot  = datetime.fromisoformat(rec["open_time"].replace("Z", "+00:00"))
            cdt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            rec["hold_minutes"] = round((cdt - ot).total_seconds() / 60, 1)
        except Exception:
            rec["hold_minutes"] = None

        try:
            sl_dist   = abs(rec["entry_price"] - rec["sl"])
            exit_dist = abs(exit_price - rec["entry_price"])
            rec["actual_rr"] = round(exit_dist / sl_dist, 2) if sl_dist > 0 else None
        except Exception:
            rec["actual_rr"] = None

        _flush()
        return True


def get_open_tickets() -> set[int]:
    with _lock:
        _load()
        return {tk for tk, r in _index.items() if r.get("outcome") == "OPEN"}


def get_all(limit: int = 500) -> list[dict]:
    with _lock:
        _load()
        recs = sorted(_index.values(), key=lambda r: r.get("open_time", ""), reverse=True)
        return list(recs[:limit])


def get_stats() -> dict:
    """Returns aggregated stats: total, by_source, by_strategy, by_symbol."""
    with _lock:
        _load()
        closed = [r for r in _index.values()
                  if r.get("outcome") != "OPEN" and r.get("pnl") is not None]

    def _agg(records: list[dict]) -> dict:
        if not records:
            return {"trades": 0}
        wins   = [r for r in records if r["pnl"] > 0]
        losses = [r for r in records if r["pnl"] <= 0]
        gross_profit = sum(r["pnl"] for r in wins)
        gross_loss   = abs(sum(r["pnl"] for r in losses))
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        hold_vals = [r["hold_minutes"] for r in records if r.get("hold_minutes") is not None]
        avg_hold = round(sum(hold_vals) / len(hold_vals), 1) if hold_vals else None
        return {
            "trades":          len(records),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate_pct":    round(len(wins) / len(records) * 100, 1),
            "profit_factor":   pf,
            "net_pnl":         round(sum(r["pnl"] for r in records), 2),
            "avg_hold_minutes": avg_hold,
            "expectancy":      round(sum(r["pnl"] for r in records) / len(records), 2),
        }

    sources: dict[str, list] = {}
    for r in closed:
        sources.setdefault(r.get("source", "unknown"), []).append(r)

    strat_map: dict[str, list] = {}
    for r in closed:
        for s in (r.get("strategies") or []):
            strat_map.setdefault(s, []).append(r)

    sym_map: dict[str, list] = {}
    for r in closed:
        sym_map.setdefault(r["symbol"], []).append(r)

    return {
        "total":       _agg(closed),
        "by_source":   {k: _agg(v) for k, v in sources.items()},
        "by_strategy": {k: _agg(v) for k, v in strat_map.items()},
        "by_symbol":   {k: _agg(v) for k, v in sym_map.items()},
    }
