import re
from fastapi import APIRouter, Query
from core.state_manager import poller
from core.log_tailer import tailer
from core.config import LIVE_LOG_PATH

router = APIRouter()

_ORDER_RE = re.compile(
    r">> (\w+): (BUY|SELL) ([\d.]+)L @ ([\d.]+) SL=([\d.]+) TP=([\d.]+)"
)


def _parse_trades_from_log() -> list:
    if not LIVE_LOG_PATH.exists():
        return []
    try:
        text = LIVE_LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    trades = []
    for line in text.splitlines():
        m = _ORDER_RE.search(line)
        if not m:
            continue
        ts_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        ts = ts_match.group(1) if ts_match else ""
        trades.append({
            "symbol": m.group(1),
            "direction": m.group(2),
            "volume": float(m.group(3)),
            "entry_price": float(m.group(4)),
            "sl": float(m.group(5)),
            "tp": float(m.group(6)),
            "open_time": ts,
            "status": "logged",
        })
    return trades


@router.get("/history")
def get_history(
    symbol: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
):
    trades = _parse_trades_from_log()

    if symbol:
        trades = [t for t in trades if t["symbol"].upper() == symbol.upper()]

    total = len(trades)
    trades = trades[-(page * per_page):][:per_page]

    wins = sum(1 for t in trades if t.get("direction") == "BUY")
    win_rate = round(wins / total * 100, 1) if total else 0.0

    return {
        "trades": trades,
        "total": total,
        "page": page,
        "per_page": per_page,
        "win_rate": win_rate,
    }
