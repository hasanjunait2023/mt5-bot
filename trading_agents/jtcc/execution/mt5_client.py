"""HTTP client for VPS2 FastAPI MT5 bridge. Places and manages trades."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger("jtcc.mt5_client")

_DEFAULT_TIMEOUT = 20       # MT5 copy_rates can be slow during broker reconnect
_MAX_RETRIES = 2            # fewer retries — fail fast to unblock queue
_RETRY_DELAY = 1.0

# Circuit breaker state
_breaker_lock = __import__("threading").Lock()
_breaker_state = {"failures": 0, "open_until": 0.0}
_BREAKER_THRESHOLD = 3      # open faster — 3 failures is enough signal
_BREAKER_COOLDOWN = 30      # shorter cooldown — retry sooner


def _breaker_check() -> bool:
    """Returns True if circuit is open (block requests)."""
    with _breaker_lock:
        return time.time() < _breaker_state["open_until"]


def _breaker_record(success: bool) -> None:
    with _breaker_lock:
        if success:
            _breaker_state["failures"] = 0
        else:
            _breaker_state["failures"] += 1
            if _breaker_state["failures"] >= _BREAKER_THRESHOLD:
                _breaker_state["open_until"] = time.time() + _BREAKER_COOLDOWN
                log.error("MT5 bridge circuit breaker OPEN for %ds after %d failures",
                          _BREAKER_COOLDOWN, _breaker_state["failures"])


def _get_bridge_url() -> str:
    return os.getenv("MT5_BRIDGE_URL", "http://localhost:8090").rstrip("/")


def _get_headers() -> dict:
    secret = os.getenv("MT5_BRIDGE_SECRET", "")
    return {"X-API-Key": secret, "Content-Type": "application/json"} if secret else {}


def _request(method: str, path: str, **kwargs) -> dict:
    if _breaker_check():
        raise ConnectionError("MT5 bridge circuit breaker OPEN — cooldown active")

    url = f"{_get_bridge_url()}{path}"
    headers = _get_headers()
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.request(method, url, headers=headers,
                                    timeout=_DEFAULT_TIMEOUT, **kwargs)
            resp.raise_for_status()
            _breaker_record(True)
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            backoff = _RETRY_DELAY * (2 ** attempt)  # exponential: 1s, 2s, 4s
            log.warning("MT5 bridge request failed (attempt %d/%d): %s — backoff %.1fs",
                        attempt + 1, _MAX_RETRIES, e, backoff)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(backoff)
    _breaker_record(False)
    raise ConnectionError(f"MT5 bridge unreachable after {_MAX_RETRIES} attempts: {last_err}")


def breaker_status() -> dict:
    return {
        "open": _breaker_check(),
        "failures": _breaker_state["failures"],
        "cooldown_remaining_s": max(0, _breaker_state["open_until"] - time.time()),
    }


def place_trade(
    symbol: str,
    action: str,       # "BUY" or "SELL"
    lot: float,
    sl: float,
    tp: float,
    magic: int = 20260600,
    comment: str = "JTCC",
    strategy: str = "",
) -> dict[str, Any]:
    payload = {
        "symbol": symbol,
        "action": action,
        "lot": lot,
        "sl": sl,
        "tp": tp,
        "magic": magic,
        "comment": f"{comment}:{strategy}"[:30] if strategy else comment,
    }
    try:
        result = _request("POST", "/trade/open", json=payload)
        log.info("Trade placed: %s %s %.2f lots SL=%.5f TP=%.5f → %s",
                 action, symbol, lot, sl, tp, result.get("ticket", "?"))
        return result
    except Exception as e:
        log.error("place_trade failed: %s", e)
        return {"success": False, "error": str(e)}


def close_trade(ticket: int) -> dict[str, Any]:
    try:
        return _request("POST", "/trade/close", json={"ticket": ticket})
    except Exception as e:
        log.error("close_trade %d failed: %s", ticket, e)
        return {"success": False, "error": str(e)}


def close_all_positions(magic: int | None = None) -> dict[str, Any]:
    payload = {"magic": magic} if magic else {}
    try:
        return _request("POST", "/trade/close_all", json=payload)
    except Exception as e:
        log.error("close_all_positions failed: %s", e)
        return {"success": False, "error": str(e)}


def get_account_info() -> dict[str, Any]:
    try:
        return _request("GET", "/account/info")
    except Exception as e:
        return {"error": str(e)}


def get_open_positions(magic: int | None = None) -> list[dict]:
    params = {"magic": magic} if magic else {}
    try:
        result = _request("GET", "/positions/open", params=params)
        return result if isinstance(result, list) else result.get("positions", [])
    except Exception:
        return []


def ping() -> bool:
    try:
        _request("GET", "/health")
        return True
    except Exception:
        return False
