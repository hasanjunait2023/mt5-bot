"""Base agent mixin — shared utilities for all trading agents.

New agents should inherit from BaseAgent to get:
- write_state()     : atomic JSON state write with universal schema
- paper_gate_check(): PF + trade count promotion gate
- log_trade()       : trade journal hook
- daily_rollover()  : UTC date-change detection + reset
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("base_agent")


class BaseAgent:
    """Mixin — inherit alongside your agent class or use standalone."""

    agent_id: str = "unknown"
    agent_name: str = "Unknown Agent"
    state_path: Path = Path("logs/unknown/_agent_state.json")
    _manifest: dict | None = None

    # ── State writing ───────────────────────────────────────────────────────

    def write_state(self, extra: dict[str, Any]) -> None:
        """Write universal state schema + extra fields atomically."""
        base: dict[str, Any] = {
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        base.update(extra)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(base, default=str), encoding="utf-8")
            tmp.replace(self.state_path)
        except Exception as e:
            log.warning("write_state failed: %s", e)
            tmp.unlink(missing_ok=True)

    # ── Paper gate ──────────────────────────────────────────────────────────

    def paper_gate_check(
        self,
        trades: int,
        pf: float,
        min_trades: int = 20,
        min_pf: float = 1.3,
    ) -> bool:
        """Return True if strategy is ready for live promotion."""
        return trades >= min_trades and pf >= min_pf

    def paper_gate_progress(
        self,
        trades: int,
        pf: float,
        min_trades: int = 20,
        min_pf: float = 1.3,
    ) -> dict:
        return {
            "trades_done": trades,
            "trades_needed": min_trades,
            "pf_current": round(pf, 3),
            "pf_needed": min_pf,
            "ready": self.paper_gate_check(trades, pf, min_trades, min_pf),
            "pct_trades": min(100, int(trades / min_trades * 100)),
        }

    # ── Trade journal hook ──────────────────────────────────────────────────

    def log_trade(self, action: str = "open", **kwargs: Any) -> None:
        try:
            from trading_agents.trade_journal import open_trade, close_trade  # type: ignore
            if action == "open":
                open_trade(**kwargs)
            else:
                close_trade(**kwargs)
        except Exception as e:
            log.debug("trade_journal unavailable: %s", e)

    # ── Daily rollover ──────────────────────────────────────────────────────

    def daily_rollover(
        self,
        current_date_str: str | None,
        balance: float,
        trades: dict | int,
    ) -> tuple[str, float, dict | int]:
        """Detect UTC date change and reset daily counters.

        Returns (today_str, start_balance, trades_reset).
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if current_date_str != today:
            log.info("Daily rollover: %s → %s", current_date_str, today)
            return today, balance, ({} if isinstance(trades, dict) else 0)
        return today, balance, trades

    def daily_loss_pct(self, equity: float, start_balance: float) -> float:
        if start_balance <= 0:
            return 0.0
        return round((start_balance - equity) / start_balance * 100, 3)

    def is_dd_exceeded(
        self,
        equity: float,
        start_balance: float,
        limit_pct: float = 20.0,
    ) -> bool:
        return self.daily_loss_pct(equity, start_balance) >= limit_pct

    # ── Manifest access ─────────────────────────────────────────────────────

    def get_manifest(self) -> dict | None:
        if self._manifest is not None:
            return self._manifest
        try:
            from trading_agents.registry.manifest import get
            self._manifest = get(self.agent_id)
        except Exception:
            pass
        return self._manifest
