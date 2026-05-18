import time
from fastapi import APIRouter
from core.state_manager import poller

router = APIRouter()


@router.get("/positions")
def get_positions():
    state = poller.get_snapshot()
    positions = state.get("positions", [])
    now = time.time()
    for p in positions:
        open_time = p.get("open_time", now)
        p["duration_mins"] = int((now - open_time) / 60)
        entry = p.get("entry_price", 0)
        current = p.get("current_price", entry)
        sl = p.get("sl", 0)
        tp = p.get("tp", 0)
        if p.get("direction") == "BUY":
            p["pips_to_sl"] = round(current - sl, 5) if sl else 0
            p["pips_to_tp"] = round(tp - current, 5) if tp else 0
        else:
            p["pips_to_sl"] = round(sl - current, 5) if sl else 0
            p["pips_to_tp"] = round(current - tp, 5) if tp else 0
        risk = abs(entry - sl) if sl else 1
        p["unrealized_pct"] = round(p.get("profit", 0) / (state.get("account", {}).get("balance", 1) or 1) * 100, 3)
    return {"positions": positions, "count": len(positions)}
