"""Builds shared MarketContext JSON — the standardized input to all Layer 2 strategy agents."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

BD_TZ = ZoneInfo("Asia/Dhaka")


class MarketContext:
    """Holds one complete market snapshot for a single symbol."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.timestamp = datetime.now(tz=BD_TZ).isoformat()
        self.price: dict = {}
        self.ohlcv: dict = {}     # raw bars, NOT included in to_dict() for strategy engine
        self.session: dict = {}
        self.market: dict = {}    # market_structure output
        self.smc: dict = {}
        self.momentum: dict = {}
        self.news: dict = {}
        self.risk: dict = {}
        self._built_ms = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialized context for strategy rule engine and Master Agent prompt."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "price": self.price,
            "session": self.session,
            "market": self.market,
            "smc": self.smc,
            "momentum": self.momentum,
            "news": self.news,
            "risk": self.risk,
            "_built_ms": round(self._built_ms, 1),
        }

    @classmethod
    def mock(cls, symbol: str = "XAUUSD", price: float = 3280.0) -> "MarketContext":
        """Create a mock context for offline testing."""
        ctx = cls(symbol)
        ctx.price = {"bid": price - 0.3, "ask": price + 0.3, "spread": 0.6, "mid": price}
        ctx.ohlcv = {"open": [price] * 50, "high": [price * 1.001] * 50,
                     "low": [price * 0.999] * 50, "close": [price] * 50, "volume": [1000] * 50}
        ctx.session = {"name": "london_kz", "active": True, "primary": True}
        ctx.market = {"trend": "BULLISH", "bos": True, "choch": False, "mss": False}
        ctx.smc = {"sweep_detected": False, "in_ote": False}
        ctx.momentum = {"atr": 3.5, "rsi": 45.0, "ha_bull": True, "adx": 28.0, "volatility": "NORMAL"}
        ctx.news = {"blocked": False, "next_event_mins": 120}
        ctx.risk = {"daily_dd_pct": 0.0, "can_trade": True, "open_trades": 0}
        return ctx


async def build_context(
    symbol: str,
    price: dict,
    ohlcv: dict,
    risk_state: dict,
    l1_agents: list,
) -> MarketContext:
    """Run all L1 agents in parallel and assemble the full MarketContext."""
    t0 = time.perf_counter()
    ctx = MarketContext(symbol)
    ctx.price = price
    ctx.ohlcv = ohlcv

    # Seed context with OHLCV so agents can access it
    raw = {"symbol": symbol, "price": price, "ohlcv": ohlcv, "risk": risk_state}

    # Run momentum first (market_structure needs ATR from momentum)
    from trading_agents.jtcc.agents.momentum_agent import MomentumAgent
    from trading_agents.jtcc.agents.session_agent import SessionAgent
    from trading_agents.jtcc.agents.news_guard import NewsGuardAgent
    from trading_agents.jtcc.agents.market_structure import MarketStructureAgent
    from trading_agents.jtcc.agents.smc_ict_agent import SmcIctAgent

    momentum_agent = next((a for a in l1_agents if isinstance(a, MomentumAgent)), MomentumAgent())
    session_agent = next((a for a in l1_agents if isinstance(a, SessionAgent)), SessionAgent())
    news_agent = next((a for a in l1_agents if isinstance(a, NewsGuardAgent)), NewsGuardAgent())
    ms_agent = next((a for a in l1_agents if isinstance(a, MarketStructureAgent)), MarketStructureAgent())
    smc_agent = next((a for a in l1_agents if isinstance(a, SmcIctAgent)), SmcIctAgent())

    # Run momentum + session + news in parallel first
    momentum, session, news = await asyncio.gather(
        momentum_agent.analyze(raw),
        session_agent.analyze(raw),
        news_agent.analyze(raw),
    )
    ctx.momentum = momentum
    ctx.session = session
    ctx.news = news

    # Then market_structure (needs momentum.atr) + smc in parallel
    raw_with_momentum = {**raw, "momentum": momentum}
    market_struct, smc = await asyncio.gather(
        ms_agent.analyze(raw_with_momentum),
        smc_agent.analyze(raw_with_momentum),
    )
    ctx.market = market_struct
    ctx.smc = smc
    ctx.risk = risk_state

    ctx._built_ms = (time.perf_counter() - t0) * 1000
    return ctx
