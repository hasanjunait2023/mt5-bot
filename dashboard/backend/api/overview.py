from fastapi import APIRouter
from core.state_manager import poller
from core.log_tailer import tailer

router = APIRouter()


@router.get("/overview")
def get_overview():
    state = poller.get_snapshot()
    recent_events = tailer.get_recent(n=20)
    return {**state, "recent_events": recent_events}
