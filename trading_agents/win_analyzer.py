"""
win_analyzer.py — Post-WIN analysis engine (mirror of loss_analyzer.py).

The improvement loop must learn from what WORKS, not only patch what fails.
For every TP_HIT / positive-pnl trade in the journal, classify what made it win
and aggregate per-strategy strength patterns. Feeds strategy_scorecard's
`strength_headline` and the Phase 5 improvement loop (reinforce, don't only fix).

Win patterns:
  STRONG_CONFLUENCE  — high signal quality at entry (conf >= 60)
  BIG_RR             — captured >= 2R
  PRIME_SESSION      — entered in a London/NY kill-zone hour
  QUICK_WIN          — TP hit fast (hold < 30 min), clean momentum
  SOLID_WIN          — won with no single standout factor
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

_CACHE_TTL = 60
_cache: dict[str, Any] = {"ts": 0.0, "data": None}

# UTC kill-zone hours (London 13-16 BD = 07-10 UTC, NY 18-21 BD = 12-15 UTC) +
# the active-session band where edge concentrates.
_PRIME_HOURS = {7, 8, 9, 10, 12, 13, 14, 15}


def _classify(rec: dict) -> str:
    conf = rec.get("confluence_score") or 0
    rr = rec.get("actual_rr") or 0
    hold = rec.get("hold_minutes")
    if conf >= 60:
        return "STRONG_CONFLUENCE"
    if rr >= 2:
        return "BIG_RR"
    try:
        ot = datetime.fromisoformat(str(rec["open_time"]).replace("Z", "+00:00"))
        if ot.hour in _PRIME_HOURS:
            return "PRIME_SESSION"
    except Exception:
        pass
    if hold is not None and hold < 30:
        return "QUICK_WIN"
    return "SOLID_WIN"


_STRENGTHS: dict[str, str] = {
    "STRONG_CONFLUENCE": "High-confluence entries win — keep the bar high, this is the edge",
    "BIG_RR":            "Wins come from letting 2R+ run — protect runners, don't cut early",
    "PRIME_SESSION":     "Edge concentrates in London/NY kill-zones — weight size there",
    "QUICK_WIN":         "Fast momentum TPs work — favour clean breakout setups",
    "SOLID_WIN":         "Wins are broad-based — no single factor; consistency is the strength",
}


def _agg(recs: list[dict]) -> dict:
    if not recs:
        return {}
    counts: dict[str, int] = {}
    for r in recs:
        p = r.get("win_pattern", "SOLID_WIN")
        counts[p] = counts.get(p, 0) + 1
    top = max(counts, key=lambda k: counts[k])
    confs = [r.get("confluence_score") or 0 for r in recs]
    rrs = [r["actual_rr"] for r in recs if r.get("actual_rr") is not None]
    holds = [r["hold_minutes"] for r in recs if r.get("hold_minutes") is not None]
    return {
        "win_count":       len(recs),
        "pattern_counts":  counts,
        "top_strength":    top,
        "strength_note":   _STRENGTHS[top],
        "avg_confluence":  round(sum(confs) / len(confs), 1) if confs else None,
        "avg_rr":          round(sum(rrs) / len(rrs), 2) if rrs else None,
        "avg_hold_minutes": round(sum(holds) / len(holds), 1) if holds else None,
    }


def analyze() -> dict:
    """Full win analysis, cached for _CACHE_TTL seconds."""
    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    from trading_agents.trade_journal import get_all

    wins = [t for t in get_all(limit=1000)
            if t.get("outcome") == "TP_HIT" or (t.get("pnl") or 0) > 0]
    classified = [{**rec, "win_pattern": _classify(rec)} for rec in wins
                  if rec.get("outcome") != "OPEN"]

    strat_map: dict[str, list] = {}
    for rec in classified:
        for s in (rec.get("strategies") or ["unknown"]):
            strat_map.setdefault(s, []).append(rec)
    src_map: dict[str, list] = {}
    for rec in classified:
        src_map.setdefault(rec.get("source", "unknown"), []).append(rec)

    result = {
        "total_wins":  len(classified),
        "by_strategy": {k: _agg(v) for k, v in strat_map.items()},
        "by_source":   {k: _agg(v) for k, v in src_map.items()},
    }
    _cache["ts"], _cache["data"] = now, result
    return result
