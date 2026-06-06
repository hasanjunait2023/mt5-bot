"""Source Hunter — the autonomous daily front door to the Strategy Factory.

Every run it sweeps the world for institutional-grade trading strategies across
four source kinds, has an LLM curate them down to the best-of-the-best, and opens
a Factory job for each survivor. The Factory then carries each candidate hands-free
through codegen → backtest → optimize → demo soak; a human only approves the final
demo→real-money promotion (GATE_LIVE).

Sources (each toggleable in hunter_config.json):
  - youtube     : newest uploads of a curated channel list  -> Factory YT path
  - web         : RSS / blog feeds (institutional desks, edu) -> spec-first job
  - llm         : Claude invents novel institutional setups   -> spec-first job
  - papers      : arXiv q-fin recent abstracts                -> spec-first job

Dedup is persistent (logs/factory/_hunter_state.json): a video id / content hash is
never processed twice. Per-run caps bound LLM/codegen cost.

Usage:
  python -m trading_agents.factory.source_hunter --once
  python -m trading_agents.factory.source_hunter --loop --interval 24
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from trading_agents.factory import state as st
from trading_agents.factory import youtube as yt

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("factory.source_hunter")

CONFIG_FILE = Path(__file__).parent / "hunter_config.json"
STATE_FILE = st.FACTORY_DIR / "_hunter_state.json"

_DEFAULT_CFG = {
    "interval_hours": 24,
    "sources": {"youtube": True, "web": True, "llm": True, "papers": True},
    "youtube_channels": [],
    "videos_per_channel": 4,
    "web_feeds": [
        "https://www.babypips.com/feed.rss",
        "https://www.forexlive.com/feed/news",
    ],
    "arxiv_query": "cat:q-fin.TR OR cat:q-fin.PM OR cat:q-fin.ST",
    "arxiv_max": 8,
    "llm_ideas_per_run": 3,
    "target_symbols": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"],
    "curation_min_score": 65,
    "max_youtube_jobs_per_run": 3,
    "max_text_jobs_per_run": 4,
    "max_jobs_per_run": 5,
}

_CURATE_SYSTEM = """You are the gatekeeper of an institutional strategy factory. You
score raw trading-strategy candidates on whether they are worth the expensive build
+ backtest pipeline. You are ruthless: most retail content is junk.

Score 0-100 on institutional quality:
  90-100: precise, mechanical, institutional concept (order flow, liquidity, vol
          regime, statistical edge) with clear entry/exit/risk.
  65-89 : plausible, reasonably specific edge worth testing.
  40-64 : vague / generic / retail cliche (lone EMA cross, "trade the trend").
  0-39  : not a tradeable mechanical strategy / pure hype / no edge.

For EACH candidate return one object. Output ONLY a JSON array, no prose:
[{"i": <index>, "score": <0-100>, "verdict": "<one line why>",
  "symbols": ["XAUUSD"], "title": "<concise strategy name>"}]"""

_LLM_IDEA_SYSTEM = """You are a world-class quant who invents novel, MECHANICAL,
institutional-grade trading strategies — order flow, liquidity sweeps, volatility
regime, session statistics, mean-reversion with a real edge. Never generic retail
cliches. Be precise: indicators, thresholds, entry, exit, stop, target, session,
and the instruments it suits."""

_LLM_IDEA_USER = """Invent {n} distinct, concrete strategies the desk does not yet
have. For EACH, write a self-contained paragraph precise enough to code and backtest
directly (entry trigger, exit, stop placement, target/RR, session, symbols from:
{symbols}). Number them. Plain prose, one paragraph each."""


# ── config / state ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    cfg = dict(_DEFAULT_CFG)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen_videos": [], "seen_hashes": [], "runs": 0, "created_jobs": []}


def _save_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").strip().lower().encode()).hexdigest()[:16]


_STOP = {"the", "a", "an", "of", "and", "on", "in", "for", "with", "to", "strategy",
         "trading", "trade", "setup", "system", "based", "using"}


def _tokset(title: str) -> set:
    import re
    return {w for w in re.split(r"[^a-z0-9]+", (title or "").lower()) if w and w not in _STOP}


def _is_dup_title(title: str, existing: list, thresh: float = 0.6) -> bool:
    """Jaccard token-overlap vs already-discovered titles — blocks rediscovering the
    same edge under a slightly different name."""
    a = _tokset(title)
    if not a:
        return False
    for ex in existing:
        b = _tokset(ex)
        if b and len(a & b) / len(a | b) >= thresh:
            return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _notify(msg: str, level: str = "INFO") -> None:
    try:
        from trading_agents import telegram_hq
        telegram_hq.send("ceo", msg, level=level)
    except Exception:
        pass


def _llm(system: str, user: str, label: str, max_tokens: int = 4000) -> str:
    """Resilient Claude→NVIDIA call. Empty string on failure."""
    try:
        import anthropic
        from trading_agents.llm_fallback import chat_resilient
        try:
            client = anthropic.Anthropic()
        except Exception:
            client = None
        return chat_resilient(client, system=system, user=user, max_tokens=max_tokens,
                              model="claude-opus-4-8", nvidia_tier="ULTRA", label=label) or ""
    except Exception as e:  # noqa: BLE001
        log.warning("LLM call (%s) failed: %s", label, e)
        return ""


# ── source: web feeds (RSS) ───────────────────────────────────────────────────

def _collect_web(cfg: dict) -> list[dict]:
    out: list[dict] = []
    for url in cfg.get("web_feeds", []):
        try:
            resp = requests.get(url, timeout=12, headers={"User-Agent": "SourceHunter/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            count = 0
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                desc = (item.findtext("description") or "").strip()
                if not (title or desc):
                    continue
                out.append({"kind": "web", "title": title[:120],
                            "text": f"{title}\n{desc}"[:4000], "ref": url})
                count += 1
                if count >= 4:
                    break
        except Exception as e:  # noqa: BLE001
            log.warning("web feed failed (%s): %s", url, e)
    # firecrawl (optional, if module + key present)
    try:
        from trading_agents.strategy_scout.firecrawl_source import fetch as _fc
        for blob in _fc(cfg.get("web_urls", [])) or []:
            out.append({"kind": "web", "title": blob[:80], "text": blob[:4000], "ref": "firecrawl"})
    except Exception:
        pass
    return out


# ── source: arXiv q-fin papers ────────────────────────────────────────────────

def _collect_papers(cfg: dict) -> list[dict]:
    q = cfg.get("arxiv_query", "cat:q-fin.TR")
    n = cfg.get("arxiv_max", 8)
    url = ("http://export.arxiv.org/api/query?search_query="
           + requests.utils.quote(q)
           + f"&sortBy=submittedDate&sortOrder=descending&max_results={n}")
    out: list[dict] = []
    resp = None
    for attempt in range(3):  # arXiv rate-limits aggressively; back off and retry
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "SourceHunter/1.0"})
            resp.raise_for_status()
            break
        except Exception as e:  # noqa: BLE001
            log.warning("arXiv fetch attempt %d failed: %s", attempt + 1, e)
            resp = None
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    if resp is None:
        return out
    try:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.content)
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            summ = (e.findtext("a:summary", default="", namespaces=ns) or "").strip()
            ref = (e.findtext("a:id", default="", namespaces=ns) or "").strip()
            if title and summ:
                out.append({"kind": "papers", "title": title[:120],
                            "text": f"{title}\n\n{summ}"[:4000], "ref": ref})
    except Exception as e:  # noqa: BLE001
        log.warning("arXiv parse failed: %s", e)
    return out


# ── source: LLM-invented ideas ────────────────────────────────────────────────

def _collect_llm(cfg: dict) -> list[dict]:
    n = cfg.get("llm_ideas_per_run", 3)
    syms = ", ".join(cfg.get("target_symbols", ["XAUUSD"]))
    prose = _llm(_LLM_IDEA_SYSTEM, _LLM_IDEA_USER.format(n=n, symbols=syms),
                 label="hunter_llm_ideas", max_tokens=4000)
    if not prose:
        return []
    # Split on numbered paragraphs ("1." ... "2." ...).
    import re
    chunks = re.split(r"\n(?=\s*\d+[\.\)]\s)", prose.strip())
    out = []
    for ch in chunks:
        ch = ch.strip()
        if len(ch) < 80:
            continue
        title = re.sub(r"^\s*\d+[\.\)]\s*", "", ch).split("\n")[0][:120]
        out.append({"kind": "llm", "title": title, "text": ch[:4000], "ref": "claude"})
    return out


# ── source: YouTube channels ──────────────────────────────────────────────────

import re as _re

# Word-boundary matched (short tokens that appear as substrings in unrelated words).
_STRATEGY_TITLE_WORDS = {"ict", "smc", "fvg", "bos", "ea"}
# Substring matched (safe multi-word phrases unlikely to appear in noise).
_STRATEGY_TITLE_KW = {
    "strategy", "setup", "backtest", "backtesting", "system", "indicator",
    "scalp", "swing", "breakout", "reversal", "orderblock", "order block",
    "liquidity", "fibonacci", "fair value", "choch", "how to trade", "confluence",
    "algo trading", "automated trading", "pine script", "quant", "mechanical",
    "high probability", "risk reward", "smart money", "institutional",
    "supply demand", "supply and demand", "market structure", "price action",
    "trade setup", "trading system", "live trade", "profit factor",
    "expert advisor", "mql5", "ninjatrader", "python trading",
    "forex strategy", "gold strategy", "xauusd", "eurusd strategy",
}
_REJECT_TITLE_KW = {
    "day in the life", "my journey", "motivat", "mindset", "mental", "goals 20",
    "i became", "week in review", "market news", "economic calendar", "this week in",
    "forex news", "q&a", "interview", "vlog", "reaction", "story time",
    "portfolio update", "results video", "income report", "how i made",
    "for beginners", "beginner", "beginner's", "prediction market", "nfl",
    "sports betting", "crypto news", "nba", "it was too slow",
}


def _is_strategy_title(title: str) -> bool:
    t = title.lower()
    if any(kw in t for kw in _REJECT_TITLE_KW):
        return False
    if any(kw in t for kw in _STRATEGY_TITLE_KW):
        return True
    return any(_re.search(r"\b" + kw + r"\b", t) for kw in _STRATEGY_TITLE_WORDS)


def _collect_youtube(cfg: dict, state: dict) -> tuple[list[dict], list[str]]:
    """Returns (strategy_candidates, title_filtered_video_ids).
    Caller persists title_filtered_video_ids into seen_videos so they are
    never re-checked in future runs."""
    seen = set(state.get("seen_videos", []))
    out: list[dict] = []
    title_filtered_ids: list[str] = []
    for ch in cfg.get("youtube_channels", []):
        for v in yt.list_channel_videos(ch, cfg.get("videos_per_channel", 4)):
            if v["video_id"] in seen:
                continue
            if not _is_strategy_title(v["title"]):
                title_filtered_ids.append(v["video_id"])
                log.debug("title-filter skip: %s", v["title"])
                continue
            out.append({"kind": "youtube", "title": v["title"][:120],
                        "text": v["title"], "ref": v["url"],
                        "video_id": v["video_id"]})
    if title_filtered_ids:
        log.info("title-filter skipped %d non-strategy YouTube video(s)", len(title_filtered_ids))
    return out, title_filtered_ids


# ── curation ──────────────────────────────────────────────────────────────────

def _curate(candidates: list[dict]) -> list[dict]:
    """LLM-score TEXT candidates (web/llm/papers) on their full content. YouTube is
    NOT curated here — a video's edge lives in the transcript, not the (often
    clickbait) title, so title-curation wrongly rejects good strategy videos. Videos
    pass through with a neutral score and are filtered downstream by the Factory's
    CLASSIFY + transcript research."""
    if not candidates:
        return []
    yt = [c for c in candidates if c["kind"] == "youtube"]
    text = [c for c in candidates if c["kind"] != "youtube"]
    for c in yt:
        c["score"] = 50  # neutral; Factory CLASSIFY is the real filter for videos
        c["verdict"] = "video — Factory will classify transcript"
        c["symbols"] = None

    if text:
        listing = "\n\n".join(
            f"[{i}] ({c['kind']}) {c['title']}\n{c.get('text','')[:1200]}"
            for i, c in enumerate(text)
        )[:18000]
        raw = _llm(_CURATE_SYSTEM, f"Candidates:\n\n{listing}", label="hunter_curate",
                   max_tokens=3000)
        scores: dict[int, dict] = {}
        if raw:
            try:
                arr = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
                for o in arr:
                    scores[int(o.get("i"))] = o
            except Exception as e:  # noqa: BLE001
                log.warning("curation parse failed: %s", e)
        for i, c in enumerate(text):
            s = scores.get(i, {})
            c["score"] = int(s.get("score", 50))
            c["verdict"] = s.get("verdict", "unscored")
            c["symbols"] = s.get("symbols") or None
            if s.get("title"):
                c["title"] = s["title"][:120]
    return sorted(candidates, key=lambda c: c["score"], reverse=True)


# ── job creation ──────────────────────────────────────────────────────────────

def _open_job(c: dict) -> dict | None:
    try:
        if c["kind"] == "youtube":
            job = st.new_job(c["ref"], title=c["title"])
        else:
            job = st.new_job_from_text(
                c.get("text", ""), title=c["title"], source_kind=c["kind"],
                source_ref=c.get("ref", ""), symbols=c.get("symbols"))
        return job
    except Exception as e:  # noqa: BLE001
        log.error("failed to open job for %s: %s", c.get("title"), e)
        return None


# ── one run ───────────────────────────────────────────────────────────────────

def run_once() -> dict:
    cfg = _cfg()
    state = _load_state()
    state["runs"] = state.get("runs", 0) + 1
    srcs = cfg.get("sources", {})
    seen_hashes = set(state.get("seen_hashes", []))
    seen_videos = set(state.get("seen_videos", []))

    candidates: list[dict] = []
    title_filtered_ids: list[str] = []
    if srcs.get("youtube"):
        yt_cands, title_filtered_ids = _collect_youtube(cfg, state)
        candidates += yt_cands
    if srcs.get("web"):
        candidates += _collect_web(cfg)
    if srcs.get("llm"):
        candidates += _collect_llm(cfg)
    if srcs.get("papers"):
        candidates += _collect_papers(cfg)

    # Dedup vs persistent state.
    fresh = []
    for c in candidates:
        if c["kind"] == "youtube":
            if c["video_id"] in seen_videos:
                continue
        else:
            h = _hash(c.get("text", ""))
            if h in seen_hashes:
                continue
            c["_hash"] = h
        fresh.append(c)

    log.info("collected %d candidate(s), %d fresh", len(candidates), len(fresh))
    ranked = _curate(fresh)

    min_score = cfg.get("curation_min_score", 65)
    max_yt = cfg.get("max_youtube_jobs_per_run", 3)
    max_text = cfg.get("max_text_jobs_per_run", 4)
    max_total = cfg.get("max_jobs_per_run", 5)

    # Titles already discovered (past runs) — don't rediscover the same edge.
    known_titles = [r.get("title", "") for r in state.get("created_jobs", [])]
    try:
        known_titles += [j.get("title", "") for j in
                         (json.loads((st.FACTORY_DIR / "_index.json").read_text(encoding="utf-8")) or {}).values()]
    except Exception:
        pass

    # YouTube is curated on TITLE only (cheap) → clickbait titles under-score real
    # strategy videos. So videos use a LOW floor and lean on the Factory's CLASSIFY +
    # transcript research (the real content filter); text sources keep the full bar.
    yt_min = cfg.get("youtube_min_score", 40)
    created, yt_n, text_n, dup_skipped = [], 0, 0, 0
    for c in ranked:
        if len(created) >= max_total:
            break
        floor = yt_min if c["kind"] == "youtube" else min_score
        if c["score"] < floor:
            continue
        if c["kind"] == "youtube" and yt_n >= max_yt:
            continue
        if c["kind"] != "youtube" and text_n >= max_text:
            continue
        if _is_dup_title(c["title"], known_titles):
            dup_skipped += 1
            log.info("skip dup-title: %s", c["title"])
            continue
        job = _open_job(c)
        if not job:
            continue
        known_titles.append(c["title"])  # block near-dupes within this same run too
        # Mark consumed (so we never reprocess even if the job later fails).
        if c["kind"] == "youtube":
            seen_videos.add(c["video_id"])
            yt_n += 1
        else:
            seen_hashes.add(c.get("_hash", _hash(c.get("text", ""))))
            text_n += 1
        rec = {"job_id": job["job_id"], "title": c["title"], "kind": c["kind"],
               "score": c["score"], "verdict": c["verdict"], "at": _now()}
        created.append(rec)
        log.info("opened %s [%s %d] %s", job["job_id"], c["kind"], c["score"], c["title"])

    # YouTube videos are marked "seen" ONLY when OPENED (in the loop above) — never by
    # score, since they aren't title-scored. A backlog-rich channel (one video per
    # big-trader strategy) therefore drains a few videos per run over many runs instead
    # of being burned in one pass; the Factory CLASSIFY stage rejects non-strategies.

    # Persist title-filtered video IDs so they are never re-checked in future runs.
    seen_videos.update(title_filtered_ids)
    state["seen_videos"] = list(seen_videos)[-3000:]
    state["seen_hashes"] = list(seen_hashes)[-4000:]
    state["created_jobs"] = (state.get("created_jobs", []) + created)[-500:]
    scorecard = {
        "run": state["runs"], "collected": len(candidates), "fresh": len(fresh),
        "opened": len(created), "dup_skipped": dup_skipped,
        "top": [r["title"] for r in created[:5]],
        "at": _now(),
    }
    state["last_scorecard"] = scorecard
    _save_state(state)

    if created:
        lines = "\n".join(f"• [{r['score']}] {r['title']} ({r['kind']})" for r in created)
        dup_note = f" · {dup_skipped} dup-skipped" if dup_skipped else ""
        _notify(f"🔭 Source Hunter run #{state['runs']}: opened {len(created)} Factory job(s) "
                f"(from {len(fresh)} fresh / {len(candidates)} scanned{dup_note})\n{lines}\n"
                f"→ autonomous build→backtest→demo soak. Real-money still needs your OK in /factory.")
    else:
        log.info("run #%d: nothing cleared the bar (scanned %d)", state["runs"], len(candidates))
    return scorecard


def run_loop(interval_hours: float | None = None) -> None:
    interval = interval_hours or _cfg().get("interval_hours", 24)
    log.info("Source Hunter loop — every %.1fh", interval)
    while True:
        try:
            run_once()
        except Exception as e:  # noqa: BLE001
            log.error("hunter run crashed: %s", e)
            _notify(f"🔭 Source Hunter CRITICAL: run crashed — {e}", level="CRITICAL")
        time.sleep(interval * 3600)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=None)
    args = ap.parse_args()
    if args.loop:
        run_loop(args.interval)
    else:
        print(json.dumps(run_once(), indent=2, default=str))


if __name__ == "__main__":
    main()
