import re
import json
from pathlib import Path
from fastapi import APIRouter
from core.state_manager import poller
from core.config import BASE_DIR, EA_PERF_PATH, ICT_WF_PATH

router = APIRouter()

EA_DIR = BASE_DIR / "mql5_experts" / "scalpmaster"

EA_META = {
    "MTF_EMA_Scalper_M1.mq5": {
        "name":        "MTF EMA Scalper M1",
        "magic":       20260100,
        "symbols":     "All 28 FX pairs + XAUUSD + BTCUSD",
        "timeframe":   "M1 (+ M3 + M15 alignment)",
        "strategy":    "Multi-timeframe EMA 200/9/15 crossover with session filters",
        "sessions":    "London 08–12 UTC + NY 13–17 UTC",
        "risk_pct":    2.0,
        "rr_ratio":    2.0,
        "daily_dd":    4.5,
        "max_dd":      30.0,
        "ea_key":      "MTF_EMA_Scalper",
    },
    "ScalpMaster_HFT.mq5": {
        "name":        "ScalpMaster HFT",
        "magic":       20260516,
        "symbols":     "EURUSD, XAUUSD, BTCUSD",
        "timeframe":   "M1",
        "strategy":    "Score-based momentum scalper (EMA + RSI + ATR + BB + MACD)",
        "sessions":    "London + NY optimised",
        "risk_pct":    3.0,
        "rr_ratio":    2.5,
        "daily_dd":    None,
        "max_dd":      25.0,
        "ea_key":      "ScalpMaster_HFT",
    },
    "ScalpMaster_HFT_Aggressive.mq5": {
        "name":        "ScalpMaster HFT Aggressive",
        "magic":       20260517,
        "symbols":     "EURUSD, XAUUSD, BTCUSD",
        "timeframe":   "M1",
        "strategy":    "Aggressive variant of ScalpMaster HFT — higher risk, tighter filters",
        "sessions":    "All sessions",
        "risk_pct":    None,
        "rr_ratio":    None,
        "daily_dd":    None,
        "max_dd":      None,
        "ea_key":      "ScalpMaster_HFT_Aggressive",
    },
    "XAUUSD_ScalpMaster_Gold_M1.mq5": {
        "name":        "XAUUSD Gold Scalper M1",
        "magic":       20260002,
        "symbols":     "XAUUSD",
        "timeframe":   "M1",
        "strategy":    "Gold-tuned M1 scalper — 58–61% WR, PF 2.21–2.67, RR 1:2",
        "sessions":    "08:00–12:00 UTC + 19:00–23:00 UTC",
        "risk_pct":    2.0,
        "rr_ratio":    2.0,
        "daily_dd":    4.5,
        "max_dd":      30.0,
        "ea_key":      "XAUUSD_Gold_Scalper",
    },
    "BTCUSD_ScalpMaster_M1.mq5": {
        "name":        "BTCUSD Scalper M1",
        "magic":       20260001,
        "symbols":     "BTCUSD",
        "timeframe":   "M1",
        "strategy":    "BTC-specific M1 momentum scalper",
        "sessions":    "London + NY",
        "risk_pct":    None,
        "rr_ratio":    None,
        "daily_dd":    None,
        "max_dd":      None,
        "ea_key":      "BTCUSD_Scalper",
    },
}

_PARAM_RE = re.compile(
    r'input\s+\w+\s+\w+\s+(\w+)\s*=\s*([^;/\n]+?)\s*(?:;|//)',
    re.MULTILINE,
)


def _read_params(filename: str) -> dict:
    path = EA_DIR / filename
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        params = {}
        for m in _PARAM_RE.finditer(text):
            name, val = m.group(1).strip(), m.group(2).strip()
            try:
                params[name] = float(val) if "." in val else int(val)
            except ValueError:
                params[name] = val.strip('"')
        return params
    except Exception:
        return {}


@router.get("/eas")
def get_eas():
    state      = poller.get_snapshot()
    ea_pos_map = state.get("ea_positions", {})

    eas = []
    for filename, meta in EA_META.items():
        params    = _read_params(filename)
        ea_key    = meta["ea_key"]
        positions = ea_pos_map.get(ea_key, [])
        total_pnl = sum(p["profit"] for p in positions)
        eas.append({
            **meta,
            "filename":      filename,
            "file_exists":   (EA_DIR / filename).exists(),
            "live_positions": positions,
            "position_count": len(positions),
            "total_pnl":     round(total_pnl, 2),
            "is_active":     len(positions) > 0,
            "parameters":    params,
        })

    total_all_pnl = sum(e["total_pnl"] for e in eas)
    total_all_pos = sum(e["position_count"] for e in eas)

    return {
        "eas": eas,
        "summary": {
            "total_eas":       len(eas),
            "active_eas":      sum(1 for e in eas if e["is_active"]),
            "total_positions": total_all_pos,
            "total_pnl":       round(total_all_pnl, 2),
        },
    }


@router.get("/ea-performance")
def get_ea_performance():
    """Realized per-EA performance from closed MT5 history (spread/commission
    included — the REAL numbers, unlike the backtest). Produced by
    ea_performance_report.py which writes mt5_bridge/_ea_performance.json.
    """
    if not EA_PERF_PATH.exists():
        return {
            "available": False,
            "message": "No performance report yet. Run: python "
                       "ea_performance_report.py (writes _ea_performance.json).",
            "eas": [], "summary": {}, "account": {},
        }
    try:
        rep = json.loads(EA_PERF_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"available": False, "message": f"Report parse error: {exc}",
                "eas": [], "summary": {}, "account": {}}
    rep["available"] = "error" not in rep
    return rep


@router.get("/ict/results")
def get_ict_results():
    """ICT 2022 Mentorship Model — walk-forward validation results.
    Generated by: python backtest_runner.py --ict-wf
    Saved to: backtest_reports/ict_wf_results.json
    """
    if not ICT_WF_PATH.exists():
        return {
            "available": False,
            "message": "No ICT walk-forward results yet. "
                       "Run: python backtest_runner.py --ict-wf",
            "symbols": {}, "promoted": [],
        }
    try:
        data = json.loads(ICT_WF_PATH.read_text(encoding="utf-8"))
        data["available"] = True
        return data
    except Exception as exc:
        return {"available": False, "message": f"Parse error: {exc}",
                "symbols": {}, "promoted": []}
