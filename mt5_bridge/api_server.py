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
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Optional

import MetaTrader5 as mt5
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("mt5_bridge.api")

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


def _ensure_mt5() -> bool:
    global _initialized
    with _mt5_lock:
        if _initialized:
            return True
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
    if secret and x_api_key != secret:
        raise HTTPException(status_code=401, detail="Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_mt5()
    yield
    if _initialized:
        with _mt5_lock:
            mt5.shutdown()
            log.info("MT5 disconnected")


app = FastAPI(title="MT5 FastAPI Bridge", version="1.0", lifespan=lifespan)


@app.get("/health")
def health(x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    return {"status": "ok" if _ensure_mt5() else "mt5_down",
            "mt5_initialized": _initialized}


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
    limit: int = Query(200, ge=1, le=5000),
    x_api_key: Optional[str] = Header(None),
):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    tf = TF_MAP.get(timeframe)
    if tf is None:
        raise HTTPException(400, f"Invalid timeframe: {timeframe}. Valid: {list(TF_MAP.keys())}")
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, limit)
    if rates is None or len(rates) == 0:
        raise HTTPException(404, f"No bars for {symbol}: {mt5.last_error()}")
    return {
        "symbol": symbol, "timeframe": timeframe, "count": len(rates),
        "open":   [float(r["open"])   for r in rates],
        "high":   [float(r["high"])   for r in rates],
        "low":    [float(r["low"])    for r in rates],
        "close":  [float(r["close"])  for r in rates],
        "volume": [int(r["tick_volume"]) for r in rates],
        "time":   [int(r["time"])     for r in rates],
    }


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
    }


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
        if magic and p.magic != magic:
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
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
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

    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
        "type": close_type, "position": pos.ticket, "price": price,
        "deviation": 20, "magic": pos.magic, "comment": "JTCC_close",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        raise HTTPException(503, f"order_send None: {mt5.last_error()}")
    return {
        "success": result.retcode == mt5.TRADE_RETCODE_DONE,
        "ticket": req.ticket, "retcode": result.retcode, "comment": result.comment,
    }


@app.post("/trade/close_all")
def trade_close_all(magic: Optional[int] = None, x_api_key: Optional[str] = Header(None)):
    _check_auth(x_api_key)
    if not _ensure_mt5():
        raise HTTPException(503, "MT5 not connected")
    positions = mt5.positions_get() or []
    closed, failed = [], []
    for p in positions:
        if magic and p.magic != magic:
            continue
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            failed.append(p.ticket)
            continue
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
            "type": close_type, "position": p.ticket, "price": price,
            "deviation": 20, "magic": p.magic, "comment": "JTCC_close_all",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed.append(p.ticket)
        else:
            failed.append(p.ticket)
    return {"closed": closed, "failed": failed, "total": len(closed) + len(failed)}


def main() -> None:
    import uvicorn
    parser = argparse.ArgumentParser(description="MT5 FastAPI Bridge")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    log.info("Starting MT5 bridge on http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
