"""ALPHA DESK — institutional confluence signal system.

Stacks 6 analysis layers on top of every per-tick MT5 snapshot:
  1. Trend / momentum            (from SignalEngine snapshots)
  2. Supply / demand zones        (alpha_desk.zones)
  3. Liquidity pools              (alpha_desk.liquidity)
  4. Sweep detection              (alpha_desk.confluence)
  5. Order flow / absorption      (alpha_desk.orderflow)
  6. Session context              (alpha_desk.sessions)

Emits to dedicated Telegram topics and writes JSONL events so the dashboard
Desk View can render zones + liquidity + bias next to the user's TradingView.
"""

from .engine import AlphaDeskEngine
from .zones import ZoneTracker, Zone
from .liquidity import LiquidityTracker, Pool
from .orderflow import OrderFlowDetector
from .sessions import current_session, session_label, SessionName
from .confluence import ConfluenceScorer, AlphaSignal
from .reports import generate_session_brief

__all__ = [
    "AlphaDeskEngine", "ZoneTracker", "Zone",
    "LiquidityTracker", "Pool", "OrderFlowDetector",
    "current_session", "session_label", "SessionName",
    "ConfluenceScorer", "AlphaSignal", "generate_session_brief",
]
