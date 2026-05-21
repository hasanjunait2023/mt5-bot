"""Pre-session brief generator.

Builds a markdown/text report from the current alpha desk state — currency
strength, top high-conviction setups, reversal-risk warnings, avoid list.

Used by the AlphaDeskEngine in two ways:
  1. Scheduled cron-style emit ~30 min before each major session.
  2. Manual fetch via /api/desk/brief — user can request anytime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .sessions import SESSIONS, SessionName, session_label

MAX_SETUPS    = 5
MAX_WARNINGS  = 5
MAX_AVOID     = 4


def _strength_top(strength: dict, k: int = 3) -> list[tuple[str, float]]:
    return sorted(strength.items(), key=lambda x: x[1], reverse=True)[:k]


def _strength_bot(strength: dict, k: int = 3) -> list[tuple[str, float]]:
    return sorted(strength.items(), key=lambda x: x[1])[:k]


def generate_session_brief(*,
                           session: SessionName,
                           snapshots: dict,
                           strength: dict,
                           zones_tracker,
                           liquidity_tracker,
                           orderflow_detector,
                           pending_setups: Optional[list[dict]] = None) -> str:
    """`snapshots` = SignalEngine per-tick snapshot map, `pending_setups`
    is a pre-built list of {symbol, side, score, reasons, refs} that the
    engine has aggregated."""
    label = session_label(session) if session in SESSIONS else "Off-session"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    top_str = _strength_top(strength, 3)
    bot_str = _strength_bot(strength, 3)

    # build theme line
    theme_bits: list[str] = []
    for ccy, s in top_str:
        if s >= 7.0:    theme_bits.append(f"{ccy} strong ({s:.1f})")
    for ccy, s in bot_str:
        if s <= 3.0:    theme_bits.append(f"{ccy} weak ({s:.1f})")
    theme = " · ".join(theme_bits) or "no dominant theme — mixed flows"

    lines: list[str] = []
    lines.append(f"📰 *{label.upper()} BRIEF*  ·  `{now}`")
    lines.append("")
    lines.append(f"*📊 Currency Strength:* {theme}")
    lines.append("")

    # ── high-conviction setups ──────────────────────────────────────────
    setups = sorted(pending_setups or [], key=lambda s: s["score"], reverse=True)[:MAX_SETUPS]
    if setups:
        lines.append("*🎯 HIGH-CONVICTION SETUPS*")
        for i, s in enumerate(setups, 1):
            sym  = s["symbol"]
            side = s["side"]
            arrow = "🟢" if side == "BUY" else "🔴"
            lines.append(f"")
            lines.append(f"*{i}. `{sym}`  ·  {arrow} {side}  ·  Conf *{s['score']:.0f}/100*  ·  {s.get('tier','')}*")
            for r in (s.get("reasons") or [])[:4]:
                lines.append(f"   {r}")
            if "plan" in s:
                lines.append(f"   📍 *Plan:* {s['plan']}")
    else:
        lines.append("_No high-conviction setups right now — waiting for confluence._")

    # ── reversal-risk warnings ───────────────────────────────────────────
    warnings: list[str] = []
    for sym, snap in snapshots.items():
        zones = zones_tracker.zones_for(sym)
        last_h1 = snap["tfs"]["H1"].iloc[-1]
        price   = float(last_h1["close"])
        for z in zones:
            if z.contains(price) and z.test_count >= 2:
                warnings.append(
                    f"⚠️ `{sym}` at *{z.side.upper()}* zone {z.timeframe} (tested {z.test_count}× — trend tiring)"
                )
                break
    warnings = warnings[:MAX_WARNINGS]
    if warnings:
        lines.append("")
        lines.append("*⚠️ REVERSAL RISK*")
        for w in warnings:
            lines.append(w)

    # ── avoid list ──────────────────────────────────────────────────────
    avoid: list[str] = []
    for sym, snap in snapshots.items():
        if snap["align"] == "none":
            avoid.append(sym)
    avoid = avoid[:MAX_AVOID]
    if avoid:
        lines.append("")
        lines.append("*❌ AVOID (ranging / no clean setup):*  " +
                     " · ".join(f"`{s}`" for s in avoid))

    lines.append("")
    lines.append(f"_Next brief: ~ session open. Track live signals in 💎 ALPHA topics._")
    return "\n".join(lines)
