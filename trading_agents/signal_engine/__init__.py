"""Signal Engine — multi-TF EMA-200 alignment scanner with chart-attached
Telegram alerts and live WebSocket push to the dashboard."""

from .engine import SignalEngine, SIGNAL_TYPES
from .chart import render_signal_chart

__all__ = ["SignalEngine", "SIGNAL_TYPES", "render_signal_chart"]
