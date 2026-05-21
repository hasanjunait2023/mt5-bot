"""
Trade Confirmation & Regime Agent — the AI half of the hybrid CPP system.
=========================================================================

The mechanical CPP rules (strategies/confluence_pullback.py) generate
candidate setups. This agent sits BETWEEN signal and execution and returns
one of: APPROVE / SIZE_DOWN / VETO. Research-grounded design: the AI is
added to *confirm and modulate exposure*, never to invent trades or
replace the rule edge — with a fast deterministic fallback so the system
keeps trading when the LLM is unreachable.

Two backends, one interface:
  • rule  — deterministic scorer over the SAME Setup features the rules
            judge. Zero network. Used in backtest (2y replay, no API
            storm) and as the LLM fallback.
  • llm   — Claude (→ NVIDIA via llm_fallback.chat_resilient, telemetry
            auto-recorded) for nuanced regime / news / structure reads.
            Live only.

Modes:
  off       always APPROVE (pure mechanical baseline / A-B control)
  advisory  rule backend only — deterministic, what the backtest uses
  veto      rule + LLM; LLM may downsize or veto, never upsize; any LLM
            failure → rule verdict (fail-safe, edge keeps running)

It NEVER blocks a high-confluence setup on mere uncertainty: a failed or
low-confidence LLM call degrades to the rule verdict, it does not abstain
into a VETO. Promotion to real money still goes through the existing
fail-closed promotion_gate.can_go_live — this agent only gates entries.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

_TA_DIR = Path(__file__).resolve().parent
if str(_TA_DIR) not in sys.path:
    sys.path.insert(0, str(_TA_DIR))

from strategies.confluence_pullback import Setup  # noqa: E402

try:
    from llm_fallback import chat_resilient        # noqa: E402
except Exception:  # pragma: no cover
    chat_resilient = None


# ── verdict ────────────────────────────────────────────────────────────
@dataclass
class AgentVerdict:
    decision: str        # APPROVE | SIZE_DOWN | VETO
    size_mult: float     # multiply the 1% risk by this (0.0 == veto)
    confidence: float    # 0..1
    rationale: str
    backend: str         # "rule" | "llm" | "off"

    def dict(self) -> dict:
        return asdict(self)


_APPROVE = lambda c, r, b="rule": AgentVerdict("APPROVE", 1.0, c, r, b)
_DOWN = lambda c, r, b="rule": AgentVerdict("SIZE_DOWN", 0.5, c, r, b)
_VETO = lambda c, r, b="rule": AgentVerdict("VETO", 0.0, c, r, b)


DEFAULT_CFG = {
    "mode": "advisory",          # off | advisory | veto
    "veto_below_score": 45.0,    # rule: confluence < this  -> VETO
    "downsize_below_score": 62.0,  # rule: confluence < this -> SIZE_DOWN
    "news_blackout_veto": True,  # context.news_high -> VETO
    "llm_model": "claude-haiku-4-5-20251001",  # cheap, fast — gate not reasoner
    "llm_tier": "MEDIUM",
}


class TradeConfirmationAgent:
    def __init__(self, cfg: Optional[dict] = None, client=None):
        self.cfg = {**DEFAULT_CFG, **(cfg or {})}
        self._client = client  # anthropic.Anthropic | None (lazy)

    # ── public API ─────────────────────────────────────────────────────
    def evaluate(self, setup: Setup, context: Optional[dict] = None) -> AgentVerdict:
        """Decide on one candidate setup. `context` (live only) may carry
        {news_high: bool, spread_pts: float, open_risk_pct: float,
         recent_losses: int, symbol: str, session: str}."""
        ctx = context or {}
        mode = self.cfg["mode"]

        if mode == "off":
            return AgentVerdict("APPROVE", 1.0, 1.0,
                                "agent off (mechanical baseline)", "off")

        rule = self._rule_verdict(setup, ctx)

        if mode == "advisory" or rule.decision == "VETO":
            # rule VETO is authoritative (low confluence is non-negotiable);
            # advisory mode never calls the LLM (keeps backtest deterministic)
            return rule

        # mode == "veto": let the LLM tighten (downsize/veto), never loosen
        llm = self._llm_verdict(setup, ctx)
        if llm is None:
            return rule  # fail-safe: keep the rule decision, edge keeps running
        # take the MORE conservative of the two; LLM can only restrict
        if llm.decision == "VETO":
            return llm
        if llm.decision == "SIZE_DOWN" and rule.decision == "APPROVE":
            return llm
        return rule

    # ── rule backend (deterministic, also the LLM fallback) ─────────────
    def _rule_verdict(self, s: Setup, ctx: dict) -> AgentVerdict:
        if self.cfg["news_blackout_veto"] and ctx.get("news_high"):
            return _VETO(0.9, "high-impact news blackout")
        if ctx.get("spread_pts") and s.atr > 0 and \
                ctx["spread_pts"] > 0.25 * (s.atr / max(ctx.get("pip", 1e-9), 1e-9)):
            return _DOWN(0.6, f"wide spread {ctx['spread_pts']:.0f}pts vs ATR")
        if s.score < self.cfg["veto_below_score"]:
            return _VETO(0.8, f"weak confluence (score {s.score} < "
                              f"{self.cfg['veto_below_score']})")
        if s.score < self.cfg["downsize_below_score"]:
            return _DOWN(0.65, f"moderate confluence (score {s.score})")
        if ctx.get("recent_losses", 0) >= 3:
            return _DOWN(0.7, "3+ recent losses — defensive sizing")
        return _APPROVE(min(1.0, s.score / 100.0),
                        f"clean {s.regime} setup (score {s.score}, "
                        f"ADX {s.adx:.0f})")

    # ── llm backend (live nuance; telemetry auto via chat_resilient) ────
    def _llm_verdict(self, s: Setup, ctx: dict) -> Optional[AgentVerdict]:
        if chat_resilient is None:
            return None
        try:
            if self._client is None:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_API_KEY"))
            sys_p = (
                "You are a risk-gate for a rule-based FX/metals trading "
                "system. The mechanical rules already passed this setup. "
                "Your ONLY job is to confirm, downsize, or veto on regime / "
                "news / structure grounds. You may NEVER upsize or invent "
                "trades. Reply with STRICT JSON only: "
                '{\"decision\":\"APPROVE|SIZE_DOWN|VETO\",'
                '\"size_mult\":0.0-1.0,\"confidence\":0.0-1.0,'
                '\"rationale\":\"<=20 words\"}.')
            usr = json.dumps({"setup": {
                "symbol": ctx.get("symbol"), "dir": s.direction,
                "regime": s.regime, "score": s.score, "adx": round(s.adx, 1),
                "rsi": round(s.rsi, 1), "stoch_k": round(s.stoch_k, 1),
                "pullback_atr": round(s.pullback_atr, 2)},
                "context": {k: ctx.get(k) for k in (
                    "news_high", "spread_pts", "recent_losses",
                    "open_risk_pct", "session")}})
            raw = chat_resilient(
                self._client, system=sys_p, user=usr, max_tokens=200,
                model=self.cfg["llm_model"], thinking=False,
                nvidia_tier=self.cfg["llm_tier"],
                label="trade_confirmation_agent")
            j = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            dec = str(j.get("decision", "APPROVE")).upper()
            if dec not in ("APPROVE", "SIZE_DOWN", "VETO"):
                return None
            return AgentVerdict(
                dec, max(0.0, min(1.0, float(j.get("size_mult", 1.0)))),
                max(0.0, min(1.0, float(j.get("confidence", 0.5)))),
                str(j.get("rationale", ""))[:120], "llm")
        except Exception:
            return None  # any failure → caller falls back to the rule verdict


# ── selftest (verification step 1) ─────────────────────────────────────
def _selftest() -> int:
    clean = Setup("BUY", "test", "trend", 78.0, 2.5, 33.0, 55.0, 30.0, 0.3)
    weak = Setup("SELL", "test", "range", 38.0, 1.0, 20.5, 50.0, 80.0, 0.9)
    mid = Setup("BUY", "test", "range", 55.0, 1.5, 24.0, 52.0, 22.0, 0.5)
    a = TradeConfirmationAgent({"mode": "advisory"})
    r1 = a.evaluate(clean)
    r2 = a.evaluate(weak)
    r3 = a.evaluate(mid)
    r4 = a.evaluate(clean, {"news_high": True})
    r5 = TradeConfirmationAgent({"mode": "off"}).evaluate(weak)
    print(f"clean setup     -> {r1.decision:9s} x{r1.size_mult} ({r1.rationale})")
    print(f"weak setup      -> {r2.decision:9s} x{r2.size_mult} ({r2.rationale})")
    print(f"mid setup       -> {r3.decision:9s} x{r3.size_mult} ({r3.rationale})")
    print(f"clean + news    -> {r4.decision:9s} x{r4.size_mult} ({r4.rationale})")
    print(f"agent off       -> {r5.decision:9s} x{r5.size_mult} ({r5.rationale})")
    ok = (r1.decision == "APPROVE" and r2.decision == "VETO"
          and r3.decision == "SIZE_DOWN" and r4.decision == "VETO"
          and r5.decision == "APPROVE" and r1.backend == "rule")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("Trade Confirmation Agent. Run with --selftest to verify.")
