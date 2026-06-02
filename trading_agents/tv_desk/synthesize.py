"""synthesize — turn structural facts into concrete entries.

The deterministic detectors produce facts (zones, pools, OBs, dealing range).
The LLM (llm_fallback.chat_resilient) reads those facts and proposes entries
with a narrative + win-probability. A deterministic validator then RECOMPUTES
SL/TP so the risk:reward is exactly the configured target — the LLM can suggest
direction/levels but can never emit broken math. If the LLM is unavailable, a
structure-based fallback still generates setups (the agents must always output).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from .. import llm_fallback
from . import config, news

log = logging.getLogger("tv_desk.synthesize")


def _client():
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


_SYSTEM = """You are an institutional intraday/scalp analyst (ICT / Smart-Money).
You read pre-computed market structure facts for ONE instrument and output a
trade plan. You think in liquidity (buy/sell-side pools, sweeps), premium/discount
of the dealing range, order blocks, fair-value gaps, and session context.

Rules:
- Output STRICT JSON only. No prose outside the JSON.
- Entries must be intraday/scalp (open and close within the day/session). Never swing.
- Each entry needs: side ("BUY"|"SELL"), entry (number), sl (number), type (short
  tag e.g. "OB mitigation","FVG fill","SSL sweep","supply reject"), reasons (array
  of 2-4 short strings), win_prob (0-100 integer, your honest estimate).
- Put SL at the structural invalidation (beyond the zone/sweep), NOT a fixed
  distance. TP is computed for you — do NOT invent tp.
- Prefer entries aligned with bias + discount(for buys)/premium(for sells), but
  you may include one counter setup if a clean liquidity sweep supports it.

JSON shape:
{"bias":"bullish|bearish|neutral","narrative":"2-4 sentence read",
 "entries":[{"side":"BUY","entry":123.4,"sl":120.0,"type":"...","reasons":["..."],"win_prob":58}]}
"""


def _user_prompt(facts: dict, n_entries: int) -> str:
    compact = {
        k: facts[k] for k in (
            "symbol", "name", "mode", "price", "dp", "atr_entry", "bias",
            "dealing_range", "pdh", "pdl", "asian_high", "asian_low",
            "fvgs", "entry_tf",
        ) if k in facts
    }
    for k in ("market_structure", "htf_levels", "session_ranges", "absorption"):
        if facts.get(k):
            compact[k] = facts[k]
    compact["zones"] = facts.get("zones", [])[:8]
    compact["pools"] = facts.get("pools", [])[:12]
    compact["order_blocks"] = facts.get("order_blocks", [])[:6]
    return (
        f"Produce up to {n_entries} {facts.get('mode')} entries for "
        f"{facts.get('name')} ({facts.get('symbol')}) on {facts.get('entry_tf')}.\n"
        f"Current price: {facts.get('price')}.\n\n"
        f"FACTS:\n{json.dumps(compact, default=str)}"
    )


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = re.sub(r"```(json)?", "", text).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except Exception:
        return None


# ── structure levels (for snap-gate + scoring) ───────────────────────────────
def _structure_levels(facts: dict) -> list[tuple[float, str]]:
    """All real price levels the agent detected, as (price, label)."""
    out: list[tuple[float, str]] = []
    for z in facts.get("zones", []):
        out += [(z["top"], f"{z['side']} zone"), (z["bottom"], f"{z['side']} zone"),
                ((z["top"] + z["bottom"]) / 2, f"{z['side']} zone")]
    for o in facts.get("order_blocks", []):
        out += [(o["top"], f"{o['side']} OB"), (o["bottom"], f"{o['side']} OB")]
    for f in facts.get("fvgs", []):
        out += [(f["top"], f"{f['side']} FVG"), (f["bottom"], f"{f['side']} FVG")]
    for p in facts.get("pools", []):
        out.append((p["price"], p.get("label", "pool")))
    for key, lab in (("pdh", "PDH"), ("pdl", "PDL")):
        if facts.get(key) is not None:
            out.append((facts[key], lab))
    for lab, v in (facts.get("htf_levels") or {}).items():
        out.append((v, lab.upper()))
    dr = facts.get("dealing_range") or {}
    if dr.get("equilibrium") is not None:
        out.append((dr["equilibrium"], "equilibrium"))
    return out


def _snap(entry: float, levels: list[tuple[float, str]], tol: float) -> tuple[bool, str]:
    best, label = None, ""
    for price, lab in levels:
        d = abs(entry - price)
        if best is None or d < best:
            best, label = d, lab
    return (best is not None and best <= tol), label


def _score(e: dict, facts: dict, snap_label: str) -> tuple[int, str, list[str]]:
    """0-100 confluence score + tier + factor list."""
    s, why = 0, []
    side = e["side"]
    bias = facts["bias"]["label"]
    ms = (facts.get("market_structure") or {}).get("trend")
    zone = (facts.get("dealing_range") or {}).get("zone")
    if (side == "BUY" and bias == "bullish") or (side == "SELL" and bias == "bearish"):
        s += 20; why.append("bias aligned")
    if (side == "BUY" and ms == "bullish") or (side == "SELL" and ms == "bearish"):
        s += 15; why.append("structure aligned")
    if (side == "BUY" and zone == "discount") or (side == "SELL" and zone == "premium"):
        s += 15; why.append(f"{zone} entry")
    lab = snap_label.lower()
    if "ob" in lab:   s += 14; why.append("at order block")
    elif "fvg" in lab: s += 12; why.append("at FVG")
    elif "zone" in lab: s += 12; why.append("at S/D zone")
    elif lab:          s += 8;  why.append(f"at {snap_label}")
    ab = facts.get("absorption")
    if ab and ((side == "BUY" and ab["side"] == "bull") or (side == "SELL" and ab["side"] == "bear")):
        s += 10; why.append("absorption confirm")
    wp = e.get("win_prob") or 50
    s += max(-8, min(8, int((wp - 50) / 5)))
    s = max(0, min(100, s))
    tier = "A" if s >= config.TIER_A_MIN else ("B" if s >= config.TIER_B_MIN else "C")
    return s, tier, why


def synthesize(facts: dict, *, mode: str = "intraday") -> dict:
    n = config.N_INTRADAY_ENTRIES if mode == "intraday" else config.N_SCALP_ENTRIES
    rr = config.RR_INTRADAY if mode == "intraday" else config.RR_SCALP

    parsed = None
    try:
        text = llm_fallback.chat_resilient(
            _client(),
            system=_SYSTEM,
            user=_user_prompt(facts, n),
            max_tokens=2200,
            model="claude-opus-4-8",
            thinking=True,
            nvidia_tier="ULTRA",
            label=f"tv_desk_{mode}",
        )
        parsed = _parse_json(text)
    except Exception as e:
        log.warning("LLM synth failed for %s: %s", facts.get("symbol"), e)

    horizon = config.NEWS_HORIZON_H.get(mode, 8)
    upcoming = news.upcoming(facts["symbol"], horizon)

    def _finish(entries, bias, narrative, source):
        for e in entries:
            e["news_warn"] = bool(upcoming)
        return {"bias": bias, "narrative": narrative, "entries": entries,
                "source": source, "news": upcoming}

    if parsed and parsed.get("entries"):
        entries = _validate(parsed["entries"], facts, rr, n, require_snap=True)
        if entries:
            return _finish(entries, parsed.get("bias", facts["bias"]["label"]),
                           parsed.get("narrative", ""), "llm")

    # fallback — structure-built, never empty (snap gate off; they ARE structure)
    raw = _fallback_entries(facts, rr, n)
    entries = _validate(raw, facts, rr, n, require_snap=False)
    return _finish(entries, facts["bias"]["label"], _fallback_narrative(facts), "fallback")


# ── validation (RR is recomputed deterministically) ──────────────────────────
def _validate(raw: list, facts: dict, rr: list[float], n: int,
              *, require_snap: bool = True) -> list[dict]:
    dp = int(facts.get("dp", 5))
    price = float(facts["price"])
    atr = float(facts.get("atr_entry") or 0) or price * 0.002
    levels = _structure_levels(facts)
    min_stop = config.MIN_STOP_ATR * atr
    snap_tol = config.SNAP_TOL_ATR * atr
    out: list[dict] = []
    for e in raw:
        try:
            side = str(e.get("side", "")).upper()
            entry = float(e["entry"])
            sl = float(e["sl"])
        except Exception:
            continue
        if side not in ("BUY", "SELL"):
            continue
        if side == "BUY" and not sl < entry:
            continue
        if side == "SELL" and not sl > entry:
            continue
        if abs(entry - price) > 8 * atr:        # sanity
            continue

        # snap-to-structure: reject mid-air entries (skip gate for fallback)
        ok, snap_label = _snap(entry, levels, snap_tol)
        if require_snap and not ok:
            continue

        # min-ATR stop floor (anti-noise): widen SL if too tight, keep RR exact
        risk = abs(entry - sl)
        if risk < min_stop:
            sl = entry - min_stop if side == "BUY" else entry + min_stop
            risk = min_stop
        tps = [round(entry + risk * r if side == "BUY" else entry - risk * r, dp) for r in rr]

        try:
            wp = max(1, min(99, int(round(float(e.get("win_prob"))))))
        except Exception:
            wp = 50

        item = {
            "side": side, "entry": round(entry, dp), "sl": round(sl, dp),
            "tp1": tps[0], "tp2": tps[1] if len(tps) > 1 else tps[0],
            "rr": rr, "type": str(e.get("type", "setup"))[:40],
            "reasons": [str(r)[:120] for r in (e.get("reasons") or [])][:4],
            "win_prob": wp,
        }
        score, tier, why = _score(item, facts, snap_label)
        item.update(score=score, tier=tier, snap=snap_label, score_reasons=why)
        out.append(item)
        if len(out) >= n:
            break
    # best setups first
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ── fallback generator (structure-based) ─────────────────────────────────────
def _fallback_entries(facts: dict, rr: list[float], n: int) -> list[dict]:
    dp = int(facts.get("dp", 5))
    price = float(facts["price"])
    atr = float(facts.get("atr_entry") or 0) or price * 0.002
    bias = facts["bias"]["label"]
    disc = facts["dealing_range"]["zone"] == "discount"

    prefer_buy = bias == "bullish" or (bias == "neutral" and disc)
    candidates: list[dict] = []

    # demand/supply zones
    for z in facts.get("zones", []):
        mid = (z["top"] + z["bottom"]) / 2
        if z["side"] == "demand" and mid < price:
            candidates.append(("BUY", mid, z["bottom"] - 0.3 * atr, "demand zone"))
        elif z["side"] == "supply" and mid > price:
            candidates.append(("SELL", mid, z["top"] + 0.3 * atr, "supply zone"))
    # order blocks
    for o in facts.get("order_blocks", []):
        mid = (o["top"] + o["bottom"]) / 2
        if o["side"] == "bull" and mid < price:
            candidates.append(("BUY", mid, o["bottom"] - 0.3 * atr, "bullish OB"))
        elif o["side"] == "bear" and mid > price:
            candidates.append(("SELL", mid, o["top"] + 0.3 * atr, "bearish OB"))
    # unswept pools (fade/continuation)
    for p in facts.get("pools", []):
        if p.get("swept"):
            continue
        if p["side"] == "ssl" and p["price"] < price:
            candidates.append(("BUY", p["price"], p["price"] - 0.4 * atr, f"{p.get('label','SSL')} reclaim"))
        elif p["side"] == "bsl" and p["price"] > price:
            candidates.append(("SELL", p["price"], p["price"] + 0.4 * atr, f"{p.get('label','BSL')} reject"))

    # order by alignment then distance to price
    def _key(c):
        side = c[0]
        aligned = (side == "BUY") == prefer_buy
        return (0 if aligned else 1, abs(c[1] - price))
    candidates.sort(key=_key)

    out: list[dict] = []
    seen: set = set()
    for side, entry, sl, tag in candidates:
        key = (side, round(entry, dp))
        if key in seen:
            continue
        seen.add(key)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tps = [round(entry + risk * r if side == "BUY" else entry - risk * r, dp) for r in rr]
        out.append({
            "side": side, "entry": round(entry, dp), "sl": round(sl, dp),
            "tp1": tps[0], "tp2": tps[1] if len(tps) > 1 else tps[0],
            "rr": rr, "type": tag,
            "reasons": [tag, f"{facts['bias']['label']} bias",
                        facts["dealing_range"]["zone"]],
            "win_prob": 52 if ((side == "BUY") == prefer_buy) else 44,
        })
        if len(out) >= n:
            break
    return out


def _fallback_narrative(facts: dict) -> str:
    b = facts["bias"]
    dr = facts["dealing_range"]
    return (f"{facts['name']} {b['label']} bias ({', '.join(b['notes']) or 'mixed'}); "
            f"price in {dr['zone']} of range {dr['low']}–{dr['high']} "
            f"(eq {dr['equilibrium']}). Structure-derived setups (LLM offline).")
