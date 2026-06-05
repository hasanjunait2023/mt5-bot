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
    """(halt, dd_usd) — dd_usd is the day's loss in dollars (>= 0)."""
    dd_usd = max((start_balance or 0.0) - (equity or 0.0), 0.0)
    return dd_usd >= daily_dd_usd_limit(), dd_usd
