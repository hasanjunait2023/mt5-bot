"""Layer 3: Master Decision Agent — the ONLY component that calls Claude API.
Called ONLY when ≥3 strategy votes agree on the same symbol+direction.
Uses llm_fallback.chat_resilient with prompt caching for token efficiency."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("jtcc.master_agent")

BASE_DIR_STR = str(__file__)

SYSTEM_PROMPT = """You are the MASTER DECISION AGENT for JTCC (Junait Trading Command Center).

Your role: Make the FINAL trade decision when multiple strategy signals align.
You receive: MarketContext JSON + strategy vote summary.
You return: A single JSON decision object. Nothing else.

HARD RULES (non-negotiable):
- Each voting strategy is INDIVIDUALLY backtest-validated on real broker data — a
  SINGLE high-confidence signal (confidence >= 6) is a tradeable standalone edge.
  Do NOT require multiple strategies to agree. More agreeing = higher conviction,
  but one validated signal is enough to execute when all hard gates below pass.
- Session: Only London KZ (13:00-16:00 BD) or NY KZ (18:00-21:00 BD)
- News: BLOCKED if high-impact event within ±30 min
- Daily DD: BLOCKED if ≥ 6% daily drawdown
- Open trades: Max 3 concurrent, max 2 per symbol per day
- Spread: SKIP if spread > 20% of SL distance
- Min RR: 1:2 mandatory

DECISION FORMAT (return ONLY this JSON, no markdown):
{
  "decision": "BUY" | "SELL" | "WAIT",
  "symbol": "XAUUSD",
  "confidence": 0-10,
  "entry_price": 0.0,
  "stop_loss": 0.0,
  "take_profit": 0.0,
  "rr_ratio": 0.0,
  "strategies_agreed": ["name1", "name2", "name3"],
  "confluence_score": 0.0,
  "rationale": "2-3 sentence precise technical rationale",
  "risk_validated": true | false,
  "execute": true | false
}

If ANY hard rule is violated → decision="WAIT", execute=false.
A single validated strategy signal with confidence >= 6 + all gates passing =
execute=true. Do NOT block solely because only one strategy voted.
Be cold and precise, but do not be so passive that valid edges never trade."""


def _build_prompt(ctx_dict: dict, votes: list[dict]) -> str:
    buy_votes = [v for v in votes if v.get("signal") == "BUY"]
    sell_votes = [v for v in votes if v.get("signal") == "SELL"]
    vote_summary = {
        "buy_count": len(buy_votes),
        "sell_count": len(sell_votes),
        "buy_strategies": [v["strategy"] for v in buy_votes],
        "sell_strategies": [v["strategy"] for v in sell_votes],
        "avg_confidence_buy": round(sum(v.get("confidence", 5) for v in buy_votes) / max(len(buy_votes), 1), 1),
        "avg_confidence_sell": round(sum(v.get("confidence", 5) for v in sell_votes) / max(len(sell_votes), 1), 1),
        "entry_prices": list(set(v.get("entry", 0) for v in votes if v.get("entry"))),
        "stop_losses": list(set(v.get("sl", 0) for v in votes if v.get("sl"))),
        "take_profits": list(set(v.get("tp", 0) for v in votes if v.get("tp"))),
    }
    # Strip raw OHLCV bars (too large) before sending to Claude
    ctx_clean = {k: v for k, v in ctx_dict.items() if k != "ohlcv"}
    return json.dumps({"market_context": ctx_clean, "strategy_votes": vote_summary}, indent=2)


def _parse_response(text: str) -> dict:
    """Extract JSON from response, handle markdown code blocks."""
    text = text.strip()
    if "```" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        return json.loads(text)
    except Exception:
        return {"decision": "WAIT", "execute": False, "rationale": "Parse error: " + text[:100]}


class MasterAgent:
    """Layer 3 — Single Claude API call per valid signal set. NVIDIA fallback on failure."""

    def __init__(self, min_strategies: int = 3, min_confidence: float = 6.0,
                 model: str = "claude-opus-4-7", max_tokens: int = 600,
                 nvidia_tier: str = "HEAVY", alert_on_fallback: bool = True,
                 alert_cooldown_min: int = 15) -> None:
        self.min_strategies = min_strategies
        self.min_confidence = min_confidence
        self.model = model
        self.max_tokens = max_tokens
        self.nvidia_tier = nvidia_tier
        self.alert_on_fallback = alert_on_fallback
        self.alert_cooldown_s = alert_cooldown_min * 60
        self._client: anthropic.Anthropic | None = None
        self._daily_calls = 0
        self._claude_success = 0
        self._claude_fail = 0
        self._nvidia_recovered = 0
        self._all_fail = 0
        self._last_alert_ts = 0.0

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        return self._client

    def _hard_gate(self, ctx_dict: dict, votes: list[dict]) -> str | None:
        """Returns rejection reason string if blocked, None if clear to proceed."""
        risk = ctx_dict.get("risk", {})
        session = ctx_dict.get("session", {})
        news = ctx_dict.get("news", {})

        if risk.get("daily_dd_pct", 0) >= 6.0:
            return f"BLOCKED: daily DD {risk['daily_dd_pct']:.1f}% >= 6%"
        if not session.get("active") or not session.get("primary"):
            return f"BLOCKED: session {session.get('name', 'off')} not a primary kill zone"
        if news.get("blocked"):
            return f"BLOCKED: news — {news.get('reason', 'high-impact event')}"
        if risk.get("open_trades", 0) >= 3:
            return f"BLOCKED: {risk['open_trades']} open trades (max 3)"

        # Count agreeing votes
        buy_votes = [v for v in votes if v.get("signal") == "BUY"]
        sell_votes = [v for v in votes if v.get("signal") == "SELL"]
        max_votes = max(len(buy_votes), len(sell_votes))
        if max_votes < self.min_strategies:
            return f"BLOCKED: only {max_votes} agreeing votes (need ≥{self.min_strategies})"

        return None  # clear

    async def decide(self, ctx_dict: dict, votes: list[dict]) -> dict[str, Any]:
        """Gate-check then call Claude API. Returns decision dict."""
        import asyncio

        block_reason = self._hard_gate(ctx_dict, votes)
        if block_reason:
            log.info("Master gate: %s", block_reason)
            return {"decision": "WAIT", "execute": False, "rationale": block_reason,
                    "gated": True, "api_called": False}

        # Make Claude API call via llm_fallback (Claude → NVIDIA fallback chain)
        try:
            from trading_agents.llm_fallback import chat_resilient
            client = self._get_client()
            prompt = _build_prompt(ctx_dict, votes)

            # Detect backend used by inspecting telemetry written by chat_resilient
            from trading_agents.jtcc.core.latency_tracker import tracker
            with tracker.measure("master_llm_call"):
                response_text = await asyncio.to_thread(
                    chat_resilient,
                    client,
                    system=SYSTEM_PROMPT,
                    user=prompt,
                    max_tokens=self.max_tokens,
                    model=self.model,
                    thinking=False,
                    nvidia_tier=self.nvidia_tier,    # configurable: HEAVY/ULTRA/MEDIUM
                    label="jtcc_master",
                )

            backend_used = self._detect_backend()
            self._daily_calls += 1
            if backend_used == "nvidia":
                self._nvidia_recovered += 1
                log.warning("Master call #%d recovered via NVIDIA %s (Claude failed)",
                            self._daily_calls, self.nvidia_tier)
                self._maybe_alert_fallback(ctx_dict.get("symbol", "?"))
            else:
                self._claude_success += 1
                log.info("Master API call #%d (Claude) — symbol=%s",
                         self._daily_calls, ctx_dict.get("symbol"))

            result = _parse_response(response_text)
            result["api_called"] = True
            result["backend"] = backend_used
            result["gated"] = False
            return result
        except Exception as e:
            self._all_fail += 1
            log.error("Master Agent ALL backends failed: %s", e)
            # When both Claude AND NVIDIA fail → critical Telegram + stay safe
            self._alert_total_failure(str(e), ctx_dict.get("symbol", "?"))
            return {"decision": "WAIT", "execute": False,
                    "rationale": f"All LLM backends down: {e}",
                    "api_called": False, "backend": "none"}

    def _detect_backend(self) -> str:
        """Read most recent agent_metrics line for jtcc_master to see which backend succeeded."""
        try:
            from pathlib import Path
            import json
            metrics_file = Path(__file__).parent.parent.parent.parent / "logs" / "agent_metrics.jsonl"
            if not metrics_file.exists():
                return "claude"  # assume default
            lines = metrics_file.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines[-50:]):
                try:
                    entry = json.loads(line)
                    if entry.get("label") == "jtcc_master":
                        return entry.get("backend", "claude")
                except Exception:
                    continue
        except Exception:
            pass
        return "claude"

    def _maybe_alert_fallback(self, symbol: str) -> None:
        if not self.alert_on_fallback:
            return
        import time as _t
        now = _t.time()
        if now - self._last_alert_ts < self.alert_cooldown_s:
            return
        self._last_alert_ts = now
        try:
            from trading_agents.telegram_hq import send as tg_send
            tg_send("live_trading",
                    f"⚠️ JTCC Master Agent fell back to NVIDIA {self.nvidia_tier}\n"
                    f"Claude API unavailable. NVIDIA recovered successfully.\n"
                    f"Symbol attempted: {symbol}\n"
                    f"Recovery count today: {self._nvidia_recovered}",
                    level="WARNING", title="JTCC: Claude→NVIDIA fallback")
        except Exception:
            pass

    def _alert_total_failure(self, error: str, symbol: str) -> None:
        try:
            from trading_agents.telegram_hq import send as tg_send
            tg_send("critical",
                    f"🚨 JTCC MASTER: ALL LLM BACKENDS DOWN\n"
                    f"Claude + NVIDIA both failing.\n"
                    f"Symbol: {symbol}\n"
                    f"Error: {error[:200]}\n"
                    f"Trading SAFE — no signal will fire until recovery.",
                    level="CRITICAL", title="JTCC LLM CHAIN DOWN")
        except Exception:
            pass

    def backend_stats(self) -> dict:
        return {
            "claude_success": self._claude_success,
            "nvidia_recovered": self._nvidia_recovered,
            "all_fail": self._all_fail,
            "total_calls": self._daily_calls,
            "fallback_rate_pct": round(self._nvidia_recovered / max(self._daily_calls, 1) * 100, 1),
        }

    @property
    def daily_calls(self) -> int:
        return self._daily_calls

    def reset_daily_count(self) -> None:
        self._daily_calls = 0
