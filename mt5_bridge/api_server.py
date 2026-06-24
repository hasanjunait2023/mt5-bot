"""MT5 FastAPI Bridge — exposes MetaTrader5 terminal as HTTP API for JTCC.

Run:
  python -m mt5_bridge.api_server                    # default port 8090
  python -m mt5_bridge.api_server --port 8090

Endpoints:
  GET  /health                          - ping
  GET  /account/info                    - balance, equity, margin
  GET  /bars/{symbol}?timeframe=&limit= - OHLCV bars
  GET  /tick/{symbol}                   - latest bid/ask
  GET  /positions/open?magic=           - open positions
  POST /trade/open                      - place a trade
  POST /trade/close                     - close by ticket
  POST /trade/close_all?magic=          - close all positions

Auth: optional X-API-Key header (set MT5_BRIDGE_SECRET in env)
"""

from __future__ import annotations

import argparse
import hmac as _hmac
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import MetaTrader5 as mt5
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("mt5_bridge.api")

# Trade journal + magic registry live in trading_agents/. The bridge needs the
# repo root on sys.path (set via PYTHONPATH in the wine launcher, but insert
# defensively for script-mode runs too).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
try:
    from trading_agents import trade_journal as _journal
    from trading_agents import magic_registry as _magic
except Exception as _imp_err:  # pragma: no cover - import guard
    _journal = None
    _magic = None
    log.warning("reconciler disabled — journal import failed: %s", _imp_err)

# Close-reconciler state (exposed via /reconciler/status for the dashboard stamp).
_reconcile_state: dict = {"last_run": None, "closed_total": 0, "last_closed": 0, "enabled": True}

TF_MAP = {
    "1min": mt5.TIMEFRAME_M1, "M1": mt5.TIMEFRAME_M1,
    "2min": mt5.TIMEFRAME_M2, "M2": mt5.TIMEFRAME_M2,
    "3min": mt5.TIMEFRAME_M3, "M3": mt5.TIMEFRAME_M3,
    "5min": mt5.TIMEFRAME_M5, "M5": mt5.TIMEFRAME_M5,
    "15min": mt5.TIMEFRAME_M15, "M15": mt5.TIMEFRAME_M15,
    "30min": mt5.TIMEFRAME_M30, "M30": mt5.TIMEFRAME_M30,
    "1hour": mt5.TIMEFRAME_H1, "H1": mt5.TIMEFRAME_H1,
    "4hour": mt5.TIMEFRAME_H4, "H4": mt5.TIMEFRAME_H4,
    "1day": mt5.TIMEFRAME_D1, "daily": mt5.TIMEFRAME_D1, "D1": mt5.TIMEFRAME_D1,
}

_mt5_lock = threading.Lock()
_initialized = False

# Bar cache: key=(symbol, timeframe, limit) → (timestamp, payload)
# TTL per timeframe keeps stale-data risk < one bar behind.
_bar_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_TF_TTL = {
    "M1": 30, "1min": 30,
    "M2": 60, "2min": 60,
    "M3": 90, "3min": 90,
    "M5": 150, "5min": 150,
    "M15": 300, "15min": 300,
    "M30": 600, "30min": 600,
    "H1": 1800, "1hour": 1800,
    "H4": 7200, "4hour": 7200,
    "D1": 21600, "1day": 21600, "daily": 21600,
}


def _cache_get(key: tuple) -> Optional[dict]:
    with _cache_lock:
        entry = _bar_cache.get(key)
        if entry is None:
            return None
        ts, payload = entry
        tf = key[1]
        ttl = _TF_TTL.get(tf, 60)
        if time.time() - ts > ttl:
            del _bar_cache[key]
            return None
        return payload


def _cache_set(key: tuple, payload: dict) -> None:
    with _cache_lock:
        _bar_cache[key] = (time.time(), payload)
    # Periodic sweep: keep cache under 500 entries
    if len(_bar_cache) > 500:
        with _cache_lock:
            if len(_bar_cache) > 500:
                now = time.time()
                stale = [k for k, v in _bar_cache.items() if now - v[0] > 3600]
                for k in stale:
                    del _bar_cache[k]
                if len(_bar_cache) > 500:
                    sorted_keys = sorted(_bar_cache.keys(), key=lambda k: _bar_cache[k][0])
                    for k in sorted_keys[: len(_bar_cache) - 500]:
                        del _bar_cache[k]


def _ensure_mt5() -> bool:
    global _initialized
    with _mt5_lock:
        if _initialized:
            # `_initialized` only records that we called initialize() once — the
            # link to the terminal/broker can still drop silently. Verify it's
            # actually live and self-heal if it dropped, so the bridge (and every
            # endpoint that gates on this) recovers without a process restart.
            try:
                if mt5.account_info() is not None:
                    return True
            except Exception:
                pass
            log.warning("MT5 link lost (was marked connected) — re-initializing")
            try:
                mt5.shutdown()
            except Exception:
                pass
            _initialized = False
        if mt5.initialize():
            _initialized = True
            info = mt5.account_info()
            if info:
                log.info("MT5 connected: %s @ %s, balance %.2f %s",
                         info.login, info.server, info.balance, info.currency)
            return True
        log.error("MT5 initialize failed: %s", mt5.last_error())
        return False


def _check_auth(x_api_key: Optional[str]) -> None:
    secret = os.getenv("MT5_BRIDGE_SECRET", "")
    if secret and not _hmac.compare_digest((x_api_key or "").encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _reconcile_once() -> int:
    """Find journal-OPEN tickets that are no longer live positions, fetch their
    closing deals from MT5, and append a close event. Idempotent (close_trade
    skips already-closed). Returns number of closes journaled this cycle."""
    if _journal is None or not _ensure_mt5():
        return 0
    open_tickets = _journal.get_open_tickets()
    if not open_tickets:
        return 0
    with _mt5_lock:
        acct = mt5.account_info()
        positions = mt5.positions_get() or []
    login = int(acct.login) if acct else None
    is_demo = (acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO) if acct else None
    live_open = {p.ticket for p in positions}

    _OUT = {mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT, getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)}
    closed_n = 0
    for tk in open_tickets:
        if tk in live_open:
            continue  # still open
        with _mt5_lock:
            deals = mt5.history_deals_get(position=tk)
        if not deals:
            continue  # not yet settled into history — retry next cycle
        out_deals = [d for d in deals if d.entry in _OUT]
        if not out_deals:
            continue  # entry deal only so far
        pnl = sum(d.profit + d.swap + d.commission for d in deals)
        last_out = max(out_deals, key=lambda d: d.time)
        close_time = datetime.fromtimestamp(max(d.time for d in deals), tz=timezone.utc).isoformat()
        reason = getattr(last_out, "reason", None)
        if reason == getattr(mt5, "DEAL_REASON_TP", -98):
            outcome = "TP_HIT"
        elif reason == getattr(mt5, "DEAL_REASON_SL", -99):
            outcome = "SL_HIT"
        else:
            outcome = "CLOSED"
        if _journal.close_trade(tk, last_out.price, round(pnl, 2), outcome,
                                close_time=close_time, account_login=login, demo=is_demo):
            closed_n += 1
    return closed_n


def _reconciler_loop() -> None:
    interval = int(os.getenv("BRIDGE_RECONCILE_INTERVAL", "30"))
    log.info("close-reconciler started (interval=%ss)", interval)
    while True:
        try:
            n = _reconcile_once()
            _reconcile_state["last_run"] = datetime.now(timezone.utc).isoformat()
            _reconcile_state["last_closed"] = n
            _reconcile_state["closed_total"] += n
            if n:
                log.info("reconciler: journaled %d close(s)", n)
        except Exception as e:  # never let the loop die
            log.warning("reconciler cycle error: %s", e)
        time.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_mt5()
    if _journal is not None and os.getenv("BRIDGE_RECONCILE_ENABLED", "1") in ("1", "true", "yes"):
        threading.Thread(target=_reconciler_loop, daemon=True, name="reconciler").start()
    else:
        _reconcile_state["enabled"] = False
    yield
    if _initialized:
        with _mt5_lock:
            mt5.shutdown()
            log.info("MT5 disconnected")


app = FastAPI(title="MT5 FastAPI Bridge", version="1.0", lifespan=lifespan)


@app.get("/health")
def health(x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    with _cache_lock:
        cached_entries = len(_bar_cache)
    ok = _ensure_mt5()
    # trade_allowed mirrors the terminal's "Algo Trading" toggle — when it's OFF
    # every order is rejected with retcode 10027, so surface it for the guard.
    trade_allowed = None
    if ok:
        try:
            ti = mt5.terminal_info()
            trade_allowed = bool(ti.trade_allowed) if ti else None
        except Exception:
            trade_allowed = None
    return {"status": "ok" if ok else "mt5_down",
            "mt5_initialized": _initialized,
            "trade_allowed": trade_allowed,
            "bar_cache_entries": cached_entries}


@app.post("/cache/clear")
def cache_clear(x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    with _cache_lock:
        count = len(_bar_cache)
        _bar_cache.clear()
    log.info("Bar cache cleared (%d entries)", count)
    return {"cleared": count}


@app.get("/account/info")
def account_info(x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    info = mt5.account_info()
    if info is None:
        raise HTTPException(503, f"account_info failed: {mt5.last_error()}")
    return {
        "login": info.login, "broker": info.company, "server": info.server,
        "balance": info.balance, "equity": info.equity, "margin": info.margin,
        "margin_free": info.margin_free, "leverage": info.leverage,
        "currency": info.currency, "profit": info.profit,
    }


@app.get("/bars/{symbol}")
def bars(
    symbol: str,
    timeframe: str = Query("5min"),
    limit: int = Query(200, ge=1, le=200000),  # high cap: backtests pull months of M1/M5 in one call
    x_api_key: Optional[str] = Header(None),
):
    _check_auth(x_api_key)
    tf = TF_MAP.get(timeframe)
    if tf is None:
        raise HTTPException(400, f"Invalid timeframe: {timeframe}. Valid: {list(TF_MAP.keys())}")

    cache_key = (symbol.upper(), timeframe, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, limit)
    if rates is None or len(rates) == 0:
        raise HTTPException(404, f"No bars for {symbol}: {mt5.last_error()}")
    payload = {
        "symbol": symbol, "timeframe": timeframe, "count": len(rates),
        "open":   [float(r["open"])   for r in rates],
        "high":   [float(r["high"])   for r in rates],
        "low":    [float(r["low"])    for r in rates],
        "close":  [float(r["close"])  for r in rates],
        "volume": [int(r["tick_volume"]) for r in rates],
        "time":   [int(r["time"])     for r in rates],
    }
    _cache_set(cache_key, payload)
    return payload


@app.get("/tick/{symbol}")
def tick(symbol: str, x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    mt5.symbol_select(symbol, True)
    t = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if t is None or info is None:
        raise HTTPException(404, f"No tick for {symbol}: {mt5.last_error()}")
    return {
        "symbol": symbol, "bid": t.bid, "ask": t.ask,
        "spread": round((t.ask - t.bid) * (10 ** info.digits), 1),
        "spread_price": round(t.ask - t.bid, info.digits),
        "time": t.time, "digits": info.digits,
        "point": info.point, "min_lot": info.volume_min,
        "max_lot": info.volume_max, "lot_step": info.volume_step,
        # Full symbol contract spec — needed by agents that size lots from tick
        # value (scalp/iconic/mtf). Kept here so a single /tick round-trip gives
        # both the live quote and the sizing inputs.
        "volume_min": info.volume_min, "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "trade_tick_size": info.trade_tick_size,
        "trade_tick_value": info.trade_tick_value,
        "trade_contract_size": info.trade_contract_size,
    }


@app.get("/symbol/{symbol}")
def symbol_spec(symbol: str, x_api_key: Optional[str] = Header(None)):
    """Static-ish contract spec (no live quote). Mirrors mt5.symbol_info()."""
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(404, f"No symbol_info for {symbol}: {mt5.last_error()}")
    return {
        "symbol": symbol, "digits": info.digits, "point": info.point,
        "volume_min": info.volume_min, "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "trade_tick_size": info.trade_tick_size,
        "trade_tick_value": info.trade_tick_value,
        "trade_contract_size": info.trade_contract_size,
        "spread": info.spread,
    }


@app.get("/history/deals/{ticket}")
def history_deals(ticket: int, x_api_key: Optional[str] = Header(None)):
    """Deals for a closed position ticket. Mirrors mt5.history_deals_get(position=)."""
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    deals = mt5.history_deals_get(position=ticket)
    if deals is None:
        return {"deals": []}
    return {"deals": [
        {"ticket": d.ticket, "order": d.order, "time": d.time, "type": d.type,
         "entry": d.entry, "symbol": d.symbol, "volume": d.volume,
         "price": d.price, "profit": d.profit, "commission": d.commission,
         "swap": d.swap, "magic": d.magic, "comment": d.comment}
        for d in deals
    ]}


def _deal_to_dict(d) -> dict:
    return {
        "ticket": d.ticket, "order": d.order, "position_id": d.position_id,
        "time": d.time, "type": d.type, "entry": d.entry, "reason": getattr(d, "reason", None),
        "symbol": d.symbol, "volume": d.volume, "price": d.price,
        "profit": d.profit, "commission": d.commission, "swap": d.swap,
        "magic": d.magic, "comment": d.comment,
    }


@app.get("/history/deals")
def history_deals_range(
    from_: Optional[int] = Query(None, alias="from"),
    to: Optional[int] = None,
    days: Optional[int] = None,
    x_api_key: Optional[str] = Header(None),
):
    """All deals in a unix-time range. Mirrors mt5.history_deals_get(from, to).
    Used by the close-reconciler backfill. `from`/`to` are unix seconds; default =
    last 90 days → now."""
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    now = datetime.now(timezone.utc)
    dt_to = datetime.fromtimestamp(to, tz=timezone.utc) if to else now
    # Honor ?days=N as a convenience window (used by ad-hoc/agent "today" queries).
    # Silently ignoring it returned 90d of history and once looked like a 24h
    # over-trading spike — keep it explicit. `from`/`to` still win when given.
    _win = days if (days and days > 0) else 90
    dt_from = datetime.fromtimestamp(from_, tz=timezone.utc) if from_ else now - timedelta(days=_win)
    with _mt5_lock:
        deals = mt5.history_deals_get(dt_from, dt_to)
    if deals is None:
        return {"deals": [], "count": 0}
    return {"deals": [_deal_to_dict(d) for d in deals], "count": len(deals)}


@app.get("/reconciler/status")
def reconciler_status(x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    return dict(_reconcile_state)


@app.get("/positions/open")
def positions_open(
    magic: Optional[int] = None,
    x_api_key: Optional[str] = Header(None),
):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    positions = mt5.positions_get()
    if positions is None:
        return {"positions": []}
    result = []
    for p in positions:
        if magic is not None and p.magic != magic:
            continue
        result.append({
            "ticket": p.ticket, "symbol": p.symbol,
            "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "volume": p.volume, "price_open": p.price_open,
            "sl": p.sl, "tp": p.tp, "price_current": p.price_current,
            "profit": p.profit, "swap": p.swap, "magic": p.magic,
            "comment": p.comment, "time": p.time,
        })
    return {"positions": result, "count": len(result)}


class TradeOpen(BaseModel):
    symbol: str
    action: str   # "BUY" or "SELL"
    lot: float
    sl: float
    tp: float
    magic: int = 20260600
    comment: str = "JTCC"
    deviation: int = 20


def _send_with_filling(request: dict, symbol: str):
    """Send an order, retrying across filling modes on retcode 10030 (Unsupported
    filling mode). Brokers differ per symbol (IOC/FOK/RETURN); order the attempts
    by the symbol's declared filling_mode bitmask. Centralised here because all
    agents now route order_send through the bridge via the shim."""
    info = mt5.symbol_info(symbol)
    fm = int(getattr(info, "filling_mode", 0) or 0) if info else 0
    if fm & 1:      # SYMBOL_FILLING_FOK
        fills = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2:    # SYMBOL_FILLING_IOC
        fills = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fills = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK]
    result = None
    for i, f in enumerate(fills):
        request["type_filling"] = f
        result = mt5.order_send(request)
        if result is not None and result.retcode != 10030:
            break
    return result


@app.post("/trade/open")
def trade_open(req: TradeOpen, x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")

    mt5.symbol_select(req.symbol, True)
    tick = mt5.symbol_info_tick(req.symbol)
    if tick is None:
        raise HTTPException(503, f"No tick: {mt5.last_error()}")

    order_type = mt5.ORDER_TYPE_BUY if req.action.upper() == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": req.symbol, "volume": req.lot,
        "type": order_type, "price": price, "sl": req.sl, "tp": req.tp,
        "deviation": req.deviation, "magic": req.magic, "comment": req.comment,
        "type_time": mt5.ORDER_TIME_GTC,
    }
    result = _send_with_filling(request, req.symbol)
    if result is None:
        raise HTTPException(503, f"order_send returned None: {mt5.last_error()}")

    success = result.retcode == mt5.TRADE_RETCODE_DONE
    return {
        "success": success, "ticket": result.order, "deal": result.deal,
        "retcode": result.retcode, "comment": result.comment,
        "price": result.price, "volume": result.volume,
    }


class TradeClose(BaseModel):
    ticket: int
    volume: Optional[float] = None    # partial close; None/<=0 → close full position


@app.post("/trade/close")
def trade_close(req: TradeClose, x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")

    positions = mt5.positions_get(ticket=req.ticket)
    if not positions:
        raise HTTPException(404, f"Position {req.ticket} not found")
    pos = positions[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        raise HTTPException(503, f"No tick: {mt5.last_error()}")

    # Partial close: clamp the requested volume to the symbol's step + the
    # position's open volume. None/<=0 or >= open volume → full close.
    vol = float(pos.volume)
    if req.volume and req.volume > 0:
        info = mt5.symbol_info(pos.symbol)
        step = getattr(info, "volume_step", 0.01) or 0.01
        want = round(float(req.volume) / step) * step
        if 0 < want < pos.volume:
            vol = round(want, 2)

    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": vol,
        "type": close_type, "position": pos.ticket, "price": price,
        "deviation": 20, "magic": pos.magic, "comment": "JTCC_close",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    result = _send_with_filling(request, pos.symbol)
    if result is None:
        raise HTTPException(503, f"order_send None: {mt5.last_error()}")
    return {
        "success": result.retcode == mt5.TRADE_RETCODE_DONE,
        "ticket": req.ticket, "closed_volume": vol, "partial": vol < pos.volume,
        "retcode": result.retcode, "comment": result.comment,
    }


class TradeModify(BaseModel):
    ticket: int
    sl: Optional[float] = None
    tp: Optional[float] = None


@app.post("/trade/modify")
def trade_modify(req: TradeModify, x_api_key: Optional[str] = Header(None)):
    """Modify a position's SL/TP (used for stop-to-zero and trailing). Keeps the
    existing level for any field left None."""
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    positions = mt5.positions_get(ticket=req.ticket)
    if not positions:
        raise HTTPException(404, f"Position {req.ticket} not found")
    pos = positions[0]
    new_sl = float(req.sl) if req.sl is not None else float(pos.sl)
    new_tp = float(req.tp) if req.tp is not None else float(pos.tp)
    request = {
        "action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol,
        "position": pos.ticket, "sl": new_sl, "tp": new_tp,
        "magic": pos.magic,
    }
    result = mt5.order_send(request)
    if result is None:
        raise HTTPException(503, f"order_send None: {mt5.last_error()}")
    return {
        "success": result.retcode == mt5.TRADE_RETCODE_DONE,
        "ticket": req.ticket, "sl": new_sl, "tp": new_tp,
        "retcode": result.retcode, "comment": result.comment,
    }


@app.post("/trade/close_all")
def trade_close_all(magic: Optional[int] = None, x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    positions = mt5.positions_get() or []
    closed, failed = [], []
    for p in positions:
        if magic is not None and p.magic != magic:
            continue
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            failed.append(p.ticket)
            continue
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        result = _send_with_filling({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
            "type": close_type, "position": p.ticket, "price": price,
            "deviation": 20, "magic": p.magic, "comment": "JTCC_close_all",
            "type_time": mt5.ORDER_TIME_GTC,
        }, p.symbol)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed.append(p.ticket)
        else:
            failed.append(p.ticket)
    return {"closed": closed, "failed": failed, "total": len(closed) + len(failed)}


def main() -> None:
    import uvicorn
    parser = argparse.ArgumentParser(description="MT5 FastAPI Bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    log.info("Starting MT5 bridge on http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
