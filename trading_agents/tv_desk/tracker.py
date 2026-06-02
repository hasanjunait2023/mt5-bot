"""tracker — record every published setup and resolve its real outcome from TV.

This is the data layer that turns "the agent suggested X" into measured results,
so win-rate / expectancy accrue over time (the user asked to "collect the data
for the future"). No live money — pure forward paper tracking off TradingView's
own OHLCV.

Lifecycle per entry:
  pending  → price has not yet traded to the entry
  active   → entry filled, waiting for SL or TP1
  win      → TP1 hit first        (r_multiple = +RR1)
  loss     → SL hit first         (r_multiple = -1)
  expired  → filled but neither hit within the horizon (r marked-to-last)
  no_fill  → entry never reached within the horizon

Files (per agent dir):
  _trades.json   working set (list, mutated in place)
  _perf.json     rollup the dashboard reads
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import structure

log = logging.getLogger("tv_desk.tracker")

HORIZON_H = {"intraday": 24, "scalp": 8}
MAX_TRADES = 2000


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _load(agent_dir: Path) -> list[dict]:
    f = agent_dir / "_trades.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(agent_dir: Path, trades: list[dict]) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    trades = trades[-MAX_TRADES:]
    tmp = agent_dir / "_trades.json.tmp"
    tmp.write_text(json.dumps(trades, default=str), encoding="utf-8")
    tmp.replace(agent_dir / "_trades.json")


# ── record ───────────────────────────────────────────────────────────────────
def record(agent_dir: Path, event: dict, *, mode: str) -> None:
    trades = _load(agent_dir)
    horizon = HORIZON_H.get(mode, 12)
    ts_open = _now()
    for i, e in enumerate(event.get("entries", [])):
        trades.append({
            "id": f"{event['id']}#{i}",
            "event_id": event["id"],
            "symbol": event["symbol"],
            "tv_symbol": event["tv_symbol"],
            "entry_tf_code": event.get("entry_tf_code") or ("60" if mode == "intraday" else "15"),
            "mode": mode,
            "session": event.get("session"),
            "side": e["side"],
            "entry": float(e["entry"]),
            "sl": float(e["sl"]),
            "tp1": float(e["tp1"]),
            "tp2": float(e.get("tp2", e["tp1"])),
            "rr": e.get("rr", [2.0]),
            "win_prob": e.get("win_prob"),
            "type": e.get("type"),
            "ts_open": ts_open,
            "horizon_h": horizon,
            "status": "pending",
            "fill_ts": None, "close_ts": None, "close_price": None,
            "r_multiple": None,
        })
    _save(agent_dir, trades)
    log.info("recorded %d setups (%s)", len(event.get("entries", [])), event["symbol"])


# ── resolve ──────────────────────────────────────────────────────────────────
def resolve(tv, agent_dir: Path) -> None:
    """Walk TV price since each open trade opened and close any that hit SL/TP."""
    trades = _load(agent_dir)
    if not trades:
        return
    open_trades = [t for t in trades if t["status"] in ("pending", "active")]
    if not open_trades:
        compute_perf(agent_dir, trades)
        return

    # resolve on M5 for accurate fill / SL / TP detection (one fetch per symbol)
    groups: dict[str, list[dict]] = {}
    for t in open_trades:
        groups.setdefault(t["tv_symbol"], []).append(t)

    now = _now()
    for tv_symbol, group in groups.items():
        try:
            df = structure.fetch_df(tv, tv_symbol, "5")
        except Exception as e:
            log.warning("resolve fetch failed %s: %s", tv_symbol, e)
            continue
        if df is None or len(df) == 0:
            continue
        bars = df[["time", "high", "low", "close"]].copy()
        bars["ts"] = bars["time"].astype("int64") // 10 ** 9
        rows = bars.to_dict("records")
        for t in group:
            _resolve_one(t, rows, now)

    compute_perf(agent_dir, trades)
    _save(agent_dir, trades)


def _resolve_one(t: dict, rows: list[dict], now: float) -> None:
    risk = abs(t["entry"] - t["sl"]) or 1e-9
    buy = t["side"] == "BUY"
    expired_at = t["ts_open"] + t["horizon_h"] * 3600

    for r in rows:
        ts = r["ts"]
        if ts < t["ts_open"]:
            continue
        hi, lo, close = float(r["high"]), float(r["low"]), float(r["close"])

        if t["status"] == "pending":
            if lo <= t["entry"] <= hi:
                t["status"] = "active"
                t["fill_ts"] = ts
            else:
                continue   # not filled this bar

        if t["status"] == "active":
            if buy:
                hit_sl = lo <= t["sl"]
                hit_tp = hi >= t["tp1"]
            else:
                hit_sl = hi >= t["sl"]
                hit_tp = lo <= t["tp1"]
            if hit_sl and hit_tp:
                hit_tp = False        # same-bar ambiguity → SL first (conservative)
            if hit_sl:
                t.update(status="loss", close_ts=ts, close_price=t["sl"], r_multiple=-1.0)
                return
            if hit_tp:
                t.update(status="win", close_ts=ts, close_price=t["tp1"],
                         r_multiple=float(t["rr"][0]))
                return

    # horizon expiry
    if now >= expired_at and rows:
        last_close = float(rows[-1]["close"])
        if t["status"] == "pending":
            t["status"] = "no_fill"
        elif t["status"] == "active":
            r = ((last_close - t["entry"]) if buy else (t["entry"] - last_close)) / risk
            t.update(status="expired", close_ts=rows[-1]["ts"],
                     close_price=round(last_close, 6), r_multiple=round(r, 2))


# ── perf rollup ──────────────────────────────────────────────────────────────
def compute_perf(agent_dir: Path, trades: list[dict] | None = None) -> dict:
    trades = trades if trades is not None else _load(agent_dir)
    decisive = [t for t in trades if t["status"] in ("win", "loss")]
    closed = [t for t in trades if t["status"] in ("win", "loss", "expired")]
    wins = sum(1 for t in decisive if t["status"] == "win")
    losses = sum(1 for t in decisive if t["status"] == "loss")
    n_dec = wins + losses

    def _rollup(key: str) -> dict:
        out: dict[str, dict] = {}
        for t in decisive:
            k = str(t.get(key) or "—")
            o = out.setdefault(k, {"win": 0, "loss": 0})
            o["win" if t["status"] == "win" else "loss"] += 1
        for k, o in out.items():
            tot = o["win"] + o["loss"]
            o["n"] = tot
            o["win_rate"] = round(100 * o["win"] / tot, 1) if tot else 0.0
        return out

    perf = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": {
            "recorded": len(trades),
            "pending": sum(1 for t in trades if t["status"] == "pending"),
            "active": sum(1 for t in trades if t["status"] == "active"),
            "no_fill": sum(1 for t in trades if t["status"] == "no_fill"),
            "win": wins, "loss": losses, "expired": len(closed) - n_dec,
            "win_rate": round(100 * wins / n_dec, 1) if n_dec else None,
            "total_R": round(sum(t["r_multiple"] for t in closed if t["r_multiple"] is not None), 2),
            "avg_R": round(sum(t["r_multiple"] for t in closed if t["r_multiple"] is not None) / len(closed), 2) if closed else None,
        },
        "by_symbol": _rollup("symbol"),
        "by_session": _rollup("session"),
        "recent_closed": sorted(
            [t for t in closed], key=lambda t: t.get("close_ts") or 0, reverse=True)[:40],
    }
    (agent_dir / "_perf.json").write_text(json.dumps(perf, indent=2, default=str), encoding="utf-8")
    return perf
