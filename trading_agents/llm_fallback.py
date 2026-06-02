"""
Resilient LLM call — Claude with automatic NVIDIA NIM fallback + telemetry.

Every high-value agent calls Claude through this. On ANY Claude failure
(outage, rate limit, 529, missing/expired ANTHROPIC_API_KEY, network error,
empty text) it falls back to the given NVIDIA NIM tier so the agent keeps
running instead of crashing. Every call is recorded to agent_telemetry so
the dashboard can show fallback rate / latency / errors per agent.

Model guidance:
  P1 reasoners (debug_investigator, supervisor, scout) →
      model="claude-opus-4-8", thinking=True, nvidia_tier="ULTRA"
  Everyone else → keep their current model (sonnet/haiku), thinking=False,
      nvidia_tier="HEAVY" (reasoning) or "MEDIUM" (routing/docs)

NVIDIA tiers (nvidia_model_router.MODELS): ULTRA mistral-675b · HEAVY
nemotron-49b · MEDIUM llama-70b · LIGHT nano-8b · NANO llama-1b.
"""

import logging
import os
import shutil
import subprocess
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

# Map full model IDs → claude CLI aliases
_CLI_MODEL_ALIAS = {
    "claude-opus-4-8":          "opus",
    "claude-sonnet-4-6":        "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
    "claude-haiku-4-5":         "haiku",
}


def _claude_cli_call(system: str, user: str, max_tokens: int,
                     model: str, timeout: int = 120) -> str:
    """
    Call `claude -p` subprocess using the existing Claude Code subscription
    (OAuth/keychain auth — no ANTHROPIC_API_KEY required).
    """
    cli = shutil.which("claude")
    if cli is None:
        raise RuntimeError("claude CLI not found in PATH")

    model_arg = _CLI_MODEL_ALIAS.get(model, model)
    cmd = [
        cli, "-p", user,
        "--model", model_arg,
        "--output-format", "text",
    ]
    if system:
        cmd += ["--system-prompt", system]

    # Strip empty ANTHROPIC_API_KEY so CLI falls through to OAuth/keychain.
    env = dict(os.environ)
    if not env.get("ANTHROPIC_API_KEY", "").strip():
        env.pop("ANTHROPIC_API_KEY", None)

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=timeout, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exit {result.returncode}: {result.stderr[:300]}"
        )
    text = result.stdout.strip()
    if not text:
        raise RuntimeError("claude CLI returned empty output")
    return text


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
                   model: str = "claude-opus-4-8", thinking: bool = True,
                   effort: str = "high", nvidia_tier: str = "ULTRA",
                   label: str = "agent") -> str:
    """
    Try Claude SDK → claude CLI subprocess → NVIDIA NIM.

    thinking=True  → Opus/Sonnet adaptive thinking + effort (P1 reasoners).
    thinking=False → plain call, current model unchanged (Haiku / non-P1).

    Returns the assistant text. Raises RuntimeError only if ALL backends fail.
    """
    t0 = time.perf_counter()

    # ── 1. Primary: Claude SDK (needs ANTHROPIC_API_KEY) ─────────────────
    try:
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}

        resp = client.messages.create(**kwargs)
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        if text:
            _emit(label, model, "claude", t0, True)
            return text
        raise RuntimeError("Claude returned no text block")
    except Exception as e:
        log.warning("[%s] Claude (%s) unavailable (%r) — trying claude CLI",
                    label, model, str(e)[:120])

    # ── 1.5. Claude CLI subprocess (uses subscription OAuth, no key needed) ─
    try:
        text = _claude_cli_call(system, user, max_tokens, model, timeout=120)
        log.info("[%s] Recovered via claude CLI (%s)", label, model)
        _emit(label, model, "claude_cli", t0, True)
        return text
    except Exception as e:
        log.warning("[%s] claude CLI failed (%s) — NVIDIA %s fallback",
                    label, e, nvidia_tier)

    # ── 2. Last resort: NVIDIA NIM ────────────────────────────────────────
    try:
        import nvidia_model_router as nvr
    except Exception as e:
        _emit(label, model, "claude", t0, False,
              f"All Claude backends failed; NVIDIA router unavailable: {e}")
        raise RuntimeError(
            f"[{label}] All Claude backends failed and NVIDIA router unavailable: {e}"
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

    _emit(label, model, "nvidia", t0, False, f"all backends failed: {last_err}")
    raise RuntimeError(
        f"[{label}] all backends failed (Claude SDK + CLI + NVIDIA {nvidia_tier}): {last_err}"
    )
