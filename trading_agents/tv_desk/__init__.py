"""tv_desk — TradingView-driven analysis agents.

Two scheduled agents that read TradingView directly (via the tradingview-mcp
stdio server), run institutional structure analysis, mark up the chart, and
publish to the dashboard + Telegram:

  - intraday_analyst : once/day (NY-close) → 3 intraday day-trades per symbol
  - session_scalper  : 3×/day (30 min pre-session) → 2-3 scalps for next session

Both reuse the Alpha Desk detector brain (zones/liquidity/orderflow) and the
resilient LLM layer (llm_fallback.chat_resilient). TradingView is the single
data source AND the drawing canvas.
"""

from .config import SYMBOLS, LAYOUT_NAME  # noqa: F401
