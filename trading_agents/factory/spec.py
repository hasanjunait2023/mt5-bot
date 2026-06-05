"""Merge research artifacts into one canonical strategy spec + a human plan.

The spec is the single input to codegen. It captures the mechanical strategy plus
a tunable_params grid the optimizer can sweep.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from trading_agents.factory import state as st

log = logging.getLogger("factory.spec")

_DEFAULT_SYMBOLS = ["XAUUSD"]

_SPEC_SYSTEM = """You are a quant who turns trading-strategy research into a precise,
backtestable spec. You are given NotebookLM Q&A, a video-extracted strategy JSON,
and/or a transcript. Synthesize ONE canonical strategy.

Output ONLY a JSON object with EXACTLY these keys:
{
  "name": "short strategy name",
  "strategy_type": "trend_following|mean_reversion|breakout|ict_smc|momentum|other",
  "symbols": ["XAUUSD"],            // pick what the source targets; default XAUUSD
  "timeframe": "M1|M3|M5|M15",      // the ENTRY timeframe
  "indicators": ["ema","atr",...],  // ONLY from the allowed catalog you are given
  "entry_rules": ["mechanical bullet", ...],
  "exit_rules": ["stop-loss rule", "take-profit rule"],
  "sl_rule": "exact stop-loss placement",
  "tp_rule": "exact take-profit / RR",
  "rr": 2.0,
  "session_filter": true|false,     // restrict to London/NY kill-zones?
  "tunable_params": {"param_name": [v1, v2, v3], ...},  // small grid (<=4 params, <=4 values each)
  "confidence": 0.0-1.0,
  "notes": "caveats, missing detail, assumptions"
}
Use ONLY indicators from this allowed catalog (others do not exist):
ema, atr, rsi, stoch, bollinger, keltner, vwap_session, ema_cross, ema_above,
swing_high, swing_low, has_bullish_fvg, has_bearish_fvg, find_fvg_zones,
find_inverse_fvg, detect_liquidity_sweep, detect_trendline_break, session_info."""


def _read(path: str | None, limit: int = 6000) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")[:limit]


def merge_spec(job: dict) -> dict:
    """MERGE_SPEC: combine artifacts into a canonical spec dict, save it, return it."""
    from trading_agents.llm_fallback import chat_resilient
    art = job.get("artifacts", {})
    bundle = {
        "video_meta": {
            "title": job.get("source", {}).get("title", ""),
            "channel": job.get("source", {}).get("channel", ""),
            "description": (job.get("source", {}).get("description", "") or "")[:1500],
        },
        "notebook_discovery": _read(art.get("discovery_qa")),
        "notebook_deep": _read(art.get("deep_qa")),
        "video_spec": _read(art.get("video_spec"), 4000),
        "transcript_excerpt": _read(art.get("transcript"), 4000),
    }
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        client = None
    spec = _fallback_spec(job)
    try:
        raw = chat_resilient(client, system=_SPEC_SYSTEM,
                             user=json.dumps(bundle, ensure_ascii=False)[:14000],
                             max_tokens=2500, model="claude-opus-4-8", thinking=True,
                             nvidia_tier="ULTRA", label="factory_spec")
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            spec.update({k: v for k, v in parsed.items() if v is not None})
    except Exception as e:  # noqa: BLE001
        log.warning("spec synthesis failed (%s) — using fallback spec", e)

    hint = job.get("source", {}).get("symbols_hint")
    if not spec.get("symbols") and hint:
        spec["symbols"] = hint
    spec.setdefault("symbols", _DEFAULT_SYMBOLS)
    if not spec.get("symbols"):
        spec["symbols"] = _DEFAULT_SYMBOLS
    spec.setdefault("timeframe", "M3")
    spec["source_url"] = job.get("source", {}).get("youtube_url", "")

    out = st.artifact_dir(job["job_id"]) / "spec.json"
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    job["artifacts"]["merged_spec"] = str(out)
    st.save_job(job)
    return spec


def _fallback_spec(job: dict) -> dict:
    return {
        "name": (job.get("source", {}).get("title") or "Untitled Strategy")[:48],
        "strategy_type": "other",
        "symbols": list(_DEFAULT_SYMBOLS),
        "timeframe": "M3",
        "indicators": ["ema", "atr", "rsi"],
        "entry_rules": [],
        "exit_rules": [],
        "sl_rule": "1.5 ATR beyond entry",
        "tp_rule": "2:1 reward:risk",
        "rr": 2.0,
        "session_filter": False,
        "tunable_params": {},
        "confidence": 0.2,
        "notes": "fallback spec — LLM synthesis unavailable",
    }


def build_plan(job: dict, spec: dict) -> str:
    """BUILD_PLAN: render a concise markdown plan for the user to approve."""
    entry = [f"- {r}" for r in spec.get("entry_rules", [])] or ["- (none extracted)"]
    exits = [f"- {r}" for r in spec.get("exit_rules", [])]
    tunables = [f"- {k}: {v}" for k, v in (spec.get("tunable_params") or {}).items()] or ["- (none)"]
    lines = [
        f"# Strategy Build Plan — {spec.get('name', '?')}",
        "",
        f"**Source:** {spec.get('source_url', '')}",
        f"**Type:** {spec.get('strategy_type', '?')}  |  **Symbols:** {', '.join(spec.get('symbols', []))}"
        f"  |  **Entry TF:** {spec.get('timeframe', '?')}",
        f"**Indicators:** {', '.join(spec.get('indicators', []))}",
        f"**Confidence:** {spec.get('confidence', 0)}",
        "",
        "## Entry rules",
        *entry,
        "",
        "## Exit / risk",
        f"- SL: {spec.get('sl_rule', '?')}",
        f"- TP: {spec.get('tp_rule', '?')}  (RR {spec.get('rr', '?')})",
        *exits,
        f"- Session filter: {spec.get('session_filter', False)}",
        "",
        "## Tunable params (optimizer grid)",
        *tunables,
        "",
        "## Notes",
        spec.get("notes", ""),
        "",
        "_Approve to generate code → backtest → (gate) → optimize → demo soak._",
    ]
    md = "\n".join(lines)
    out = st.artifact_dir(job["job_id"]) / "build_plan.md"
    out.write_text(md, encoding="utf-8")
    job["artifacts"]["build_plan"] = str(out)
    st.save_job(job)
    return md
