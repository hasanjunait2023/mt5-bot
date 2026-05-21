"""asyncio event bus for JTCC agent communication."""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

log = logging.getLogger("jtcc.event_bus")


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable[..., Coroutine]) -> None:
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        self._handlers[event] = [h for h in self._handlers[event] if h != handler]

    async def emit(self, event: str, **data: Any) -> None:
        handlers = self._handlers.get(event, [])
        if not handlers:
            return
        tasks = [asyncio.create_task(h(**data)) for h in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error("event %s handler error: %s", event, r)


# Events emitted by JTCC
ON_TICK = "on_tick"            # data: symbol, bid, ask, time
ON_BAR_CLOSE = "on_bar_close"  # data: symbol, timeframe, ohlcv (dict)
ON_SIGNAL = "on_signal"        # data: signal (dict from rule_engine)
ON_TRADE = "on_trade"          # data: trade result dict
ON_DD_WARNING = "on_dd_warning"  # data: pct
ON_DD_SHUTDOWN = "on_dd_shutdown"  # data: pct
ON_STRATEGY_LOADED = "on_strategy_loaded"  # data: name


bus = EventBus()
