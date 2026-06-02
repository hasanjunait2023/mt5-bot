"""Classify an ingested video: is it a tradeable strategy or something else?

Uses the video's title + channel + description (cheap, no transcript needed) to
decide whether to run the full strategy pipeline or to produce a short plan for
the user to approve (non-strategy branch).
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("factory.classify")

_SYSTEM = """You triage YouTube videos for a trading-strategy research factory.
Given a video's title, channel and description, decide if it teaches a concrete,
backtestable TRADING STRATEGY (entry/exit rules on price charts) versus anything
else (market news, motivation, broker review, general education, unrelated).

Reply with ONLY a JSON object:
{"is_strategy": true|false,
 "confidence": 0.0-1.0,
 "reason": "one sentence",
 "plan": "if NOT a strategy: 2-4 sentence plan of what you COULD do with this video instead; else empty string"}"""


def classify(meta: dict) -> dict:
    """Return {is_strategy, confidence, reason, plan}. Never raises — defaults to
    treating it as a strategy if the LLM is unavailable (the gate catches bad
    ones later)."""
    from trading_agents.llm_fallback import chat_resilient

    user = json.dumps({
        "title": meta.get("title", ""),
        "channel": meta.get("channel", ""),
        "description": (meta.get("description", "") or "")[:3000],
    }, ensure_ascii=False)

    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        client = None

    try:
        raw = chat_resilient(
            client, system=_SYSTEM, user=user, max_tokens=600,
            model="claude-opus-4-8", thinking=False, nvidia_tier="HEAVY",
            label="factory_classify",
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        return {
            "is_strategy": bool(data.get("is_strategy", True)),
            "confidence": float(data.get("confidence", 0.5)),
            "reason": str(data.get("reason", "")),
            "plan": str(data.get("plan", "")),
        }
    except Exception as e:  # noqa: BLE001
        log.warning("classify failed (%s) — defaulting to is_strategy=True", e)
        return {"is_strategy": True, "confidence": 0.3,
                "reason": f"classifier unavailable ({e}); assuming strategy", "plan": ""}
