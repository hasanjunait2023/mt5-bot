"""
Resilient LLM call — Claude with automatic NVIDIA NIM fallback + telemetry.

Every high-value agent calls Claude through this. On ANY Claude failure
(outage, rate limit, 529, missing/expired ANTHROPIC_API_KEY, network error,
empty text) it falls back to the given NVIDIA NIM tier so the agent keeps
running instead of crashing. Every call is recorded to agent_telemetry so
the dashboard can show fallback rate / latency / errors per agent.

Model guidance:
  P1 reasoners (debug_investigator, supervisor, scout) →
      model="claude-opus-4-7", thinking=True, nvidia_tier="ULTRA"
  Everyone else → keep their current model (sonnet/haiku), thinking=False,
      nvidia_tier="HEAVY" (reasoning) or "MEDIUM" (routing/docs)

NVIDIA tiers (nvidia_model_router.MODELS): ULTRA mistral-675b · HEAVY
nemotron-49b · MEDIUM llama-70b · LIGHT nano-8b · NANO llama-1b.
"""

import logging
import sys
import time
from pathlib import Path

log = logging.getLogger("LLMFallback")

# nvidia_model_router.py and agent_telemetry.py sit next to this file.
_TA_DIR = Path(__file__).resolve().parent
if str(_TA_DIR) not in sys.path:
    sys.path.insert(0, str(_TA_DIR))

try:
    import agent_telemetry as _tel
except Exception:  # telemetry is optional, never fatal
    _tel = None


def _emit(agent: str, model: str, backend: str, t0: float,
          ok: bool, error: str | None = None) -> None:
    if _tel is None:
        return
    try:
        _tel.record(agent, model=model, backend=backend,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    ok=ok, error=error)
    except Exception:
        pass


def chat_resilient(client, *, system: str, user: str, max_tokens: int,
                   model: str = "claude-opus-4-7", thinking: bool = True,
                   effort: str = "high", nvidia_tier: str = "ULTRA",
                   label: str = "agent") -> str:
    """
    Try Claude (`model`). On any failure fall back to the NVIDIA NIM tier.

    thinking=True  → Opus/Sonnet adaptive thinking + effort (P1 reasoners).
    thinking=False → plain call, current model unchanged (use for Haiku and
                     the non-P1 agents — keeps their cost/behaviour as-is,
                     just adds the NVIDIA safety net + telemetry).

    Returns the assistant text. Raises RuntimeError only if EVERY backend fails.
    """
    t0 = time.perf_counter()

    # ── 1. Primary: Claude ───────────────────────────────────────────────
    try:
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            # Static system prompt as a content block (cache no-op below ~2-4k tok)
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if thinking:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": effort}

        resp = client.messages.create(**kwargs)
        # With thinking enabled content[0] may be a thinking block.
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        if text:
            _emit(label, model, "claude", t0, True)
            return text
        raise RuntimeError("Claude returned no text block")
    except Exception as e:
        log.warning("[%s] Claude (%s) unavailable (%s) — NVIDIA %s fallback",
                    label, model, e, nvidia_tier)

    # ── 2. Fallback: NVIDIA NIM (primary → fallback model) ───────────────
    try:
        import nvidia_model_router as nvr
    except Exception as e:
        _emit(label, model, "claude", t0, False,
              f"Claude failed; NVIDIA router unavailable: {e}")
        raise RuntimeError(
            f"[{label}] Claude failed and NVIDIA router unavailable: {e}"
        )

    spec = nvr.MODELS.get(nvidia_tier) or nvr.MODELS["HEAVY"]
    timeout = spec.get("timeout", 120)
    nvidia_max = min(max_tokens, spec.get("max_tokens", max_tokens))
    last_err = None
    for nv_model in (spec.get("primary"), spec.get("fallback")):
        if not nv_model:
            continue
        try:
            text = nvr._chat(nv_model, system, user, nvidia_max,
                             temperature=0.2, timeout=timeout)
            if text and text.strip():
                log.info("[%s] Recovered via NVIDIA %s", label, nv_model)
                _emit(label, nv_model, "nvidia", t0, True)
                return text.strip()
        except Exception as e:
            last_err = e
            log.warning("[%s] NVIDIA %s failed: %s", label, nv_model, e)

    _emit(label, model, "nvidia", t0, False,
          f"all backends failed: {last_err}")
    raise RuntimeError(
        f"[{label}] all backends failed (Claude {model} + NVIDIA {nvidia_tier}): {last_err}"
    )
