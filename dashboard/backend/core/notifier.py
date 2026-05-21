"""Backend bridge to the Telegram HQ hub.

Adds the project root to sys.path (the hub lives under trading_agents/) and
re-exports it so backend code can `from core.notifier import hq` and call
hq.send / hq.load_config / hq.read_outbox without import-path gymnastics.
"""

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parents[3]      # project root ("mt5 bot/")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("backend.notifier")

try:
    from trading_agents import telegram_hq as hq  # noqa: E402
except Exception as e:                              # pragma: no cover
    hq = None
    log.warning("Telegram HQ hub unavailable: %s", e)


def send(category: str, message: str, level: str = "INFO", title: str | None = None) -> bool:
    """Safe fire-and-forget notify from backend threads — never raises."""
    if hq is None:
        return False
    try:
        return hq.send(category, message, level=level, title=title)
    except Exception as e:
        log.debug("hq.send failed: %s", e)
        return False
