"""Drop-in MetaTrader5 shim backed by the HTTP bridge (api_server on :8090).

The `MetaTrader5` PyPI package is Windows-only, so agents that `import
MetaTrader5 as mt5` can't run on the Linux VPS. This module exposes the SAME
surface those agents use (constants + the handful of functions: copy_rates_from_pos,
symbol_info, symbol_info_tick, account_info, positions_get, order_send,
history_deals_get, initialize/shutdown/last_error) but every call goes over HTTP
to the bridge — which runs under wine python next to the real terminal.

Swap is mechanical:  `import MetaTrader5 as mt5`  →  `from mt5_bridge import bridge_client as mt5`

Only the subset the live agents (scalp, iconic, mtf_live, signal_engine) actually
touch is implemented. Unsupported attrs raise AttributeError loudly rather than
silently returning wrong data — better to fail fast on money code.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any, Optional

import numpy as np
import requests

# ── Constants (numeric values match the real MetaTrader5 package) ────────────
# Timeframes are the bridge's TF_MAP string keys, so copy_rates_from_pos can pass
# them straight through as the ?timeframe= query param.
TIMEFRAME_M1, TIMEFRAME_M2, TIMEFRAME_M3 = "M1", "M2", "M3"
TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = "M5", "M15", "M30"
TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = "H1", "H4", "D1"

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1
TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 2
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_INVALID_FILL = 10030

_RATES_DTYPE = np.dtype([
    ("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
    ("close", "f8"), ("tick_volume", "i8"), ("spread", "i8"), ("real_volume", "i8"),
])

_last_error: tuple[int, str] = (0, "Success")
_TIMEOUT = 20


def _base() -> str:
    return os.getenv("MT5_BRIDGE_URL", "http://localhost:8090").rstrip("/")


def _headers() -> dict:
    secret = os.getenv("MT5_BRIDGE_SECRET", "")
    return {"X-API-Key": secret} if secret else {}


def _get(path: str, **params) -> Optional[dict]:
    global _last_error
    try:
        r = requests.get(_base() + path, params=params or None,
                         headers=_headers(), timeout=_TIMEOUT)
        if r.status_code >= 400:
            _last_error = (r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001 — surface as mt5-style error
        _last_error = (-1, str(e)[:200])
        return None


def _post(path: str, body: dict) -> Optional[dict]:
    global _last_error
    try:
        r = requests.post(_base() + path, json=body,
                          headers=_headers(), timeout=_TIMEOUT)
        if r.status_code >= 400:
            _last_error = (r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001
        _last_error = (-1, str(e)[:200])
        return None


# ── Lifecycle ────────────────────────────────────────────────────────────────
def initialize(*args, **kwargs) -> bool:
    """Confirm the bridge is reachable — waiting out a short restart window.

    The bridge (wine api_server) occasionally exits and is auto-restarted by the
    orchestrator within ~15-30s. Failing instantly on the first refused
    connection makes a (re)starting trader crash-loop (boot does sys.exit(1))
    and spams "MT5 init failed" alerts for a blip the system already self-heals.
    Instead, poll /health until MT5 is back, bounded by MT5_BRIDGE_WAIT_SEC so a
    genuinely-dead bridge still escalates to the caller. Set the env to 0 to
    restore the old fail-fast behavior.
    """
    deadline = time.monotonic() + float(os.getenv("MT5_BRIDGE_WAIT_SEC", "60"))
    while True:
        h = _get("/health")
        if h and h.get("mt5_initialized"):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def shutdown() -> None:
    return None


def terminal_info():
    """Mimic mt5.terminal_info(); .connected reflects bridge↔MT5 link health."""
    h = _get("/health")
    if not h:
        return None
    return SimpleNamespace(connected=bool(h.get("mt5_initialized")),
                           community_connection=False, trade_allowed=True)


def last_error() -> tuple[int, str]:
    return _last_error


def symbol_select(symbol: str, enable: bool = True) -> bool:
    # The bridge auto-selects symbols on every data call, so this is a no-op
    # that just verifies the symbol resolves.
    return _get(f"/symbol/{symbol}") is not None


# ── Market data ──────────────────────────────────────────────────────────────
def copy_rates_from_pos(symbol: str, timeframe: str, start: int, count: int):
    """Return a numpy structured array (time/open/high/low/close/tick_volume/...)
    exactly like mt5.copy_rates_from_pos, so `pd.DataFrame(rates)` keeps working.
    `start` offset is honored client-side (bridge always returns the latest N)."""
    want = count + max(0, int(start))
    data = _get(f"/bars/{symbol}", timeframe=timeframe, limit=want)
    if not data or not data.get("close"):
        return None
    n = data["count"]
    arr = np.zeros(n, dtype=_RATES_DTYPE)
    arr["time"] = data["time"]
    arr["open"] = data["open"]
    arr["high"] = data["high"]
    arr["low"] = data["low"]
    arr["close"] = data["close"]
    arr["tick_volume"] = data["volume"]
    if start:
        arr = arr[: n - int(start)] if n - int(start) > 0 else arr
    return arr


def symbol_info_tick(symbol: str):
    d = _get(f"/tick/{symbol}")
    if not d:
        return None
    return SimpleNamespace(bid=d["bid"], ask=d["ask"], last=d.get("bid"),
                           time=d["time"], volume=0)


def symbol_info(symbol: str):
    d = _get(f"/tick/{symbol}")  # /tick carries the full contract spec too
    if not d:
        d = _get(f"/symbol/{symbol}")
        if not d:
            return None
    return SimpleNamespace(
        digits=d["digits"], point=d["point"],
        volume_min=d.get("volume_min", d.get("min_lot")),
        volume_max=d.get("volume_max", d.get("max_lot")),
        volume_step=d.get("volume_step", d.get("lot_step")),
        trade_tick_size=d.get("trade_tick_size", d.get("point")),
        trade_tick_value=d.get("trade_tick_value", 1.0),
        trade_contract_size=d.get("trade_contract_size", 100000.0),
        spread=d.get("spread", 0), filling_mode=0,
        visible=d.get("visible", True),
    )


# ── Account / positions ──────────────────────────────────────────────────────
def account_info():
    d = _get("/account/info")
    if not d:
        return None
    return SimpleNamespace(
        login=d["login"], server=d["server"], balance=d["balance"],
        equity=d["equity"], margin=d.get("margin", 0.0),
        margin_free=d.get("margin_free", 0.0), profit=d.get("profit", 0.0),
        leverage=d.get("leverage", 0), currency=d.get("currency", "USD"),
    )


def positions_get(symbol: Optional[str] = None, ticket: Optional[int] = None,
                  magic: Optional[int] = None):
    d = _get("/positions/open", **({"magic": magic} if magic is not None else {}))
    if not d:
        return ()
    out = []
    for p in d.get("positions", []):
        if symbol is not None and p["symbol"] != symbol:
            continue
        if ticket is not None and p["ticket"] != ticket:
            continue
        out.append(SimpleNamespace(
            ticket=p["ticket"], symbol=p["symbol"],
            type=ORDER_TYPE_BUY if p["type"] == "BUY" else ORDER_TYPE_SELL,
            volume=p["volume"], price_open=p["price_open"], sl=p["sl"],
            tp=p["tp"], price_current=p["price_current"], profit=p["profit"],
            swap=p.get("swap", 0.0), magic=p.get("magic", 0),
            comment=p.get("comment", ""), time=p.get("time", 0),
        ))
    return tuple(out)


def history_deals_get(date_from=None, date_to=None, position: Optional[int] = None, **kwargs):
    """mt5-compatible. Either:
      - history_deals_get(position=ticket)        -> deals for one position
      - history_deals_get(date_from, date_to)     -> deals in a unix/datetime range
    """
    if position is not None:
        d = _get(f"/history/deals/{position}")
        if not d:
            return ()
        return tuple(SimpleNamespace(**deal) for deal in d.get("deals", []))
    if date_from is None and date_to is None:
        return ()
    params = {}
    if date_from is not None:
        params["from"] = int(date_from.timestamp()) if hasattr(date_from, "timestamp") else int(date_from)
    if date_to is not None:
        params["to"] = int(date_to.timestamp()) if hasattr(date_to, "timestamp") else int(date_to)
    d = _get("/history/deals", **params)
    if not d:
        return ()
    return tuple(SimpleNamespace(**deal) for deal in d.get("deals", []))


# ── Order execution ──────────────────────────────────────────────────────────
def order_send(request: dict):
    """Translate an mt5 order request dict into a bridge POST. Opens go to
    /trade/open (bridge builds the deal); a request carrying "position" is a
    close → /trade/close. Returns an mt5-style result namespace with .retcode."""
    if request.get("action") == TRADE_ACTION_SLTP and "position" in request:
        # SL/TP modify → /trade/modify (stop-to-zero, trailing)
        body = {"ticket": int(request["position"])}
        if request.get("sl") is not None:
            body["sl"] = float(request["sl"])
        if request.get("tp") is not None:
            body["tp"] = float(request["tp"])
        resp = _post("/trade/modify", body)
    elif "position" in request:
        # close by ticket; carry volume for a partial close
        body = {"ticket": int(request["position"])}
        if request.get("volume"):
            body["volume"] = float(request["volume"])
        resp = _post("/trade/close", body)
    else:
        action = "BUY" if request.get("type") == ORDER_TYPE_BUY else "SELL"
        resp = _post("/trade/open", {
            "symbol": request["symbol"], "action": action,
            "lot": float(request["volume"]),
            "sl": float(request.get("sl", 0.0)),
            "tp": float(request.get("tp", 0.0)),
            "magic": int(request.get("magic", 0)),
            "comment": str(request.get("comment", "")),
            "deviation": int(request.get("deviation", 20)),
        })
    if resp is None:
        # Bridge unreachable / HTTP error — mimic mt5 returning a non-DONE result
        return SimpleNamespace(retcode=-1, order=0, deal=0,
                               comment=str(_last_error[1])[:90],
                               price=0.0, volume=0.0)
    return SimpleNamespace(
        retcode=resp.get("retcode", TRADE_RETCODE_DONE if resp.get("success") else -1),
        order=resp.get("ticket", 0), deal=resp.get("deal", 0),
        comment=resp.get("comment", ""), price=resp.get("price", 0.0),
        volume=resp.get("volume", 0.0),
    )
