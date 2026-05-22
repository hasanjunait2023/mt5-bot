"""
loss_analyzer.py — Post-loss analysis engine.

For every SL_HIT trade in the journal:
  1. Classify WHY it lost (QUICK_STOP / LOW_CONFLUENCE / POOR_RR_SETUP /
     DEAD_SESSION / PREMATURE_SL / NORMAL_LOSS)
  2. Detect if price hit the TP direction within 20 M5 bars after closure
     (PREMATURE_SL — SL was too tight)
  3. Aggregate per-strategy mistake patterns + improvement suggestions

Bridge: GET /bars/{symbol}?timeframe=M5&limit=500
Cached: 60 s — re-analysis is cheap but not real-time.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

_BRIDGE_URL    = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
_POST_BARS     = 20   # M5 bars after SL close (~100 min) to check price direction
_CACHE_TTL     = 60   # seconds


_cache: dict[str, Any] = {"ts": 0.0, "data": None}


# ── MT5 bridge helpers ────────────────────────────────────────────────────────

def _fetch_m5(symbol: str, limit: int = 500) -> list[dict] | None:
    try:
        r = requests.get(
            f"{_BRIDGE_URL}/bars/{symbol}",
            params={"timeframe": "M5", "limit": limit},
            timeout=4,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        return [
            {"time": d["time"][i], "high": d["high"][i], "low": d["low"][i]}
            for i in range(len(d["time"]))
        ]
    except Exception:
        return None


# ── mistake classification ────────────────────────────────────────────────────

_DEAD_HOURS = {21, 22, 23, 0, 1, 2}   # UTC — thin liquidity


def _classify(rec: dict, bar_map: dict[str, list]) -> str:
    hold      = rec.get("hold_minutes") or 0
    conf      = rec.get("confluence_score") or 0
    ep        = rec.get("entry_price") or 0
    sl        = rec.get("sl") or 0
    tp        = rec.get("tp") or 0
    direction = rec.get("direction", "BUY")

    # 1. Spread / noise killed within first 5 minutes
    if hold < 5:
        return "QUICK_STOP"

    # 2. Signal was weak at entry
    if conf < 40:
        return "LOW_CONFLUENCE"

    # 3. TP:SL < 1.3 at entry — bad setup geometry
    sl_dist = abs(ep - sl) if sl and ep else 0
    tp_dist = abs(tp - ep) if tp and ep else 0
    if sl_dist > 0 and tp_dist > 0 and (tp_dist / sl_dist) < 1.3:
        return "POOR_RR_SETUP"

    # 4. Entered during dead session
    try:
        ot = datetime.fromisoformat(rec["open_time"].replace("Z", "+00:00"))
        if ot.hour in _DEAD_HOURS:
            return "DEAD_SESSION"
    except Exception:
        pass

    # 5. Post-close check — did price reach TP within _POST_BARS M5 candles?
    sym = rec.get("symbol", "")
    ct  = rec.get("close_time")
    bars = bar_map.get(sym)
    if bars and ct:
        try:
            close_ts = int(
                datetime.fromisoformat(ct.replace("Z", "+00:00")).timestamp()
            )
            idx = next((i for i, b in enumerate(bars) if b["time"] >= close_ts), None)
            if idx is not None:
                window = bars[idx: idx + _POST_BARS]
                if direction == "BUY":
                    reached = any(b["high"] >= tp for b in window if tp)
                else:
                    reached = any(b["low"] <= tp for b in window if tp)
                if reached:
                    return "PREMATURE_SL"
        except Exception:
            pass

    return "NORMAL_LOSS"


# ── improvement suggestions (rule-based) ─────────────────────────────────────

_SUGGESTIONS: dict[str, str] = {
    "QUICK_STOP":     "SL too tight — widen by 1.5× or add a spread buffer at entry",
    "LOW_CONFLUENCE": "Raise minimum confluence score to 60; skip signals below threshold",
    "POOR_RR_SETUP":  "Only take trades where TP:SL ≥ 1.5 at entry; filter weak setups",
    "DEAD_SESSION":   "Add session filter — avoid trading 21:00–03:00 UTC (thin market)",
    "PREMATURE_SL":   "SL too tight vs ATR; use ATR-based SL (e.g. 1.5× ATR14 M15)",
    "NORMAL_LOSS":    "No dominant pattern — review sample size; losses may be within edge",
}


# ── aggregation ───────────────────────────────────────────────────────────────

def _agg(recs: list[dict]) -> dict:
    if not recs:
        return {}
    counts: dict[str, int] = {}
    for r in recs:
        m = r.get("mistake", "NORMAL_LOSS")
        counts[m] = counts.get(m, 0) + 1

    top = max(counts, key=lambda k: counts[k])
    holds = [r["hold_minutes"] for r in recs if r.get("hold_minutes") is not None]
    confs = [r.get("confluence_score") or 0 for r in recs]

    return {
        "loss_count":       len(recs),
        "mistake_counts":   counts,
        "top_mistake":      top,
        "suggestion":       _SUGGESTIONS[top],
        "avg_confluence":   round(sum(confs) / len(confs), 1) if confs else None,
        "avg_hold_minutes": round(sum(holds) / len(holds), 1) if holds else None,
        "premature_sl_pct": round(counts.get("PREMATURE_SL", 0) / len(recs) * 100, 1),
    }


# ── public API ────────────────────────────────────────────────────────────────

def analyze() -> dict:
    """Full loss analysis, cached for _CACHE_TTL seconds."""
    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    from trading_agents.trade_journal import get_all   # avoid top-level circular dep

    losses = [t for t in get_all(limit=1000) if t.get("outcome") == "SL_HIT"]

    # Fetch M5 bars per symbol (graceful — bridge may be offline)
    symbols: set[str] = {t["symbol"] for t in losses if t.get("symbol")}
    bar_map: dict[str, list] = {}
    for sym in symbols:
        bars = _fetch_m5(sym)
        if bars:
            bar_map[sym] = bars

    # Classify
    classified = [{**rec, "mistake": _classify(rec, bar_map)} for rec in losses]

    # By strategy
    strat_map: dict[str, list] = {}
    for rec in classified:
        for s in (rec.get("strategies") or ["unknown"]):
            strat_map.setdefault(s, []).append(rec)

    # By source
    src_map: dict[str, list] = {}
    for rec in classified:
        src_map.setdefault(rec.get("source", "unknown"), []).append(rec)

    # Symbol mistake distribution (for quick overview)
    sym_map: dict[str, list] = {}
    for rec in classified:
        sym_map.setdefault(rec.get("symbol", "?"), []).append(rec)

    result: dict[str, Any] = {
        "total_losses": len(losses),
        "by_strategy":  {k: _agg(v) for k, v in strat_map.items()},
        "by_source":    {k: _agg(v) for k, v in src_map.items()},
        "by_symbol":    {k: _agg(v) for k, v in sym_map.items()},
        "trades":       classified,
    }

    _cache["ts"]   = now
    _cache["data"] = result
    return result
