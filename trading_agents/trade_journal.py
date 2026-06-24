"""
trade_journal.py — Persistent, agent-attributed trade journal.

Records every trade open → close with full context:
  strategy names, agent, confluence score, rationale, outcome, PnL,
  hold time, actual RR achieved, account + demo/live provenance.

Storage : logs/trade_journal.jsonl — APPEND-ONLY, one JSON object per line.
  - open  : a full record with outcome="OPEN" (written by each agent at open).
  - close : a {"type":"close", "ticket":<position_id>, ...} delta (written ONLY
            by the bridge close-reconciler). Readers fold open+close at read time.

Why append-only: the journal is written by 4+ separate OS processes (each agent)
plus the bridge reconciler. The old "rewrite the whole file on close" approach let
one process overwrite the file from its own stale in-memory view and silently erase
other agents' records — a real cross-process data-loss bug. Appends never clobber.

`ticket` is the MT5 position_id (== opening order ticket for a market open). The
reconciler matches a closing deal back to its open record by this id.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("trade_journal")

_BASE = Path(__file__).parent.parent
# Legacy single-file journal (read-only now, for records written before sharding).
JOURNAL_PATH = Path(os.environ.get("TRADE_JOURNAL_PATH", str(_BASE / "logs" / "trade_journal.jsonl")))
# Sharded storage: each writer owns its own file → zero cross-process contention
# (the old single-file rewrite/append lost records under concurrent writers).
# Agents append opens to <agent>.jsonl; the bridge reconciler appends closes to
# _closes.jsonl. Readers fold across the legacy file + every shard.
JOURNAL_DIR = Path(os.environ.get("TRADE_JOURNAL_DIR", str(_BASE / "logs" / "journal")))
JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (name or "misc"))[:48] or "misc"


def _shard_path(name: str) -> Path:
    return JOURNAL_DIR / f"{_safe(name)}.jsonl"

MIN_SAMPLE = 20          # below this, per-strategy stats are flagged "insufficient"
_RATIONALE_CAP = 1000    # keep an open line well under PIPE_BUF so appends stay atomic

_lock = threading.Lock()

# close-event fields a close delta may carry onto its open record
_CLOSE_FIELDS = ("exit_price", "pnl", "outcome", "close_time",
                 "hold_minutes", "actual_rr", "account_login", "demo")


# ── internal helpers ──────────────────────────────────────────────────────────

def _read_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception as e:
            log.debug("Journal line parse failed: %s", e)
    return out


def _read_raw() -> list[dict]:
    """Read the legacy single file + every shard, in a stable order."""
    out: list[dict] = _read_file(JOURNAL_PATH)
    if JOURNAL_DIR.exists():
        for shard in sorted(JOURNAL_DIR.glob("*.jsonl")):
            out.extend(_read_file(shard))
    return out


def _folded() -> dict[int, dict]:
    """Fold open + close events into one record per ticket. Reads fresh each call
    (files are tiny) so concurrent writers in other processes are always seen."""
    index: dict[int, dict] = {}
    closes: list[tuple[int, dict]] = []
    for rec in _read_raw():
        tk = rec.get("ticket")
        if tk is None:
            continue
        tk = int(tk)
        if rec.get("type") == "close":
            closes.append((tk, rec))
        else:
            # open record (or a legacy full record that already has close fields)
            if tk in index:
                index[tk].update(rec)
            else:
                index[tk] = dict(rec)
    for tk, rec in closes:
        base = index.get(tk)
        if base is None:                      # close with no matching open (orphan)
            base = {"ticket": tk, "outcome": "OPEN"}
            index[tk] = base
        for k in _CLOSE_FIELDS:
            if rec.get(k) is not None:
                base[k] = rec[k]

    return index


def _append(rec: dict, path: Path) -> None:
    """Append one JSON line to a per-writer shard. Each writer owns its own file,
    so there is no cross-process contention to corrupt."""
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


# ── public API ────────────────────────────────────────────────────────────────

def open_trade(
    ticket: int,
    symbol: str,
    direction: str,           # "BUY" | "SELL"
    entry_price: float,
    sl: float,
    tp: float,
    volume: float,
    source: str,              # "MTF_EMA" | "JTCC" | "ICONIC" | "SCALP" | ...
    strategies: list[str] | None = None,
    agent: str = "",
    backend: str = "",
    confluence_score: float = 0.0,
    rationale: str = "",
) -> None:
    rec: dict[str, Any] = {
        "ticket":           int(ticket),
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
        "rationale":        (rationale or "")[:_RATIONALE_CAP],
        "open_time":        datetime.now(timezone.utc).isoformat(),
        "close_time":       None,
        "exit_price":       None,
        "pnl":              None,
        "outcome":          "OPEN",
        "hold_minutes":     None,
        "actual_rr":        None,
    }
    with _lock:
        _append(rec, _shard_path(agent or source))


def close_trade(
    ticket: int,
    exit_price: float,
    pnl: float,
    outcome: str,             # "TP_HIT" | "SL_HIT" | "MANUAL" | "CLOSED"
    close_time: str | None = None,
    hold_minutes: float | None = None,
    actual_rr: float | None = None,
    account_login: int | None = None,
    demo: bool | None = None,
) -> bool:
    """Append a close delta for `ticket` (= position_id). Idempotent: if the
    position is already closed in the journal, this is a no-op returning False."""
    with _lock:
        idx = _folded()
        existing = idx.get(int(ticket))
        if existing is not None and existing.get("outcome") not in (None, "OPEN") \
                and existing.get("pnl") is not None:
            return False  # already reconciled — don't double-count

        ct = close_time or datetime.now(timezone.utc).isoformat()

        # derive hold/rr from the open record when the caller didn't supply them
        if (hold_minutes is None or actual_rr is None) and existing is not None:
            if hold_minutes is None and existing.get("open_time"):
                try:
                    ot = datetime.fromisoformat(str(existing["open_time"]).replace("Z", "+00:00"))
                    cdt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    hold_minutes = round((cdt - ot).total_seconds() / 60, 1)
                except Exception as e:
                    log.debug("Hold time calc failed: %s", e)
            if actual_rr is None and existing.get("entry_price") is not None and existing.get("sl") is not None:
                try:
                    sl_dist = abs(existing["entry_price"] - existing["sl"])
                    exit_dist = abs(exit_price - existing["entry_price"])
                    actual_rr = round(exit_dist / sl_dist, 2) if sl_dist > 0 else None
                except Exception as e:
                    log.debug("RR calc failed: %s", e)

        ev: dict[str, Any] = {
            "type":         "close",
            "ticket":       int(ticket),
            "exit_price":   exit_price,
            "pnl":          round(pnl, 2),
            "outcome":      outcome,
            "close_time":   ct,
            "hold_minutes": hold_minutes,
            "actual_rr":    actual_rr,
        }
        if account_login is not None:
            ev["account_login"] = int(account_login)
        if demo is not None:
            ev["demo"] = bool(demo)
        _append(ev, _shard_path("_closes"))
        return True


def get_open_tickets() -> set[int]:
    with _lock:
        return {tk for tk, r in _folded().items() if r.get("outcome") == "OPEN"}


def get_all(limit: int = 500) -> list[dict]:
    with _lock:
        recs = sorted(_folded().values(), key=lambda r: r.get("open_time", ""), reverse=True)
        return list(recs[:limit])


# ── stats ─────────────────────────────────────────────────────────────────────

def _max_drawdown(records: list[dict]) -> float | None:
    """Isolated drawdown = worst peak-to-trough on THIS bucket's ordered closed-pnl
    running equity. NOTE: this is per-strategy isolated DD, NOT account drawdown
    (it ignores concurrent positions / shared equity). Account DD lives in risk mgmt."""
    ordered = sorted((r for r in records if r.get("close_time")),
                     key=lambda r: r["close_time"])
    if not ordered:
        return None
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in ordered:
        cum += r["pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return round(max_dd, 2)


def _agg(records: list[dict]) -> dict:
    if not records:
        return {"trades": 0, "sample_ok": False}
    wins = [r for r in records if r["pnl"] > 0]
    losses = [r for r in records if r["pnl"] <= 0]
    gross_profit = sum(r["pnl"] for r in wins)
    gross_loss = abs(sum(r["pnl"] for r in losses))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
    hold_vals = [r["hold_minutes"] for r in records if r.get("hold_minutes") is not None]
    avg_hold = round(sum(hold_vals) / len(hold_vals), 1) if hold_vals else None
    rr_vals = [r["actual_rr"] for r in records if r.get("actual_rr") is not None]
    avg_rr = round(sum(rr_vals) / len(rr_vals), 2) if rr_vals else None
    return {
        "trades":           len(records),
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate_pct":     round(len(wins) / len(records) * 100, 1),
        "profit_factor":    pf,
        "net_pnl":          round(sum(r["pnl"] for r in records), 2),
        "avg_hold_minutes": avg_hold,
        "avg_rr":           avg_rr,
        "expectancy":       round(sum(r["pnl"] for r in records) / len(records), 2),
        "max_drawdown":     _max_drawdown(records),
        "sample_ok":        len(records) >= MIN_SAMPLE,
    }


def _in_window(rec: dict, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    ct = rec.get("close_time")
    if not ct:
        return False
    try:
        return datetime.fromisoformat(str(ct).replace("Z", "+00:00")) >= cutoff
    except Exception as e:
        log.debug("close_time parse failed: %s", e)
        return False


def get_stats(window_days: int | None = None, demo: bool | None = None) -> dict:
    """Aggregated per-agent / per-strategy / per-symbol stats from CLOSED trades.

    window_days : None = since inception, or 7 / 30 to time-window by close_time.
    demo        : None = all, True/False = filter to demo or live trades only
                  (never blend — different spreads/fills make a blended PF meaningless).
    """
    with _lock:
        recs = list(_folded().values())

    cutoff = None
    if window_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    closed = [
        r for r in recs
        if r.get("outcome") != "OPEN" and r.get("pnl") is not None
        and _in_window(r, cutoff)
        and (demo is None or r.get("demo") == demo)
    ]

    def _group(key_fn) -> dict[str, list]:
        out: dict[str, list] = {}
        for r in closed:
            for k in key_fn(r):
                out.setdefault(k, []).append(r)
        return out

    by_agent = _group(lambda r: [r.get("agent") or "unknown"])
    by_source = _group(lambda r: [r.get("source") or "unknown"])
    by_strategy = _group(lambda r: (r.get("strategies") or ["(none)"]))
    by_symbol = _group(lambda r: [r.get("symbol") or "unknown"])

    # portfolio equity curve (trustworthy at any sample size)
    ordered = sorted((r for r in closed if r.get("close_time")), key=lambda r: r["close_time"])
    cum = 0.0
    equity_curve = []
    for r in ordered:
        cum += r["pnl"]
        equity_curve.append({"t": r["close_time"], "cum_pnl": round(cum, 2)})

    return {
        "window_days": window_days,
        "demo_filter": demo,
        "total":       _agg(closed),
        "by_agent":    {k: _agg(v) for k, v in by_agent.items()},
        "by_source":   {k: _agg(v) for k, v in by_source.items()},
        "by_strategy": {k: _agg(v) for k, v in by_strategy.items()},
        "by_symbol":   {k: _agg(v) for k, v in by_symbol.items()},
        "equity_curve": equity_curve,
    }
