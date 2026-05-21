"""Analytics hub — runs all academic analytics once per cycle, exposes per-symbol view.

Single entry point that the L1 pipeline calls. Fetches D1 bars from MT5 bridge
(academic strategies need daily timeframe per Moskowitz 2012 & Gatev 2006).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from . import tsmom, pairs

log = logging.getLogger("jtcc.analytics.hub")

# D1 bar cache (refresh every 1h — D1 doesn't change intra-bar much)
_D1_CACHE: dict[str, dict] = {}
_D1_CACHE_TTL_S = 3600


def _fetch_d1(symbol: str, limit: int = 300) -> dict | None:
    """Fetch D1 bars from MT5 bridge, with 1h cache."""
    cache_key = f"{symbol}_d1"
    cached = _D1_CACHE.get(cache_key)
    if cached and (time.time() - cached["fetched_at"]) < _D1_CACHE_TTL_S:
        return cached["data"]

    bridge_url = os.getenv("MT5_BRIDGE_URL", "http://localhost:8090")
    try:
        r = requests.get(f"{bridge_url}/bars/{symbol}",
                         params={"timeframe": "1day", "limit": limit},
                         timeout=10)
        r.raise_for_status()
        data = r.json()
        _D1_CACHE[cache_key] = {"data": data, "fetched_at": time.time()}
        return data
    except Exception as e:
        log.debug("D1 fetch failed for %s: %s", symbol, e)
        return None

# Configurable cross-symbol pairs (Gatev distance method)
PAIRS_CONFIG = [
    {"name": "xau_xag", "a": "XAUUSD", "b": "XAGUSD"},  # precious metals
    {"name": "eur_gbp", "a": "EURUSD", "b": "GBPUSD"},  # USD majors
    # Add more here — pairs auto-load
]

# Per-symbol TSMOM tuning (paper: 12mo for FX, 4wk for crypto)
TSMOM_LOOKBACK = {
    "XAUUSD": 252, "XAGUSD": 252,
    "EURUSD": 252, "GBPUSD": 252, "USDJPY": 252,
    "BTCUSD": 28,   # crypto: weekly horizon per Liu-Tsyvinski
}


class AnalyticsHub:
    """Computes TSMOM + pairs analytics. Call once per bar refresh, query per symbol."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def compute_all(self, bars_by_symbol: dict[str, dict] | None = None) -> dict[str, Any]:
        """Build full analytics snapshot.

        TSMOM and Pairs (Gatev) need D1 bars per paper specs. Fetch from bridge
        rather than using the 5min execution feed. The argument is kept for
        backward compatibility — D1 bars are always fetched fresh (cached 1h).
        """
        result: dict[str, Any] = {"by_symbol": {}, "pairs_summary": {}}
        symbols = list(set(list((bars_by_symbol or {}).keys()) +
                           [p["a"] for p in PAIRS_CONFIG] + [p["b"] for p in PAIRS_CONFIG]))
        if not symbols:
            symbols = ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"]

        # Fetch D1 bars for analytics (cached 1h)
        d1_bars: dict[str, dict] = {}
        for sym in symbols:
            d1 = _fetch_d1(sym, limit=300)
            if d1 and d1.get("close"):
                d1_bars[sym] = d1

        # TSMOM per symbol (D1 bars)
        for sym, bars in d1_bars.items():
            closes = bars.get("close", [])
            if not closes:
                continue
            lookback = TSMOM_LOOKBACK.get(sym, 252)
            tsmom_out = tsmom.compute(closes, lookback=lookback)
            result["by_symbol"][sym] = {
                "tsmom": tsmom_out,
                "pairs": [],
            }

        # Pairs analytics (cross-symbol, D1 bars)
        for p in PAIRS_CONFIG:
            a_bars = d1_bars.get(p["a"], {}).get("close", [])
            b_bars = d1_bars.get(p["b"], {}).get("close", [])
            if not a_bars or not b_bars:
                continue
            pair_out = pairs.compute_pair(a_bars, b_bars)
            pair_out["pair_name"] = p["name"]
            pair_out["symbol_a"] = p["a"]
            pair_out["symbol_b"] = p["b"]
            result["pairs_summary"][p["name"]] = pair_out

            # Attach to both legs so a per-symbol context can see the pair signal
            if p["a"] in result["by_symbol"]:
                # When A is the "long" leg, signal_for_a follows long_a logic
                result["by_symbol"][p["a"]]["pairs"].append({
                    **pair_out, "is_a_leg": True,
                    "want_long": pair_out["long_a"],
                    "want_short": pair_out["short_a"],
                })
            if p["b"] in result["by_symbol"]:
                # B is mirror of A
                result["by_symbol"][p["b"]]["pairs"].append({
                    **pair_out, "is_a_leg": False,
                    "want_long": pair_out["short_a"],   # short_a means long_b
                    "want_short": pair_out["long_a"],
                })

        self._cache = result
        return result

    def for_symbol(self, symbol: str) -> dict[str, Any]:
        """Return analytics view for a specific symbol (flat dict for rule engine)."""
        sym_data = self._cache.get("by_symbol", {}).get(symbol, {})
        tsmom_out = sym_data.get("tsmom", {})

        # Flatten pair info into named fields for YAML rule access
        pair_view: dict[str, Any] = {}
        for p in sym_data.get("pairs", []):
            name = p.get("pair_name", "unknown")
            pair_view[name] = {
                "zscore": p.get("zscore", 0.0),
                "want_long": p.get("want_long", False),
                "want_short": p.get("want_short", False),
                "exit_now": p.get("exit_now", False),
                "signal": p.get("signal", "NONE"),
            }

        return {
            "tsmom": tsmom_out,
            "pairs": pair_view,
            "has_pair": bool(pair_view),
        }


# Global singleton
hub = AnalyticsHub()
