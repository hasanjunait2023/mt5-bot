"""tv_desk configuration — symbols, timeframes, RR targets, paths, schedule.

Everything here is overridable by env so the agents can be retargeted without a
code change. Defaults match the user's 7 favorites and the confirmed plan.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

# ── Instruments (TradingView tickers) ────────────────────────────────────────
# tv   : exchange:ticker fed to chart_set_symbol
# base : plain symbol fed to the Alpha Desk detectors (decimals/pip logic)
# dp   : price decimals for display / rounding
# mintick = price increment per tick (needed for the TV Long/Short Position tool,
# whose stop/profit levels are expressed in TICKS, not price).
_DEFAULT_SYMBOLS = [
    {"tv": "OANDA:XAUUSD",    "base": "XAUUSD", "name": "Gold",    "dp": 2, "mintick": 0.01},
    {"tv": "BINANCE:BTCUSDT", "base": "BTCUSD", "name": "Bitcoin", "dp": 1, "mintick": 0.01},
    {"tv": "OANDA:XAGUSD",    "base": "XAGUSD", "name": "Silver",  "dp": 3, "mintick": 0.001},
    {"tv": "TVC:USOIL",       "base": "USOIL",  "name": "Oil",     "dp": 2, "mintick": 0.01},
    {"tv": "OANDA:EURUSD",    "base": "EURUSD", "name": "Euro",    "dp": 5, "mintick": 0.00001},
    {"tv": "OANDA:GBPUSD",    "base": "GBPUSD", "name": "Pound",   "dp": 5, "mintick": 0.00001},
    {"tv": "OANDA:USDJPY",    "base": "USDJPY", "name": "Yen",     "dp": 3, "mintick": 0.001},
]


def _load_symbols() -> list[dict]:
    raw = os.getenv("TV_DESK_SYMBOLS", "").strip()
    if not raw:
        return _DEFAULT_SYMBOLS
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return _DEFAULT_SYMBOLS


SYMBOLS: list[dict] = _load_symbols()

# ── Timeframes (TradingView resolution codes) ────────────────────────────────
TF_BIAS        = "D"                      # daily — bias + PDH/PDL only
TF_INTRADAY    = ["240", "60", "15"]      # H4 / H1 / M15 — intraday structure
TF_SCALP_CTX   = "60"                     # H1 context for scalps
TF_SCALP_ENTRY = ["15", "5"]             # M15 / M5 — scalp entries

# Bars to pull per timeframe (detectors want >= ~50).
BARS = {"D": 120, "240": 180, "60": 220, "15": 220, "5": 480}

# ── Risk : reward ────────────────────────────────────────────────────────────
RR_INTRADAY = [2.0, 3.0]    # TP1 = 1:2, TP2 = 1:3
RR_SCALP    = [2.0, 3.0]    # scalp TP1 = 1:2, optional runner 1:3
RR_TOL      = 0.06          # validator tolerance on computed RR

N_INTRADAY_ENTRIES = 3
N_SCALP_ENTRIES    = 3

# ── TradingView MCP ──────────────────────────────────────────────────────────
TV_MCP_SERVER = os.getenv(
    "TV_MCP_SERVER", r"C:\Users\Junait\tradingview-mcp\src\server.js"
)
TV_NODE = os.getenv("TV_NODE", "node")
TV_SCREENSHOT_DIR = Path(
    os.getenv("TV_SCREENSHOT_DIR", r"C:\Users\Junait\tradingview-mcp\screenshots")
)
# Dedicated saved layout the agents drive so the user's working chart is untouched.
LAYOUT_NAME = os.getenv("TV_DESK_LAYOUT", "AUTOMATION")

# ── Scheduling ───────────────────────────────────────────────────────────────
# Bangladesh = UTC+6. Intraday analyst fires once/day at this BD hour.
# (Default 0 = midnight BD ≈ 18:00 UTC — the user-requested "12-1 AM BD" window;
#  set to ~2 for the true NY equity close.)
ANALYST_RUN_BD_HOUR = int(os.getenv("ANALYST_RUN_BD_HOUR", "0"))
BD_UTC_OFFSET_H = 6

# ── Paths ────────────────────────────────────────────────────────────────────
LOG_ROOT          = BASE_DIR / "logs"
INTRADAY_DIR      = LOG_ROOT / "intraday_analyst"
SCALP_DIR         = LOG_ROOT / "session_scalper"
TV_LOCK_PATH      = LOG_ROOT / "tv_desk" / ".tv.lock"

# ── Accuracy upgrades ────────────────────────────────────────────────────────
# News blackout (ForexFactory cache). Skip publishing a symbol if a HIGH-impact
# event for its currencies lands within this many minutes of run time; tag
# entries whose trade horizon contains one.
NEWS_CACHE_PATH    = BASE_DIR / "mt5_bridge" / "_ff_calendar_cache.json"
NEWS_BLACKOUT_MIN  = 45
NEWS_HORIZON_H     = {"intraday": 12, "scalp": 6}

# Stop-quality: SL must be at least this × ATR(entry-TF) from entry (anti-noise).
MIN_STOP_ATR       = 0.5
# Snap gate: reject an LLM entry not within this × ATR of a real structure level.
SNAP_TOL_ATR       = 0.75

# Confluence score → tier
TIER_A_MIN = 75
TIER_B_MIN = 55

# Symbol → currencies (news mapping). Crypto has no FF currency.
SYMBOL_CCY = {
    "XAUUSD": ["USD"], "XAGUSD": ["USD"], "USOIL": ["USD"],
    "EURUSD": ["EUR", "USD"], "GBPUSD": ["GBP", "USD"], "USDJPY": ["USD", "JPY"],
    "BTCUSD": [],
}
# Correlation groups (flag concentrated same-direction USD exposure).
CORR_GROUPS = {
    "USD_majors": ["EURUSD", "GBPUSD", "USDJPY"],
    "metals":     ["XAUUSD", "XAGUSD"],
}

# ── Telegram topics ──────────────────────────────────────────────────────────
TOPIC_INTRADAY = "analyst_daily"
TOPIC_SCALP    = {"asia": "scalp_asia", "london": "scalp_london", "ny": "scalp_ny"}
