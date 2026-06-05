"""Strength producer — fetches 28-pair H1 bars and writes the session state JSON.

This is the single computation path: the M3 agent calls :func:`build_state` once
per loop and BOTH uses the returned dict in-process AND writes it via
:func:`write_state`, which the dashboard reads. No second strength calculation
exists, so the page and the agent can never drift.

Run standalone for a one-shot snapshot:
    python -m trading_agents.strength.producer
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.strength.strength import (   # noqa: E402
    PAIRS28, MAJORS, compute_sessions, trade_of_the_day,
)

LOG_DIR = BASE_DIR / "logs" / "strength"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = LOG_DIR / "_strength_state.json"


def fetch_pair_bars(mt5, tf: str = "H1", count: int = 120) -> dict:
    """{symbol: {time,high,low,close}} for all 28 pairs via the MT5 bridge."""
    tf_const = getattr(mt5, f"TIMEFRAME_{tf}", tf)
    out: dict = {}
    for sym in PAIRS28:
        try:
            rates = mt5.copy_rates_from_pos(sym, tf_const, 0, count)
        except Exception:
            rates = None
        if rates is None or len(rates) < 2:
            continue
        out[sym] = {
            "time":  [int(r["time"])    for r in rates],
            "high":  [float(r["high"])  for r in rates],
            "low":   [float(r["low"])   for r in rates],
            "close": [float(r["close"]) for r in rates],
        }
    return out


def build_state(mt5, now_unix: Optional[int] = None, tf: str = "H1") -> dict:
    """Compute the full 3-session strength payload from live bars."""
    now = int(now_unix if now_unix is not None else time.time())
    pair_bars = fetch_pair_bars(mt5, tf=tf)
    sessions = compute_sessions(pair_bars, now)
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tf": tf,
        "pairs_loaded": len(pair_bars),
        "majors": list(MAJORS),
        "sessions": sessions,
        "trade_of_the_day": trade_of_the_day(sessions),
    }


def write_state(state: dict, path: Path = STATE_PATH) -> None:
    try:
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from mt5_bridge import bridge_client as mt5
    if not mt5.initialize():
        print("MT5 bridge not reachable:", mt5.last_error())
        sys.exit(1)
    state = build_state(mt5)
    write_state(state)
    print(f"Wrote {STATE_PATH} | pairs_loaded={state['pairs_loaded']}")
    for name, s in state["sessions"].items():
        strong = [c for c, t in s["tiers"].items() if t in ("STRONG", "WEAK")]
        print(f"  {name:10s} sugg={len(s['suggestions']):2d} extremes={strong}")
    print("  trade_of_the_day:", state["trade_of_the_day"])


if __name__ == "__main__":
    main()
