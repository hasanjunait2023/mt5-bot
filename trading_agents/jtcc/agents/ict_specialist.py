"""ICT 2022 Specialist — LLM-powered ICT setup analyzer.

Unlike rule-based YAML strategies (zero tokens), this agent uses Claude (with
NVIDIA fallback) to analyze the market in pure ICT methodology terms.

Behavior:
  • Smart pre-gating: only calls LLM when ICT-relevant market conditions exist
  • Budget cap: max 30 LLM calls/day (separate from Master Agent's 15/day)
  • Returns a vote dict (BUY/SELL/NONE + confidence + rationale) that joins
    the YAML strategy votes pool — so ICT analysis counts toward Master
    Agent's ≥3-vote confluence threshold
  • Uses llm_fallback.chat_resilient → Claude → NVIDIA HEAVY fallback chain

This is the "ICT desk analyst" — speaks fluent ICT, ranks setups like Inner
Circle Trader himself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("jtcc.ict_specialist")

SYSTEM_PROMPT = """You are an ICT 2022 Mentorship Model specialist. You analyze
the market exactly like Inner Circle Trader (ICT) would — Bias, Killzone,
Liquidity, Manipulation, Distribution.

You receive a market snapshot (price, structure, SMC zones, momentum, session).
You return ONE JSON object describing whether an ICT A+ setup exists.

ICT setup rules (in order):
1. HTF BIAS:        Trend must be BULLISH or BEARISH (not NEUTRAL)
2. KILLZONE:        Must be in primary KZ (London 13:00-16:00 BD or NY 18:00-21:00 BD)
3. LIQUIDITY SWEEP: Recent wick beyond swing high (BSL_SWEEP for sells) or
                    swing low (SSL_SWEEP for buys), then close back inside
4. MSS:             Market Structure Shift = displacement candle (body > 1.5×ATR)
                    after the sweep, in the direction of HTF bias
5. FVG/OB:          Fair Value Gap or Order Block forming as entry zone
6. OTE ZONE:        Price retraced into 62-79% Fibonacci of the impulse
7. NEWS CLEAN:      No high-impact news within ±30 min

CONFIDENCE SCORING (0-10):
  10 = textbook A+ setup, every box checked, perfect structure
   8 = strong setup, 6/7 boxes
   6 = decent setup, 5/7 boxes
   <6 = skip, not worth the risk
   0 = no setup

OUTPUT FORMAT (return ONLY this JSON, no markdown):
{
  "signal": "BUY" | "SELL" | "NONE",
  "confidence": 0-10,
  "entry": float or null,
  "sl": float or null,
  "tp": float or null,
  "ict_components": {
    "bias": "BULLISH/BEARISH/NEUTRAL",
    "killzone_active": true/false,
    "sweep_detected": true/false,
    "mss_confirmed": true/false,
    "fvg_present": true/false,
    "ote_zone": true/false,
    "news_clean": true/false
  },
  "rationale": "1-2 sentence ICT-language explanation"
}

If ANY of (bias=NEUTRAL, killzone inactive, news blocked) → signal=NONE.
Be strict. ICT is patient. Skip more than you take."""


class ICTSpecialist:
    """LLM-powered ICT 2022 analyst. Votes alongside YAML rule strategies."""

    name = "ICT Specialist"

    def __init__(
        self,
        model: str = "claude-opus-4-8",
        nvidia_tier: str = "HEAVY",
        max_calls_per_day: int = 30,
        max_tokens: int = 400,
        symbols: list[str] | None = None,
    ) -> None:
        self.model = model
        self.nvidia_tier = nvidia_tier
        self.max_calls_per_day = max_calls_per_day
        self.max_tokens = max_tokens
        self.symbols = symbols or ["XAUUSD", "EURUSD", "GBPUSD"]
        self._calls_today = 0
        self._gate_blocks = 0
        self._signals_returned = 0
        self._client: anthropic.Anthropic | None = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        return self._client

    def _pre_gate(self, ctx: dict) -> tuple[bool, str]:
        """Cheap pre-check before spending tokens. Returns (call_llm, reason)."""
        symbol = ctx.get("symbol", "")
        if symbol not in self.symbols:
            return False, f"{symbol} not in ICT specialist symbols"

        session = ctx.get("session", {})
        if not session.get("primary"):
            return False, f"session not primary ({session.get('name', 'off')})"

        news = ctx.get("news", {})
        if news.get("blocked"):
            return False, "news blocked"

        smc = ctx.get("smc", {})
        market = ctx.get("market", {})

        # Need at least ONE ICT structural element to be worth analyzing
        has_setup = (
            smc.get("sweep_detected", False)
            or market.get("mss", False)
            or market.get("bos", False)
            or smc.get("in_ote", False)
            or (smc.get("bull_fvg_count", 0) + smc.get("bear_fvg_count", 0)) > 0
        )
        if not has_setup:
            return False, "no ICT structural elements present"

        if self._calls_today >= self.max_calls_per_day:
            return False, f"daily budget exhausted ({self._calls_today}/{self.max_calls_per_day})"

        return True, "ICT analysis worthwhile"

    def _build_prompt(self, ctx: dict) -> str:
        """Build compact ICT-focused prompt (strip irrelevant data)."""
        ict_view = {
            "symbol": ctx.get("symbol"),
            "current_price": ctx.get("price", {}).get("mid"),
            "spread": ctx.get("price", {}).get("spread"),
            "bias": {
                "trend": ctx.get("market", {}).get("trend"),
                "structure": ctx.get("market", {}).get("structure"),
                "hh_hl": [ctx.get("market", {}).get("hh"), ctx.get("market", {}).get("hl")],
                "lh_ll": [ctx.get("market", {}).get("lh"), ctx.get("market", {}).get("ll")],
                "last_swing_high": ctx.get("market", {}).get("last_swing_high"),
                "last_swing_low": ctx.get("market", {}).get("last_swing_low"),
                "key_levels": ctx.get("market", {}).get("key_levels", [])[:5],
            },
            "structure": {
                "bos": ctx.get("market", {}).get("bos"),
                "choch": ctx.get("market", {}).get("choch"),
                "mss": ctx.get("market", {}).get("mss"),
            },
            "liquidity": {
                "sweep_detected": ctx.get("smc", {}).get("sweep_detected"),
                "sweep_type": ctx.get("smc", {}).get("sweep_type"),
                "sweep_quality": ctx.get("smc", {}).get("sweep_quality"),
                "ssl_pools_above": ctx.get("smc", {}).get("ssl_pools", [])[:3],
                "bsl_pools_below": ctx.get("smc", {}).get("bsl_pools", [])[:3],
            },
            "zones": {
                "in_ote": ctx.get("smc", {}).get("in_ote"),
                "ote_top": ctx.get("smc", {}).get("ote_zone", {}).get("top"),
                "ote_bottom": ctx.get("smc", {}).get("ote_zone", {}).get("bottom"),
                "in_discount": ctx.get("smc", {}).get("in_discount"),
                "in_premium": ctx.get("smc", {}).get("in_premium"),
                "nearest_bull_fvg": ctx.get("smc", {}).get("nearest_bull_fvg"),
                "nearest_bear_fvg": ctx.get("smc", {}).get("nearest_bear_fvg"),
                "bull_ob_count": ctx.get("smc", {}).get("bull_ob_count"),
                "bear_ob_count": ctx.get("smc", {}).get("bear_ob_count"),
            },
            "momentum": {
                "atr": ctx.get("momentum", {}).get("atr"),
                "rsi": ctx.get("momentum", {}).get("rsi"),
                "adx": ctx.get("momentum", {}).get("adx"),
                "ha_streak": ctx.get("momentum", {}).get("ha_streak"),
            },
            "session": {
                "name": ctx.get("session", {}).get("name"),
                "silver_bullet": ctx.get("session", {}).get("silver_bullet"),
                "minutes_remaining": ctx.get("session", {}).get("minutes_remaining"),
            },
            "news_clean": not ctx.get("news", {}).get("blocked"),
        }
        return json.dumps(ict_view, indent=2)

    def _parse_response(self, text: str) -> dict:
        text = text.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        try:
            return json.loads(text)
        except Exception as e:
            log.warning("ICT response parse fail: %s | text=%s", e, text[:200])
            return {"signal": "NONE", "confidence": 0, "rationale": f"Parse error: {e}"}

    async def vote(self, ctx: dict) -> dict[str, Any]:
        """Returns a vote dict in the same format as rule_engine.evaluate().

        Output: {signal, strategy, confidence, entry, sl, tp, rr_ratio, reason}
        """
        symbol = ctx.get("symbol", "?")
        ok, reason = self._pre_gate(ctx)
        if not ok:
            self._gate_blocks += 1
            return {
                "signal": "NONE",
                "strategy": self.name,
                "confidence": 0,
                "reason": f"gate: {reason}",
                "gated": True,
            }

        # Pre-gate passed → call LLM
        try:
            from trading_agents.llm_fallback import chat_resilient
            from trading_agents.jtcc.core.latency_tracker import tracker

            client = self._get_client()
            prompt = self._build_prompt(ctx)

            with tracker.measure("ict_specialist_llm"):
                response_text = await asyncio.to_thread(
                    chat_resilient,
                    client,
                    system=SYSTEM_PROMPT,
                    user=prompt,
                    max_tokens=self.max_tokens,
                    model=self.model,
                    thinking=False,
                    nvidia_tier=self.nvidia_tier,
                    label="ict_specialist",
                )
            self._calls_today += 1

            result = self._parse_response(response_text)
            signal = (result.get("signal") or "NONE").upper()
            confidence = float(result.get("confidence", 0))

            if signal in ("BUY", "SELL") and confidence >= 6:
                self._signals_returned += 1
                price = ctx.get("price", {}).get("mid", 0)
                entry = float(result.get("entry") or price)
                sl = float(result.get("sl") or (price - ctx.get("momentum", {}).get("atr", 0) * 2 if signal == "BUY"
                                                else price + ctx.get("momentum", {}).get("atr", 0) * 2))
                tp = float(result.get("tp") or (entry + (entry - sl) * 2 if signal == "BUY"
                                                else entry - (sl - entry) * 2))
                rr = round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
                log.info("ICT Specialist [%s]: %s conf=%.1f — %s",
                         symbol, signal, confidence, result.get("rationale", "")[:80])
                return {
                    "signal": signal,
                    "strategy": self.name,
                    "confidence": confidence,
                    "entry": round(entry, 5),
                    "sl": round(sl, 5),
                    "tp": round(tp, 5),
                    "rr_ratio": rr,
                    "ict_components": result.get("ict_components", {}),
                    "reason": result.get("rationale", "ICT setup detected"),
                    "llm_called": True,
                }
            else:
                return {
                    "signal": "NONE",
                    "strategy": self.name,
                    "confidence": confidence,
                    "reason": result.get("rationale", "ICT specialist: no A+ setup"),
                    "llm_called": True,
                }
        except Exception as e:
            log.error("ICT Specialist error: %s", e)
            return {
                "signal": "NONE",
                "strategy": self.name,
                "confidence": 0,
                "reason": f"ICT specialist error: {e}",
                "llm_called": False,
            }

    def stats(self) -> dict:
        return {
            "calls_today": self._calls_today,
            "calls_budget": self.max_calls_per_day,
            "calls_remaining": max(0, self.max_calls_per_day - self._calls_today),
            "gate_blocks": self._gate_blocks,
            "signals_returned": self._signals_returned,
            "signal_rate_pct": round(self._signals_returned / max(self._calls_today, 1) * 100, 1),
        }

    def reset_daily(self) -> None:
        self._calls_today = 0
        self._gate_blocks = 0
        self._signals_returned = 0
