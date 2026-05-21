"""Abstract base class for all JTCC Layer 1 analysis agents."""

import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """All L1 agents inherit this. Must return dict in under 50ms. No Claude API calls."""

    name: str = "base"

    def __init__(self) -> None:
        self.log = logging.getLogger(f"jtcc.{self.name}")

    @abstractmethod
    async def analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Analyze market context and return structured output dict."""
        ...

    def _safe(self, fn, *args, default=None, **kwargs):
        """Run fn safely, return default on any exception."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            self.log.debug("safe call failed: %s", e)
            return default
