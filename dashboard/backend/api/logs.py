from fastapi import APIRouter, Query
from core.log_tailer import tailer

router = APIRouter()


@router.get("/logs")
def get_logs(
    n:     int = Query(default=200, ge=1, le=1000),
    level: str = Query(default=None),
):
    lines = tailer.get_recent(n=n, level=level)
    return {"lines": lines, "count": len(lines)}
