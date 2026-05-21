"""Iconic Trader (Urban Forex) confluence engine — Phase 1.

The measurable A/B/C confluence layer of Navin Prithyani's Iconic Trader
method: Volume Pop (tick-volume + 20-MA) + Purpose (session open / orange-red
G7 news) + D1 currency-strength correlation. Pattern detection (Set 1/2,
Test 1/2, money spot) is Phase 2 and lives elsewhere.

Consumes the same {snapshot, strength} contract that SignalEngine feeds Alpha
Desk, so it can be wired into SignalEngine._scan_once with zero extra MT5
fetches. See urbanforex_iconic_trader_PLAN.md for the full spec.

Status: Phase 1 (confluence layer) built + self-tested. Not yet wired into the
live scan or dashboard. Run `python -m trading_agents.iconic.confluence` for the
self-test.
"""

from .confluence import IconicConfluenceScorer, IconicScore
from .correlation import to_scale7, correlation_tier, pair_strength, split_pair
from .purpose import PurposeGate, NewsProvider
from .pattern import detect_setup, Setup, find_pivots
from .engine import IconicEngine, IconicTradeSignal
from . import volume, pattern

__all__ = [
    "IconicConfluenceScorer", "IconicScore",
    "to_scale7", "correlation_tier", "pair_strength", "split_pair",
    "PurposeGate", "NewsProvider",
    "detect_setup", "Setup", "find_pivots",
    "IconicEngine", "IconicTradeSignal",
    "volume", "pattern",
]
