"""Shared Telegram notifier for all agents.

Thin backward-compatible shim over the Telegram HQ hub. The legacy signature
`notify(message, level)` still works (lands in the Dev Team topic); pass
`category=` to route to a team's own forum topic. See `trading_agents/telegram_hq.py`.
"""

import logging
from typing import Literal

log = logging.getLogger("DevNotifier")


def notify(
    message: str,
    level: Literal["INFO", "WARNING", "CRITICAL"] = "INFO",
    category: str = "dev_team",
    title: str | None = None,
) -> bool:
    try:
        from trading_agents.telegram_hq import send
        return send(category, message, level=level, title=title)
    except Exception as e:
        log.error("Notification failed: %s", e)
        return False
