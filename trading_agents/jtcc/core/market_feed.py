"""Layer 0: Market feed — FMP REST API for OHLCV bars, _live_state.json polling for price/account."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger("jtcc.market_feed")

BASE_DIR = Path(__file__).parent.parent.parent.parent

# FMP timeframe mapping: config.yaml key → FMP API path segment
FMP_TF = {
    "1min": "1min", "M1": "1min",
    "3min": "5min", "M3": "5min",   # FMP doesn't support M3 → fallback to 5min via FMP, M3 comes from MT5 bridge
    "5min": "5min", "M5": "5min",
    "15min": "15min", "M15": "15min",
    "1hour": "1hour", "H1": "1hour",
    "4hour": "4hour", "H4": "4hour",
    "1day": "daily", "D1": "daily",
}

_ohlcv_cache: dict[str, dict] = {}  # symbol → {tf → bars_dict}


def _fmp_symbol(symbol: str) -> str:
    """MT5 symbol → FMP symbol (XAUUSD → XAUUSD, BTCUSD → BTCUSD)."""
    return symbol  # FMP uses same format for metals/forex/crypto


def _fetch_bars_mt5(symbol: str, timeframe: str = "5min", limit: int = 200) -> dict | None:
    """Fallback: try fetching bars from MT5 bridge directly."""
    try:
        from trading_agents.jtcc.execution.mt5_client import _request, _breaker_check
        if _breaker_check():
            return None
        result = _request("GET", f"/bars/{symbol}",
                          params={"timeframe": timeframe, "limit": limit})
        if isinstance(result, dict) and result.get("open"):
            return result
    except Exception as e:
        log.debug("MT5 bridge bars fallback failed for %s: %s", symbol, e)
    return None


def _fetch_bars(symbol: str, timeframe: str = "5min", limit: int = 200) -> dict | None:
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        # Try MT5 bridge fallback
        mt5_bars = _fetch_bars_mt5(symbol, timeframe, limit)
        if mt5_bars:
            return mt5_bars
        log.warning("FMP_API_KEY not set and MT5 fallback failed — no bars for %s", symbol)
        return None
    tf_path = FMP_TF.get(timeframe, "5min")
    fmp_sym = _fmp_symbol(symbol)
    headers = {"apikey": api_key}
    if tf_path == "daily":
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{fmp_sym}?timeseries={limit}"
    else:
        url = f"https://financialmodelingprep.com/api/v3/historical-chart/{tf_path}/{fmp_sym}?limit={limit}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "historical" in data:
            bars = data["historical"][::-1]  # oldest first
        elif isinstance(data, list):
            bars = data[::-1]
        else:
            return None

        opens = [b.get("open", 0) for b in bars]
        highs = [b.get("high", 0) for b in bars]
        lows = [b.get("low", 0) for b in bars]
        closes = [b.get("close", 0) for b in bars]
        volumes = [b.get("volume", 0) for b in bars]
        times = [b.get("date", "") for b in bars]
        return {"open": opens, "high": highs, "low": lows, "close": closes,
                "volume": volumes, "time": times}
    except Exception as e:
        log.error("FMP fetch failed %s %s: %s — trying MT5 fallback", symbol, timeframe, e)
        return _fetch_bars_mt5(symbol, timeframe, limit)


def _read_live_state() -> dict:
    state_path = BASE_DIR / "mt5_bridge" / "_live_state.json"
    try:
        if state_path.exists():
            return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _extract_price(state: dict, symbol: str) -> dict:
    """Extract bid/ask. Prefers MT5 bridge live tick; falls back to _live_state.json."""
    # First try MT5 bridge for live tick
    try:
        from trading_agents.jtcc.execution.mt5_client import _request, _breaker_check
        if not _breaker_check():
            t = _request("GET", f"/tick/{symbol}")
            if isinstance(t, dict) and t.get("bid"):
                bid = float(t["bid"])
                ask = float(t["ask"])
                return {"bid": bid, "ask": ask,
                        "spread": round(ask - bid, 5),
                        "mid": round((bid + ask) / 2, 5)}
    except Exception:
        pass
    # Fallback to _live_state.json
    last_signals = state.get("last_signals", {})
    sig = last_signals.get(symbol, {})
    bid = sig.get("price", sig.get("bid", 0.0))
    ask = sig.get("ask", bid)
    spread = round(ask - bid, 5) if ask > bid else 0.0
    return {"bid": bid, "ask": ask, "spread": spread, "mid": round((bid + ask) / 2, 5)}


def _extract_risk_state(state: dict) -> dict:
    account = state.get("account", {})
    equity = account.get("equity", account.get("balance", 0))
    balance = account.get("balance", equity)
    daily_pnl = state.get("daily_pnl", 0.0)
    daily_dd_pct = abs(daily_pnl / balance * 100) if balance > 0 and daily_pnl < 0 else 0.0
    positions = state.get("positions", [])
    return {
        "equity": equity,
        "balance": balance,
        "daily_pnl": daily_pnl,
        "daily_dd_pct": round(daily_dd_pct, 2),
        "can_trade": daily_dd_pct < 6.0,
        "open_trades": len(positions),
        "positions": positions,
    }


class MarketFeed:
    """Polls _live_state.json for price/account data and FMP for OHLCV bars."""

    def __init__(self, symbols: list[str], poll_interval_s: float = 1.0,
                 bar_timeframe: str = "5min", bar_limit: int = 200) -> None:
        self.symbols = symbols
        self.poll_interval_s = poll_interval_s
        self.bar_timeframe = bar_timeframe
        self.bar_limit = bar_limit
        self._running = False
        self._on_tick: list[Callable] = []
        self._on_bar_close: list[Callable] = []
        self._last_bar_time: dict[str, str] = {}
        self._bars: dict[str, dict] = {}

    def on_tick(self, fn: Callable) -> None:
        self._on_tick.append(fn)

    def on_bar_close(self, fn: Callable) -> None:
        self._on_bar_close.append(fn)

    async def fetch_bars(self, symbol: str, timeframe: str | None = None) -> dict | None:
        tf = timeframe or self.bar_timeframe
        bars = await asyncio.to_thread(_fetch_bars, symbol, tf, self.bar_limit)
        if bars:
            self._bars[f"{symbol}_{tf}"] = bars
        return bars

    def get_bars(self, symbol: str, timeframe: str | None = None) -> dict | None:
        tf = timeframe or self.bar_timeframe
        return self._bars.get(f"{symbol}_{tf}")

    async def _refresh_bars(self) -> None:
        tasks = [self.fetch_bars(sym) for sym in self.symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self) -> None:
        self._running = True
        log.info("MarketFeed started — symbols: %s", self.symbols)
        # Initial bar fetch + fire on_bar_close for each symbol with valid bars
        await self._refresh_bars()
        log.info("Initial bar fetch complete — %d symbols loaded", len([s for s in self.symbols if self.get_bars(s)]))
        initial_state = await asyncio.to_thread(_read_live_state)
        initial_risk = _extract_risk_state(initial_state)
        for sym in self.symbols:
            bars = self.get_bars(sym)
            if bars and bars.get("time"):
                self._last_bar_time[sym] = bars["time"][-1]
                log.info("Initial bar_close for %s — %d bars, last close: %s",
                         sym, len(bars["close"]), bars["close"][-1])
                for fn in self._on_bar_close:
                    try:
                        await fn(symbol=sym, timeframe=self.bar_timeframe,
                                 ohlcv=bars, risk=initial_risk)
                    except Exception as e:
                        log.error("Initial bar_close handler for %s failed: %s", sym, e)
        tick_count = 0
        bar_refresh_every = max(1, int(60 / self.poll_interval_s))  # refresh bars every ~60s
        while self._running:
            try:
                state = await asyncio.to_thread(_read_live_state)
                risk = _extract_risk_state(state)
                for sym in self.symbols:
                    price = _extract_price(state, sym)
                    if price["bid"] > 0:
                        for fn in self._on_tick:
                            await fn(symbol=sym, price=price, risk=risk, raw_state=state)
                # Refresh bars periodically
                tick_count += 1
                if tick_count % bar_refresh_every == 0:
                    await self._refresh_bars()
                    for sym in self.symbols:
                        bars = self.get_bars(sym)
                        if bars and bars.get("time"):
                            last_t = bars["time"][-1]
                            if self._last_bar_time.get(sym) != last_t:
                                self._last_bar_time[sym] = last_t
                                for fn in self._on_bar_close:
                                    await fn(symbol=sym, timeframe=self.bar_timeframe,
                                             ohlcv=bars, risk=risk)
            except Exception as e:
                log.error("MarketFeed loop error: %s", e)
            await asyncio.sleep(self.poll_interval_s)

    def stop(self) -> None:
        self._running = False
        log.info("MarketFeed stopped")
