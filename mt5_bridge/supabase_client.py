"""
Supabase client helper for mt5_bot trading system.

Usage:
    from mt5_bridge.supabase_client import get_client, push_trade, push_signal, push_log

    supabase = get_client()
    push_trade({"symbol": "XAUUSD", "direction": "buy", ...})
"""

import os
import logging
from typing import Any

log = logging.getLogger(__name__)

# Lazy client — only loads the import when first called
_client = None


def get_client():
    """Return a singleton Supabase client using env credentials."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

    if not url or not key:
        log.warning("SUPABASE_URL or SUPABASE_KEY not set — supabase client disabled")
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        log.info("Supabase client initialized: %s", url)
        return _client
    except Exception as e:
        log.error("Failed to create Supabase client: %s", e)
        return None


def push_trade(trade: dict) -> bool:
    """Insert a trade record into the trades table."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("trades").insert(trade).execute()
        return True
    except Exception as e:
        log.debug("push_trade failed: %s", e)
        return False


def push_signal(signal: dict) -> bool:
    """Insert a signal entry."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("signals").insert(signal).execute()
        return True
    except Exception as e:
        log.debug("push_signal failed: %s", e)
        return False


def push_log(agent: str, level: str, message: str, metadata: dict | None = None) -> bool:
    """Insert an agent log entry."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("agent_logs").insert({
            "agent": agent,
            "level": level,
            "message": message,
            "metadata": metadata or {},
        }).execute()
        return True
    except Exception as e:
        log.debug("push_log failed: %s", e)
        return False


def push_account_snapshot(snapshot: dict) -> bool:
    """Record an account balance/equity snapshot."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("account_snapshots").insert(snapshot).execute()
        return True
    except Exception as e:
        log.debug("push_account_snapshot failed: %s", e)
        return False


def query_trades(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    """Fetch recent trades."""
    client = get_client()
    if not client:
        return []
    try:
        query = client.table("trades").select("*").order("opened_at", desc=True).limit(limit)
        if status:
            query = query.eq("status", status)
        resp = query.execute()
        return resp.data if resp.data else []
    except Exception as e:
        log.debug("query_trades failed: %s", e)
        return []


def get_active_trades() -> list[dict[str, Any]]:
    """Fetch all currently open trades."""
    return query_trades(status="open", limit=100)


def get_risk_config(config_id: str = "default") -> dict | None:
    """Load risk configuration."""
    client = get_client()
    if not client:
        return None
    try:
        resp = client.table("risk_config").select("*").eq("id", config_id).limit(1).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
        return None
    except Exception as e:
        log.debug("get_risk_config failed: %s", e)
        return None
