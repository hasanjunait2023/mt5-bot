"""
Strategy Lab API — the champion/challenger leaderboard for the /lab page.

`GET /api/strategy-lab/leaderboard` reconstructs the autonomous strategy-discovery
funnel from the Strategy Factory's state files (no bridge needed):
  • _hunter_state.json → Source Hunter runs + each opened job's source/score
  • _index.json        → every Factory job (stage/status/verdict/strategy_id/title)
  • <job_id>.json      → per-job metrics (backtest + soak) for soaking/graduated jobs
  • _soak_state.json   → live demo PF/WR/trades/days per strategy on demo

Funnel: discovered → building → backtested → demo soak → live-ready (+ rejected).
The leaderboard ranks every strategy currently demo-trading (or graduated) by its
live soak profit factor — the champion is the top demo performer; challengers chase.
"""

import json
import time
import threading
from pathlib import Path

from fastapi import APIRouter

from core.config import BASE_DIR

router = APIRouter()

FACTORY_DIR = BASE_DIR / "logs" / "factory"
INDEX_PATH = FACTORY_DIR / "_index.json"
HUNTER_STATE = FACTORY_DIR / "_hunter_state.json"
SOAK_STATE = FACTORY_DIR / "_soak_state.json"

# Stage → funnel bucket.
_BUCKET = {
    "INGEST": "discovered", "CLASSIFY": "discovered", "RESEARCH_NB": "discovered",
    "RESEARCH_VIDEO": "discovered", "MERGE_SPEC": "discovered", "BUILD_PLAN": "discovered",
    "GATE_PLAN": "discovered",
    "CODEGEN": "building",
    "BACKTEST": "backtested", "GATE_BACKTEST": "backtested", "OPTIMIZE": "backtested",
    "DEMO_DEPLOY": "soak", "SOAK": "soak",
    "GATE_LIVE": "live_ready",
    "DONE": "live_ready",
    "REJECTED": "rejected", "FAILED": "rejected",
}
# Jobs whose live demo metrics belong on the leaderboard.
_LEADERBOARD_STAGES = {"DEMO_DEPLOY", "SOAK", "GATE_LIVE", "DONE"}

_CACHE_TTL_S = 4.0
_lock = threading.Lock()
_cache: dict = {}


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _num(v, d=0.0):
    try:
        return round(float(v), 2)
    except Exception:
        return d


def _build() -> dict:
    index = _read_json(INDEX_PATH) or {}
    hunter = _read_json(HUNTER_STATE) or {}
    soak = (_read_json(SOAK_STATE) or {}).get("strategies", {})

    # job_id → {score, kind, verdict} from the hunter's opened-jobs ledger.
    opened = {r.get("job_id"): r for r in hunter.get("created_jobs", []) if r.get("job_id")}

    funnel = {"discovered": 0, "building": 0, "backtested": 0, "soak": 0,
              "live_ready": 0, "rejected": 0}
    pipeline = []
    leaderboard = []

    for job_id, j in index.items():
        stage = j.get("stage", "")
        status = j.get("status", "")
        bucket = _BUCKET.get(stage, "discovered")
        funnel[bucket] = funnel.get(bucket, 0) + 1

        meta = opened.get(job_id, {})
        sid = j.get("strategy_id")
        row = {
            "job_id": job_id,
            "title": (j.get("title") or "Untitled")[:90],
            "strategy_id": sid,
            "stage": stage,
            "status": status,
            "bucket": bucket,
            "source": meta.get("kind", "youtube" if j.get("youtube_url") else "—"),
            "score": meta.get("score"),
            "verdict": j.get("verdict") or "",
            "created_at": j.get("created_at"),
        }

        # Pull live + backtest metrics for soaking / graduated strategies.
        soak_m = soak.get(sid) if sid else None
        if stage in _LEADERBOARD_STAGES and (soak_m or stage in ("GATE_LIVE", "DONE")):
            full = _read_json(FACTORY_DIR / f"{job_id}.json") or {}
            m = full.get("metrics", {})
            bt = m.get("backtest", {})
            sk = soak_m or m.get("soak", {})
            ready = stage == "DONE"
            entry = {
                **row,
                "soak_pf": _num(sk.get("pf")),
                "soak_wr": _num(sk.get("win_rate")),
                "soak_trades": int(sk.get("trades", 0) or 0),
                "soak_days": _num(sk.get("days")),
                "soak_open": int(sk.get("open", 0) or 0),
                "bt_pf": _num(bt.get("profit_factor")),
                "bt_wr": _num(bt.get("win_rate_pct")),
                "bt_verdict": bt.get("verdict", ""),
                "graduated": ready,
            }
            leaderboard.append(entry)
            row["soak_pf"] = entry["soak_pf"]

        pipeline.append(row)

    # Rank: graduated first, then by live soak PF, then trades.
    leaderboard.sort(key=lambda e: (e["graduated"], e["soak_pf"], e["soak_trades"]), reverse=True)
    pipeline.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    return {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hunter": {
            "runs": hunter.get("runs", 0),
            "last": hunter.get("last_scorecard", {}),
            "opened_total": len(opened),
        },
        "funnel": funnel,
        "total_jobs": len(index),
        "leaderboard": leaderboard,
        "pipeline": pipeline[:200],
    }


@router.get("/strategy-lab/leaderboard")
def leaderboard():
    now = time.time()
    with _lock:
        cached = _cache.get("data")
        if cached and now - _cache.get("ts", 0) < _CACHE_TTL_S:
            return cached
    data = _build()
    with _lock:
        _cache["data"] = data
        _cache["ts"] = now
    return data
