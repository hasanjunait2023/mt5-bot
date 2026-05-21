"""
StrategyScout — autonomous trading-edge collector and idea generator.

Scout's job is NOT to trade. It hunts the world for trading edges (RSS / trader
blogs, recurring news-event setups), invents novel setups with Claude, then
normalizes every idea into the canonical DEFAULT_PARAMS dict so the existing
StrategyResearcher can backtest it. It refuses to emit garbage: every idea is
deduped against the knowledge base and confidence-screened before return.

Usage:
  python -m trading_agents.strategy_scout.strategy_scout --once
  python -m trading_agents.strategy_scout.strategy_scout --once --source claude_brainstorm
"""

import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("StrategyScout")

BASE_DIR    = Path(__file__).parent.parent.parent
CONFIG_FILE = Path(__file__).parent / "scout_config.json"
KB_FILE     = BASE_DIR / "trading_agents" / "knowledge_base.json"

# Canonical strategy parameter schema (must match mt5_bridge/config.py DEFAULT_PARAMS)
DEFAULT_PARAMS = {
    "EMA_Fast": 9, "EMA_Slow": 21, "RSI_Period": 7, "RSI_OB": 75, "RSI_OS": 25,
    "ATR_Period": 14, "ATR_SL_Multi": 1.0, "BB_Period": 20, "BB_Deviation": 2.0,
    "MACD_Fast": 8, "MACD_Slow": 17, "MACD_Signal": 9, "MomCandles": 3,
    "MinCandleBody": 0.3, "RiskPerTrade": 1.0, "RewardPerTrade": 2.0,
    "MaxDrawdownPct": 20.0, "RequiredScore": 4, "InitialBalance": 100.0,
    "RiskPct": 1.0, "UseTrailingTP": False, "TrailTrigger": 0.5, "TrailStep": 0.5,
    "MaxTradeBars": 0, "EMASlopePeriod": 5, "EMASlopeMin": 0.1,
}

SCOUT_PERSONA = """You are Scout — a world-class quant researcher who never sleeps.
You are curious, globally aware, and ruthlessly skeptical. You hunt for genuine
trading edges and invent novel setups, but you never inflate confidence. Your job
is to find edges and describe them precisely — not to trade them."""

NORMALIZE_PROMPT = SCOUT_PERSONA + """

Convert the raw trading idea(s) below into strict JSON. For EACH distinct strategy
produce one object. The "parameters" object MUST contain EXACTLY these keys with
numeric/boolean values (use sensible values implied by the idea, else the default):

{param_schema}

Output ONLY a JSON array, each element:
{{
  "parameters": {{ ...all keys above... }},
  "description": "concise strategy name + setup",
  "type": "technical_combination|pattern_based|mean_reversion_bb|breakout_momentum",
  "timeframes": ["M5"],
  "symbols": ["EURUSD"],
  "confidence_score": 0.0-1.0,
  "entry_rules": ["..."],
  "exit_rules": ["..."],
  "session_preference": "London|NY|Asian|24h|unknown",
  "notes": "caveats or inferred params"
}}

confidence_score must honestly reflect how well-specified and plausible the edge is.
Output nothing but the JSON array."""

BRAINSTORM_PROMPT = SCOUT_PERSONA + """

Invent {n} NOVEL, concrete trading strategies the system does NOT already have.
Favour ideas with a high expected win-rate and a strong reward:risk profile.
Avoid generic "EMA crossover" clichés — be specific about the edge and why it
should work. Target these under-covered areas:

{gaps}

Return them as plain prose (one paragraph per idea, numbered). Be specific about
indicators, thresholds, entry/exit logic, session, and the symbols it suits."""


def _cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _load_kb() -> dict:
    if KB_FILE.exists():
        try:
            return json.loads(KB_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── Source 1: RSS / web feeds ─────────────────────────────────────────────────

def _fetch_rss(feeds: list[str], per_feed: int = 4) -> list[str]:
    """Return raw text snippets from RSS feeds. Each feed failure is isolated."""
    snippets: list[str] = []
    for url in feeds:
        try:
            resp = requests.get(url, timeout=12, headers={"User-Agent": "StrategyScout/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.iter("item")
            count = 0
            for item in items:
                title = (item.findtext("title") or "").strip()
                desc = (item.findtext("description") or "").strip()
                if title or desc:
                    snippets.append(f"[{url}] {title}\n{desc[:600]}")
                    count += 1
                if count >= per_feed:
                    break
        except Exception as e:
            log.warning("RSS feed failed (%s): %s — skipping", url, e)
    return snippets


# ── Source 2: news-driven setups ──────────────────────────────────────────────

def _fetch_news_context() -> str:
    try:
        sys.path.insert(0, str(BASE_DIR / "mt5_bridge"))
        from news_filter import fetch_ff_calendar  # type: ignore
        events = fetch_ff_calendar()
        high = [e for e in events if str(e.get("impact", "")).lower() in ("high", "red")][:15]
        if not high:
            return ""
        lines = [f"{e.get('country','')} {e.get('title','')} @ {e.get('date','')}" for e in high]
        return "Recurring high-impact events this week:\n" + "\n".join(lines)
    except Exception as e:
        log.warning("News context unavailable: %s", e)
        return ""


# ── Source 4: knowledge-base gap analysis ─────────────────────────────────────

def _gap_analysis(target_symbols: list[str]) -> str:
    kb = _load_kb()
    symbols = kb.get("symbols", {})
    gaps = []
    regimes = ["trending", "ranging", "volatile", "neutral"]
    for sym in target_symbols:
        sym_data = symbols.get(sym, {})
        successful = sym_data.get("successful_patterns", [])
        covered = {p.get("market_regime") for p in successful}
        missing = [r for r in regimes if r not in covered]
        if missing or not successful:
            gaps.append(f"- {sym}: no proven edge for regime(s) {missing or regimes}")
    return "\n".join(gaps) if gaps else "- General improvement across all target symbols"


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize(raw_blobs: list[str], client: anthropic.Anthropic) -> list[dict]:
    if not raw_blobs:
        return []
    schema = json.dumps(DEFAULT_PARAMS, indent=2)
    prompt = NORMALIZE_PROMPT.format(param_schema=schema)
    joined = "\n\n---\n\n".join(raw_blobs)[:12000]
    try:
        # Claude Opus 4.7 + adaptive thinking; auto-fallback to NVIDIA if Claude down
        sys.path.insert(0, str(BASE_DIR / "trading_agents"))
        from llm_fallback import chat_resilient
        text = chat_resilient(client, system=prompt,
                              user=f"Raw trading ideas:\n\n{joined}",
                              max_tokens=16000, nvidia_tier="ULTRA",
                              label="scout_normalize").strip()
        start, end = text.find("["), text.rfind("]") + 1
        ideas = json.loads(text[start:end]) if start >= 0 else []
    except Exception as e:
        log.error("Normalization failed: %s", e)
        return []

    cleaned = []
    for idea in ideas:
        params = {**DEFAULT_PARAMS, **(idea.get("parameters") or {})}
        # keep only known keys, coerce types loosely
        params = {k: params.get(k, v) for k, v in DEFAULT_PARAMS.items()}
        idea["parameters"] = params
        idea.setdefault("symbols", ["EURUSD"])
        idea.setdefault("confidence_score", 0.5)
        cleaned.append(idea)
    return cleaned


# ── Screening / dedup ─────────────────────────────────────────────────────────

def _param_similarity(a: dict, b: dict) -> float:
    keys = [k for k, v in DEFAULT_PARAMS.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not keys:
        return 0.0
    same = 0
    for k in keys:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            continue
        hi = max(abs(av), abs(bv), 1e-9)
        if abs(av - bv) / hi < 0.10:  # within 10%
            same += 1
    return same / len(keys)


def _screen(ideas: list[dict], min_conf: float, dedup_sim: float) -> list[dict]:
    kb = _load_kb()
    existing = []
    for sym_data in kb.get("symbols", {}).values():
        for p in sym_data.get("successful_patterns", []):
            if p.get("parameters"):
                existing.append(p["parameters"])

    kept = []
    for idea in ideas:
        if idea.get("confidence_score", 0) < min_conf:
            log.info("Screened out (low conf %.2f): %s", idea.get("confidence_score", 0), idea.get("description", "")[:60])
            continue
        dup = any(_param_similarity(idea["parameters"], ex) >= dedup_sim for ex in existing)
        if dup:
            log.info("Screened out (duplicate): %s", idea.get("description", "")[:60])
            continue
        kept.append(idea)
    return kept


# ── Public API ────────────────────────────────────────────────────────────────

def collect_ideas(limit: int | None = None, only_source: str | None = None) -> list[dict]:
    """Collect, normalize, and screen strategy ideas. Returns canonical dicts."""
    cfg = _cfg()
    sources = cfg.get("sources", {})
    target_symbols = cfg.get("target_symbols", ["EURUSD"])
    limit = limit or cfg.get("ideas_per_cycle", 5)
    client = _client()

    raw: list[str] = []

    if (only_source in (None, "rss")) and sources.get("rss"):
        raw += _fetch_rss(cfg.get("rss_feeds", []))

    if (only_source in (None, "firecrawl")) and sources.get("firecrawl"):
        try:
            from trading_agents.strategy_scout.firecrawl_source import fetch as _fc_fetch
            raw += _fc_fetch(cfg.get("firecrawl_urls", []))
        except Exception as e:
            log.warning("Firecrawl source failed: %s", e)

    if (only_source in (None, "news")) and sources.get("news"):
        nc = _fetch_news_context()
        if nc:
            raw.append(nc)

    if (only_source in (None, "claude_brainstorm")) and sources.get("claude_brainstorm"):
        gaps = _gap_analysis(target_symbols)
        try:
            # Claude Opus 4.7 + adaptive thinking; auto-fallback to NVIDIA if Claude down
            sys.path.insert(0, str(BASE_DIR / "trading_agents"))
            from llm_fallback import chat_resilient
            bs = chat_resilient(client, system=SCOUT_PERSONA,
                                user=BRAINSTORM_PROMPT.format(n=3, gaps=gaps),
                                max_tokens=16000, nvidia_tier="ULTRA",
                                label="scout_brainstorm").strip()
            raw.append("[claude_brainstorm]\n" + bs)
        except Exception as e:
            log.warning("Brainstorm failed: %s", e)

    if (only_source in (None, "gap_fill")) and sources.get("gap_fill"):
        raw.append("[gap_fill targets]\n" + _gap_analysis(target_symbols))

    log.info("Collected %d raw blob(s) from sources", len(raw))
    ideas = _normalize(raw, client)
    log.info("Normalized to %d candidate idea(s)", len(ideas))

    th = cfg.get("thresholds", {})
    ideas = _screen(ideas, th.get("min_confidence", 0.45), th.get("dedup_similarity", 0.9))
    log.info("After screening: %d idea(s)", len(ideas))

    for idea in ideas:
        idea.setdefault("source", only_source or "mixed")
        idea["collected_at"] = datetime.now(timezone.utc).isoformat()

    return ideas[:limit]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    src = None
    if "--source" in sys.argv:
        src = sys.argv[sys.argv.index("--source") + 1]
    result = collect_ideas(only_source=src)
    print(json.dumps(result, indent=2))
    print(f"\n{len(result)} idea(s) collected.")
