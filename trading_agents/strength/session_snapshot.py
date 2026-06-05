"""Per-session currency-strength snapshot — cron-driven, 3x/day.

The user follows an external scanner that posts the 8-currency -7..+7 strength
once per session. This captures the same: a cron job runs this at each session's
time (BD) and stores that session's strength number + pair suggestions.

    Asian   07:00 BD = 01:00 UTC
    London  11:00 BD = 05:00 UTC
    NewYork 18:00 BD = 12:00 UTC

Snapshot = current 8-major net-pair-win strength over the trailing window of H1
bars (recent momentum into the session), labelled by session. Stored in
logs/strength/_session_snapshots.json (latest per session, read by the
dashboard) and appended to logs/strength/_session_history.jsonl (time-series).

Run:
    python -m trading_agents.strength.session_snapshot --session asian
    python -m trading_agents.strength.session_snapshot --session london
    python -m trading_agents.strength.session_snapshot --session newyork
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.strength.strength import (   # noqa: E402
    PAIRS28, MAJORS, currency_strength, tier, suggestions,
)
from trading_agents.strength import producer    # noqa: E402

BD_TZ = timezone(timedelta(hours=6))
WINDOW_H1 = 6          # trailing H1 bars (~6h) into the session
VALID_SESSIONS = ("asian", "london", "newyork")

LOG_DIR = BASE_DIR / "logs" / "strength"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SNAP_PATH = LOG_DIR / "_session_snapshots.json"
HIST_PATH = LOG_DIR / "_session_history.jsonl"


def _read_snaps() -> dict:
    try:
        if SNAP_PATH.exists():
            return json.loads(SNAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"updated_at": None, "sessions": {}}


def snapshot(session: str) -> dict:
    from mt5_bridge import bridge_client as mt5
    if not mt5.initialize():
        raise RuntimeError(f"bridge not reachable: {mt5.last_error()}")

    pair_bars = producer.fetch_pair_bars(mt5, tf="H1", count=WINDOW_H1 + 4)
    score = currency_strength(pair_bars, window_bars=WINDOW_H1)
    tiers = {c: tier(s) for c, s in score.items()}
    sugg = suggestions(score)
    now = datetime.now(timezone.utc)
    return {
        "session": session,
        "score": score,
        "tiers": tiers,
        "suggestions": sugg,
        "top": sugg[0] if sugg else None,
        "pairs_loaded": len(pair_bars),
        "captured_at": now.isoformat(timespec="seconds"),
        "captured_bd": now.astimezone(BD_TZ).strftime("%Y-%m-%d %H:%M BD"),
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True, choices=VALID_SESSIONS)
    args = ap.parse_args()

    snap = snapshot(args.session)

    snaps = _read_snaps()
    snaps.setdefault("sessions", {})[args.session] = snap
    snaps["updated_at"] = snap["captured_at"]
    SNAP_PATH.write_text(json.dumps(snaps, indent=2), encoding="utf-8")

    with HIST_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "session": args.session,
            "captured_at": snap["captured_at"],
            "captured_bd": snap["captured_bd"],
            "score": snap["score"],
        }) + "\n")

    strong = [c for c, t in snap["tiers"].items() if t in ("STRONG", "WEAK")]
    print(f"[{args.session}] {snap['captured_bd']} | pairs={snap['pairs_loaded']} | "
          f"extremes={strong} | top={snap['top']}")


if __name__ == "__main__":
    main()
