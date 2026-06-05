"""Uniform per-agent daily drawdown limit, in account-currency dollars.

Demo testing phase: every live agent halts trading for the rest of the UTC day
once its account-equity drawdown from the day's starting balance reaches a fixed
dollar amount (default $200), replacing the old per-agent percentage stops.

On the shared ~$742 demo account the previous per-agent percentages (5–20%)
mapped to wildly uneven $37–$148 halts that stopped agents far too early for
data gathering. One uniform dollar knob gives every agent comparable room and a
single place to tune.

    AGENT_DAILY_DD_USD   env var (default 200.0)
"""
from __future__ import annotations

import os

DEFAULT_DD_USD = 200.0


def daily_dd_usd_limit() -> float:
    """Current per-agent daily DD limit in dollars (env-overridable)."""
    raw = os.environ.get("AGENT_DAILY_DD_USD")
    if raw is None or raw.strip() == "":
        return DEFAULT_DD_USD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_DD_USD


def dd_usd_breached(start_balance: float, equity: float) -> tuple[bool, float]:
    """ACCOUNT-WIDE day loss (start_balance - equity). DEPRECATED for per-agent
    halts: all live agents share one account, so this makes every agent see the
    same combined drawdown -> the $200 acts as a single pooled limit, not a
    per-agent one. Use agent_dd_breached() instead. Kept only for compatibility."""
    dd_usd = max((start_balance or 0.0) - (equity or 0.0), 0.0)
    return dd_usd >= daily_dd_usd_limit(), dd_usd


def _magic_set(magics) -> set:
    if isinstance(magics, (list, tuple, set, frozenset)):
        return {int(m) for m in magics}
    return {int(magics)}


def agent_daily_loss_usd(mt5, magics) -> float:
    """This agent's OWN net loss today (UTC), in dollars (>= 0), computed from
    ONLY its own trades — realised P&L of today's closed deals + floating P&L of
    open positions, both filtered to the agent's magic number(s). Independent of
    every other agent on the shared account, so a $200 limit is truly per-agent.

    `mt5` is the agent's bridge_client/MetaTrader5 module; `magics` an int or
    iterable of ints (e.g. a desk that runs several strategies)."""
    from datetime import datetime, timezone

    mset = _magic_set(magics)
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    realized = 0.0
    try:
        for d in (mt5.history_deals_get(midnight, now) or ()):
            if int(getattr(d, "magic", -1)) in mset:
                realized += (float(getattr(d, "profit", 0.0))
                             + float(getattr(d, "swap", 0.0))
                             + float(getattr(d, "commission", 0.0)))
    except Exception:
        pass

    floating = 0.0
    try:
        for p in (mt5.positions_get() or ()):
            if int(getattr(p, "magic", -1)) in mset:
                floating += float(getattr(p, "profit", 0.0)) + float(getattr(p, "swap", 0.0))
    except Exception:
        pass

    return max(-(realized + floating), 0.0)


def agent_dd_breached(mt5, magics) -> tuple[bool, float]:
    """(halt, loss_usd) for ONE agent, measured from its own magic(s) only."""
    loss = agent_daily_loss_usd(mt5, magics)
    return loss >= daily_dd_usd_limit(), loss
