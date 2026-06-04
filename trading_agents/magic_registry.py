"""
magic_registry.py — Canonical MT5 magic-number → agent map. Single source of truth.

Replaces the three divergent maps that existed before (TRACKED_MAGICS and EA_MAGICS
in mtf_live_trader.py, plus per-agent MAGIC constants). Import from here everywhere.

IMPORTANT: a magic identifies the AGENT, not the strategy. Scalp's GS11/GS07/GS01/GS12
all share magic 20260522 — so per-strategy attribution must come from the trade
journal record's `strategies[]` (set at open), never re-derived from magic. This map
only answers "is this one of ours, and which agent placed it."
"""
from __future__ import annotations

# Python trading agents (route through the bridge_client HTTP shim).
AGENT_MAGICS: dict[int, str] = {
    20260100: "mtf_live",   # MTF EMA scalper
    20260600: "jtcc",       # JTCC ICT/SMC
    20260700: "iconic",     # Iconic / Urban Forex (RESERVED — a one-off NGS/NextGenSync
                            # Grid live-test reused this magic 2026-05-20/21 then was
                            # deleted; do NOT reuse 20260700 for anything but iconic)
    20260522: "scalp",      # Gold Scalp (GS11/GS07/GS01/GS12 — all share this magic)
    20260603: "gsvp",       # GS-VP adaptive volume-profile scalp
    20260800: "asia_fade",  # Asia Desk — Asian Range Fade (S1)
    20261300: "confluence", # Confluence Desk — S13 5-Way Confluence (XAUUSD H1)
    20261900: "confluence", # Confluence Desk — S19 Confluence Pullback (EURUSD M15)
}

# MT5 Expert Advisors (compiled .mq5, separate from the python agents).
EA_MAGICS: dict[int, str] = {
    20260516: "ScalpMaster_HFT",
    20260517: "ScalpMaster_HFT_Aggressive",
    20260002: "XAUUSD_Gold_Scalper",
    20260001: "BTCUSD_Scalper",
}

# Legacy magics seen in old TRACKED_MAGICS whose owner is unconfirmed. Treated as
# "ours" (so backfill keeps them) but attributed as unknown until reclaimed.
LEGACY_MAGICS: dict[int, str] = {
    20260500: "legacy_20260500",
    20260200: "legacy_20260200",
}

OUR_MAGICS: dict[int, str] = {**AGENT_MAGICS, **EA_MAGICS, **LEGACY_MAGICS}


def agent_for_magic(magic: int) -> str | None:
    """Agent/EA name for a magic, or None if it's not one of ours (manual trade, other EA)."""
    try:
        return OUR_MAGICS.get(int(magic))
    except (TypeError, ValueError):
        return None


def is_ours(magic: int) -> bool:
    try:
        return int(magic) in OUR_MAGICS
    except (TypeError, ValueError):
        return False
