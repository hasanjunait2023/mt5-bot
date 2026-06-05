"""Strategy Factory paper-soak runner.

Paper-trades every strategy on the soak roster (logs/factory/_soak_roster.json)
against live bars from the MT5 bridge — isolated from the production scalp agent.
Writes closed trades to _soak_trades.jsonl and a heartbeat + per-strategy metrics
to _soak_state.json (read by the dashboard and the factory runner's SOAK gate).

Managed as the `factory_paper` service. Loop ~30s; 1% logic is simplified to raw
price PnL per unit (PF/WR are what matter for the gate, not absolute cash).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from trading_agents.scalp import backtest as bt
from trading_agents.factory import optimize as fopt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("factory.paper")

FACTORY_DIR = bt.BASE_DIR / "logs" / "factory"
ROSTER_PATH = FACTORY_DIR / "_soak_roster.json"
TRADES_PATH = FACTORY_DIR / "_soak_trades.jsonl"
STATE_PATH = FACTORY_DIR / "_soak_state.json"
POLL_S = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_roster() -> list[dict]:
    if not ROSTER_PATH.exists():
        return []
    try:
        return json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def add_to_roster(job_id: str, strategy_id: str, timeframe: str,
                  symbols: list[str], config_path: str = "") -> None:
    """Append/replace a strategy on the soak roster (called by DEMO_DEPLOY)."""
    FACTORY_DIR.mkdir(parents=True, exist_ok=True)
    roster = [r for r in _read_roster() if r.get("strategy_id") != strategy_id]
    roster.append({"job_id": job_id, "strategy_id": strategy_id,
                   "timeframe": timeframe, "symbols": symbols,
                   "config_path": config_path, "deployed_at": _now()})
    ROSTER_PATH.write_text(json.dumps(roster, indent=2), encoding="utf-8")


def _apply_config(sid: str, config_path: str) -> None:
    """Load saved params into the strategy module's *_PARAMS dict."""
    if not config_path or not Path(config_path).exists():
        return
    try:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        params = fopt._params_dict(sid)
        if params is not None and cfg.get("params"):
            params.update(cfg["params"])
    except Exception as e:  # noqa: BLE001
        log.warning("config load %s: %s", sid, e)


class _Book:
    """Open + closed paper trades for the whole roster, persisted to jsonl."""

    def __init__(self) -> None:
        self.pending: dict[str, dict] = {}
        self.closed: list[dict] = []
        if TRADES_PATH.exists():
            for line in TRADES_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    t = json.loads(line)
                    if t.get("status") == "closed":
                        self.closed.append(t)
                except Exception:
                    pass

    def has_pending(self, sym: str, sid: str) -> bool:
        return f"{sym}:{sid}" in self.pending

    def open(self, sym: str, sid: str, side: str, entry: float, sl: float, tp: float) -> None:
        t = {"symbol": sym, "strategy": sid, "side": side, "entry": entry,
             "stop": sl, "tp": tp, "status": "open", "ts_open": _now()}
        self.pending[f"{sym}:{sid}"] = t
        log.info("[soak] OPEN %s %s/%s @ %.5f SL=%.5f TP=%.5f", side, sym, sid, entry, sl, tp)

    def tick(self, sym: str, high: float, low: float) -> None:
        for key in [k for k in self.pending if k.startswith(sym + ":")]:
            p = self.pending[key]
            side = p["side"]
            hit_sl = low <= p["stop"] if side == "BUY" else high >= p["stop"]
            hit_tp = high >= p["tp"] if side == "BUY" else low <= p["tp"]
            if hit_sl or hit_tp:
                exit_price = p["stop"] if hit_sl else p["tp"]
                pnl = (exit_price - p["entry"]) if side == "BUY" else (p["entry"] - exit_price)
                p.update({"status": "closed", "exit": "TP" if hit_tp else "SL",
                          "exit_price": exit_price, "pnl": round(pnl, 8), "ts_close": _now()})
                self.closed.append(p)
                del self.pending[key]
                with TRADES_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(p) + "\n")
                log.info("[soak] CLOSE %s/%s %s PnL=%.5f", sym, p["strategy"], p["exit"], pnl)

    def metrics(self, sid: str) -> dict:
        tr = [t for t in self.closed if t.get("strategy") == sid]
        wins = sum(t["pnl"] for t in tr if t.get("pnl", 0) > 0)
        losses = abs(sum(t["pnl"] for t in tr if t.get("pnl", 0) < 0))
        pf = round(wins / losses, 2) if losses > 0 else (99.0 if wins > 0 else 0.0)
        wr = round(sum(1 for t in tr if t.get("pnl", 0) > 0) / len(tr) * 100, 1) if tr else 0.0
        return {"trades": len(tr), "pf": pf, "win_rate": wr,
                "open": sum(1 for k in self.pending if k.endswith(":" + sid))}


def _eval_signal(sid: str, bars: dict, t_i: int, spread: float, symbol: str):
    import inspect
    tf, fn = bt.STRATEGIES[sid]
    wants = "symbol" in inspect.signature(fn).parameters
    try:
        return fn(bars, t_i, spread, symbol) if wants else fn(bars, t_i, spread)
    except Exception as e:  # noqa: BLE001
        log.warning("[soak] %s signal error: %s", sid, e)
        return None


def _write_state(book: _Book, roster: list[dict]) -> None:
    strat_metrics = {}
    for r in roster:
        sid = r["strategy_id"]
        m = book.metrics(sid)
        try:
            dep = datetime.fromisoformat(r.get("deployed_at"))
            days = round((datetime.now(timezone.utc) - dep).total_seconds() / 86400, 2)
        except Exception:
            days = 0.0
        m["days"] = days
        m["deployed_at"] = r.get("deployed_at")
        strat_metrics[sid] = m
    state = {"updated_at": _now(), "strategies": strat_metrics,
             "roster": [r["strategy_id"] for r in roster]}
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def loop_once(book: _Book, last_bar: dict) -> None:
    roster = _read_roster()
    if any(r["strategy_id"] not in bt.STRATEGIES for r in roster):
        bt.refresh_generated()  # pick up strategies codegen'd after this process started
    for r in roster:
        sid = r["strategy_id"]
        if sid not in bt.STRATEGIES:
            continue
        _apply_config(sid, r.get("config_path", ""))
        tf = r.get("timeframe") or bt.STRATEGIES[sid][0]
        for sym in r.get("symbols", []):
            bars = bt._fetch_bars(sym, tf, 320)
            if not bars or not bars.get("close") or len(bars["close"]) < 80:
                continue
            times = bars["time"]
            key = f"{sym}:{sid}:{tf}"
            newbar = last_bar.get(key) != times[-1]
            # Tick open trades with the latest bar each loop.
            book.tick(sym, bars["high"][-1], bars["low"][-1])
            if newbar:
                last_bar[key] = times[-1]
                if not book.has_pending(sym, sid):
                    spread = bt.TYPICAL_SPREADS.get(sym, 0.0001)
                    sig = _eval_signal(sid, bars, len(bars["close"]) - 1, spread, sym)
                    if sig and sig.get("signal") in ("BUY", "SELL"):
                        entry = bars["close"][-1]
                        sl, tp = sig.get("sl"), sig.get("tp")
                        ok = (sl and tp and (
                            (sig["signal"] == "BUY" and sl < entry < tp) or
                            (sig["signal"] == "SELL" and tp < entry < sl)))
                        if ok:
                            book.open(sym, sid, sig["signal"], entry, sl, tp)
    _write_state(book, roster)


def main() -> None:
    FACTORY_DIR.mkdir(parents=True, exist_ok=True)
    book = _Book()
    last_bar: dict = {}
    log.info("Factory paper-soak runner started; roster=%d",
             len(_read_roster()))
    _write_state(book, _read_roster())  # heartbeat immediately
    while True:
        try:
            loop_once(book, last_bar)
        except Exception as e:  # noqa: BLE001
            log.error("soak loop error: %s", e)
            STATE_PATH.write_text(json.dumps({"updated_at": _now(), "error": str(e)[:200]}),
                                  encoding="utf-8")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
