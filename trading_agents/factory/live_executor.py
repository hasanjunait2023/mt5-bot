"""Factory Live Executor — the graduate-to-live path for the strategy factory.

When a factory job clears GATE_LIVE (you approve real money in /factory), this
service starts trading that strategy on the DEMO account with REAL bridge orders —
the first time a candidate sees real fills/spread/slippage rather than the paper
soak's bar-simulation. Three safety layers:

  1. SAFE BY DEFAULT — places NO orders unless FACTORY_LIVE_EXECUTOR=1. Otherwise it
     runs in DRY mode: logs every intended order, touches nothing. So deploying it is
     harmless; you flip the env on only when you want approved strategies live.
  2. PROBATION SIZE — trades at FACTORY_LIVE_RISK_PCT (default 0.25%), a quarter of a
     normal agent, until you scale it up by hand.
  3. AUTO-ROLLBACK — once a strategy has FACTORY_ROLLBACK_MIN_TRADES real closes, if
     its live profit factor is below FACTORY_ROLLBACK_PF it is halted (stops trading,
     pages you once). A graduated strategy that fails live cannot keep bleeding.

It also honours the shared per-agent daily-DD halt (risk_limits) across all factory
magics, and heartbeats _live_executor_state.json for the orchestrator + dashboard.

Roster = factory jobs with status DONE and approvals.live == approved. Each gets a
stable magic from the FACTORY_EXEC band (magic_registry). Managed as the
`factory_executor` service.

Usage:
  python -m trading_agents.factory.live_executor            # loop (DRY unless env=1)
  python -m trading_agents.factory.live_executor --once     # single pass
"""
from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from trading_agents.factory import state as st
from trading_agents.magic_registry import FACTORY_EXEC_BASE, FACTORY_EXEC_MAX

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("factory.executor")

STATE_PATH = st.FACTORY_DIR / "_live_executor_state.json"
HALT_PATH = st.FACTORY_DIR / "_live_executor_halts.json"
POLL_S = 30

LIVE = os.getenv("FACTORY_LIVE_EXECUTOR", "0").strip().lower() in ("1", "true", "yes", "on")
RISK_PCT = float(os.getenv("FACTORY_LIVE_RISK_PCT", "0.25"))
ROLLBACK_MIN_TRADES = int(os.getenv("FACTORY_ROLLBACK_MIN_TRADES", "15"))
ROLLBACK_PF = float(os.getenv("FACTORY_ROLLBACK_PF", "0.9"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents import telegram_hq
        telegram_hq.send("ceo", msg, level=level)
    except Exception:
        pass


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


# ── Roster: approved + graduated jobs → stable magic ──────────────────────────

def _build_roster() -> list[dict]:
    """Jobs that cleared GATE_LIVE (status DONE, live approved). Assign each a stable
    magic from the FACTORY_EXEC band, persisted so it never shifts."""
    halts = set(_read_json(HALT_PATH, {}).get("halted", []))
    assigned = _read_json(STATE_PATH, {}).get("magics", {})  # job_id -> magic
    roster = []
    used = set(int(m) for m in assigned.values())
    for summ in st.list_jobs():
        job = st.load_job(summ["job_id"])
        if not job or job.get("status") != st.DONE:
            continue
        if (job.get("approvals", {}).get("live", {}).get("state")) != "approved":
            continue
        sid = job.get("strategy_id")
        if not sid:
            continue
        jid = job["job_id"]
        magic = int(assigned.get(jid, 0))
        if not magic:
            magic = next((m for m in range(FACTORY_EXEC_BASE, FACTORY_EXEC_MAX + 1) if m not in used),
                         None)
            if magic is None:
                log.error("factory magic band exhausted — skip %s", jid)
                continue
            used.add(magic)
        spec = {}
        sp = job.get("artifacts", {}).get("merged_spec")
        if sp and Path(sp).exists():
            spec = _read_json(Path(sp), {})
        roster.append({
            "job_id": jid, "strategy_id": sid, "magic": magic,
            "symbols": spec.get("symbols") or ["XAUUSD"],
            "title": job.get("source", {}).get("title", sid),
            "halted": sid in halts,
        })
    return roster


# ── Order placement (parametrized magic; mirrors scalp/agent proven path) ─────

def _calc_lots(mt5, symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    acc = mt5.account_info()
    sym = mt5.symbol_info(symbol)
    if acc is None or sym is None:
        return 0.0
    risk_usd = acc.equity * risk_pct / 100.0
    sl_dist = abs(entry - stop)
    if sl_dist < sym.point or sym.trade_tick_size <= 0:
        return 0.0
    value_lot = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0:
        return 0.0
    lots = risk_usd / value_lot
    lots = round(lots / sym.volume_step) * sym.volume_step
    max_allowed = (acc.equity * 0.02) / value_lot
    return round(max(sym.volume_min, min(lots, sym.volume_max, max_allowed)), 2)


def _place(mt5, symbol: str, side: str, stop: float, tp: float, magic: int, sid: str) -> bool:
    tick = mt5.symbol_info_tick(symbol)
    sym = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return False
    digits = sym.digits
    live_entry = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    if abs(live_entry - stop) < sym.point * 5:
        log.warning("%s/%s SL too tight — skip", symbol, sid)
        return False
    lots = _calc_lots(mt5, symbol, live_entry, stop, RISK_PCT)
    if lots <= 0:
        log.warning("%s/%s lot=0 — skip", symbol, sid)
        return False

    if not LIVE:
        log.info("[DRY] would place %s %s/%s @ %.5f SL=%.5f TP=%.5f lots=%.2f magic=%d",
                 side, symbol, sid, live_entry, stop, tp, lots, magic)
        return False

    fm = int(getattr(sym, "filling_mode", 0) or 0)
    if fm & 1:
        fills = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2:
        fills = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fills = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
        "type": order_type, "price": live_entry, "sl": round(stop, digits),
        "tp": round(tp, digits), "deviation": 10, "magic": magic,
        "comment": f"Factory_{sid}"[:31], "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": fills[0],
    }
    res = mt5.order_send(req)
    fi = 1
    while (res is None or getattr(res, "retcode", 0) == 10030) and fi < len(fills):
        req["type_filling"] = fills[fi]; fi += 1
        res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("LIVE ORDER %s %s/%s @ %.5f SL=%.5f TP=%.5f lots=%.2f magic=%d",
                 side, symbol, sid, live_entry, stop, tp, lots, magic)
        _notify(f"🚀 Factory LIVE {sid} {side} {symbol} @ {live_entry:.5f} "
                f"SL={stop:.5f} TP={tp:.5f} lots={lots} (probation {RISK_PCT}%)")
        return True
    log.error("%s/%s order FAILED retcode=%s", symbol, sid, getattr(res, "retcode", None))
    return False


# ── Live per-strategy metrics + rollback ──────────────────────────────────────

def _live_metrics(mt5, magic: int) -> dict:
    """Realized PF/WR/trades for this magic over the last 30 days."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=30), now) or ()
    closes = [d for d in deals if int(getattr(d, "magic", -1)) == magic
              and int(getattr(d, "entry", -1)) == 1]
    if not closes:
        return {"trades": 0, "pf": 0.0, "wr": 0.0, "net": 0.0}
    pnls = [float(getattr(d, "profit", 0)) + float(getattr(d, "swap", 0))
            + float(getattr(d, "commission", 0)) for d in closes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gl = abs(sum(losses)) or 1e-9
    return {"trades": len(pnls), "pf": round(sum(wins) / gl, 2),
            "wr": round(len(wins) / len(pnls) * 100, 1), "net": round(sum(pnls), 2)}


def _persist_halt(sid: str) -> None:
    h = _read_json(HALT_PATH, {"halted": []})
    if sid not in h["halted"]:
        h["halted"].append(sid)
        HALT_PATH.write_text(json.dumps(h, indent=2), encoding="utf-8")


# ── One pass ───────────────────────────────────────────────────────────────────

def loop_once(mt5, last_bar: dict) -> dict:
    from trading_agents.scalp import backtest as bt
    bt.refresh_generated()
    roster = _build_roster()
    magics = [r["magic"] for r in roster]

    # Shared daily-DD halt across all factory magics.
    halted_dd = False
    try:
        from trading_agents.risk_limits import agent_dd_breached, daily_dd_usd_limit
        if magics:
            halted_dd, loss = agent_dd_breached(mt5, magics)
            if halted_dd:
                log.warning("factory daily DD $%.2f >= $%.2f — halt all this cycle",
                            loss, daily_dd_usd_limit())
    except Exception as e:
        log.debug("dd check skipped: %s", e)

    out = {}
    for r in roster:
        sid, magic = r["strategy_id"], r["magic"]
        m = _live_metrics(mt5, magic)
        # Rollback: enough real closes + weak live PF → halt for good.
        if not r["halted"] and m["trades"] >= ROLLBACK_MIN_TRADES and m["pf"] < ROLLBACK_PF:
            _persist_halt(sid)
            r["halted"] = True
            log.warning("ROLLBACK %s: live PF %.2f over %d trades < %.2f — halted",
                        sid, m["pf"], m["trades"], ROLLBACK_PF)
            _notify(f"⛔ Factory ROLLBACK: {sid} halted — live PF {m['pf']} over "
                    f"{m['trades']} trades < {ROLLBACK_PF}. Stopped trading it.", level="WARNING")

        out[sid] = {**m, "magic": magic, "job_id": r["job_id"], "halted": r["halted"], "title": r["title"]}

        if r["halted"] or halted_dd or sid not in bt.STRATEGIES:
            continue
        tf = bt.STRATEGIES[sid][0]
        for sym in r["symbols"]:
            try:
                bars = bt._fetch_bars(sym, tf, 320)
                if not bars or len(bars.get("close", [])) < 80:
                    continue
                key = f"{sym}:{sid}"
                if last_bar.get(key) == bars["time"][-1]:
                    continue
                last_bar[key] = bars["time"][-1]
                # Already in a position for this magic+symbol?
                pos = mt5.positions_get(symbol=sym, magic=magic) or ()
                if pos:
                    continue
                fn = bt.STRATEGIES[sid][1]
                wants = "symbol" in inspect.signature(fn).parameters
                spread = bt.TYPICAL_SPREADS.get(sym, 0.0001)
                sig = fn(bars, len(bars["close"]) - 1, spread, sym) if wants else fn(bars, len(bars["close"]) - 1, spread)
                if sig and sig.get("signal") in ("BUY", "SELL"):
                    _place(mt5, sym, sig["signal"], sig["sl"], sig["tp"], magic, sid)
            except Exception as e:  # noqa: BLE001
                log.warning("%s/%s exec error: %s", sid, sym, e)
    _write_state(out)
    return out


def _write_state(strategies: dict) -> None:
    # Persist job_id→magic so each graduated strategy keeps a stable magic across cycles.
    jobmap = {s["job_id"]: s["magic"] for s in strategies.values() if s.get("job_id")}
    state = {
        "updated_at": _now(),
        "mode": "LIVE" if LIVE else "DRY",
        "risk_pct": RISK_PCT,
        "rollback": {"min_trades": ROLLBACK_MIN_TRADES, "pf": ROLLBACK_PF},
        "strategies": strategies,
        "magics": jobmap,
        "count": len(strategies),
    }
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _connect():
    from mt5_bridge import bridge_client as mt5
    wait = int(os.getenv("MT5_BRIDGE_WAIT_SEC", "60"))
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            if mt5.initialize() and mt5.account_info() is not None:
                acc = mt5.account_info()
                log.info("bridge up: #%s equity $%.2f | mode=%s risk=%.2f%%",
                         acc.login, acc.equity, "LIVE" if LIVE else "DRY", RISK_PCT)
                return mt5
        except Exception as e:
            log.debug("connect retry: %s", e)
        time.sleep(3)
    log.warning("bridge not ready after %ds — will retry in loop", wait)
    return mt5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    log.info("Factory Live Executor — mode=%s (set FACTORY_LIVE_EXECUTOR=1 for real orders)",
             "LIVE" if LIVE else "DRY")
    mt5 = _connect()
    last_bar: dict = {}
    if args.once:
        out = loop_once(mt5, last_bar)
        print(json.dumps(out, indent=2))
        return
    while True:
        try:
            loop_once(mt5, last_bar)
        except Exception as e:  # noqa: BLE001
            log.error("executor loop error: %s", e)
            try:
                mt5 = _connect()
            except Exception:
                pass
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
