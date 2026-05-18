import re
from pathlib import Path
from fastapi import APIRouter
from core.state_manager import poller
from core.config import BASE_DIR

router = APIRouter()

# ── parsing ────────────────────────────────────────────────────────────────────
_METRIC_MAP = {
    "Total Trades":     "total_trades",
    "Wins":             "wins",
    "Losses":           "losses",
    "Win Rate":         "win_rate_pct",
    "Profit Factor":    "profit_factor",
    "Net P&L":          "net_pnl",
    "Total Profit":     "total_profit",
    "Total Loss":       "total_loss",
    "Max Drawdown":     "max_drawdown_pct",
    "Sharpe Ratio":     "sharpe_ratio",
    "Final Balance":    "final_balance",
}
_METRIC_RE  = re.compile(r"([A-Za-z &/]+?)\s*:\s*([\d.+\-$%]+)")
_HOURLY_RE  = re.compile(r"(\d{2}):00\s+(\d+)\s+trades?\s+WR\s+([\d.]+)%")


def _parse_backtest(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        # Try utf-16 (auto BOM detection), then utf-16-le, then utf-8
        for enc in ("utf-16", "utf-16-le", "utf-8"):
            try:
                raw = path.read_text(encoding=enc, errors="replace")
                break
            except Exception:
                continue
        else:
            return None

        # Remove null bytes and collapse whitespace runs
        clean = re.sub(r"\x00", "", raw)
        clean = re.sub(r"﻿", "", clean)           # strip BOM chars
        clean = re.sub(r"[ \t]{2,}", " ", clean)
        lines = clean.splitlines()

        metrics: dict = {}
        for line in lines:
            m = _METRIC_RE.search(line)
            if not m:
                continue
            raw_key = m.group(1).strip()
            raw_val = m.group(2).strip().lstrip("$").rstrip("%")
            # map to clean key if known, else use raw
            key = _METRIC_MAP.get(raw_key, raw_key)
            try:
                metrics[key] = float(raw_val)
            except ValueError:
                metrics[key] = raw_val

        hourly: list = []
        in_hourly = False
        for line in lines:
            if "hour-by-hour" in line.lower():
                in_hourly = True
                continue
            if in_hourly:
                hm = _HOURLY_RE.search(line)
                if hm:
                    hourly.append({
                        "hour":   int(hm.group(1)),
                        "trades": int(hm.group(2)),
                        "wr":     float(hm.group(3)),
                    })

        if not metrics:
            return None
        return {"metrics": metrics, "hourly": hourly}
    except Exception:
        return None


# ── EA → backtest files mapping ───────────────────────────────────────────────
_EA_BACKTEST = [
    {
        "ea_key":   "MTF_EMA_Scalper",
        "ea_name":  "MTF EMA Scalper M1",
        "files":    {"EURUSD": BASE_DIR / "backtest_eurusd.txt",
                     "XAUUSD": BASE_DIR / "backtest_xauusd.txt"},
    },
    {
        "ea_key":   "ScalpMaster_HFT",
        "ea_name":  "ScalpMaster HFT",
        "files":    {"EURUSD": BASE_DIR / "backtest_eurusd.txt",
                     "XAUUSD": BASE_DIR / "backtest_xauusd.txt"},
    },
    {
        "ea_key":   "ScalpMaster_HFT_Aggressive",
        "ea_name":  "ScalpMaster HFT Aggressive",
        "files":    {"EURUSD": BASE_DIR / "backtest_eurusd.txt",
                     "XAUUSD": BASE_DIR / "backtest_xauusd.txt"},
    },
    {
        "ea_key":   "XAUUSD_Gold_Scalper",
        "ea_name":  "XAUUSD Gold Scalper M1",
        "files":    {"XAUUSD": BASE_DIR / "backtest_xauusd.txt"},
    },
    {
        "ea_key":   "BTCUSD_Scalper",
        "ea_name":  "BTCUSD Scalper M1",
        "files":    {},
    },
]


def _ea_backtests() -> list:
    out = []
    for ea in _EA_BACKTEST:
        symbols: dict = {}
        total_trades = 0
        wr_sum = 0.0
        pf_sum = 0.0
        count = 0
        for sym, path in ea["files"].items():
            result = _parse_backtest(path)
            if result:
                symbols[sym] = result
                m = result["metrics"]
                total_trades += int(m.get("total_trades", 0))
                wr_sum       += float(m.get("win_rate_pct", 0.0))
                pf_sum       += float(m.get("profit_factor", 0.0))
                count        += 1
        out.append({
            "ea_key":   ea["ea_key"],
            "ea_name":  ea["ea_name"],
            "symbols":  symbols,
            "summary": {
                "total_trades":  total_trades,
                "avg_win_rate":  round(wr_sum / count, 1) if count else None,
                "avg_profit_factor": round(pf_sum / count, 2) if count else None,
                "symbols_tested": list(symbols.keys()),
            },
        })
    return out


# ── endpoint ──────────────────────────────────────────────────────────────────
@router.get("/reports")
def get_reports():
    equity_history = poller.get_equity_history(n=1440)
    pl             = poller.get_perf_log()
    kb             = poller.get_knowledge_base()

    daily_perf = pl.get("daily_performance", [])

    drawdown_series = []
    peak = 0.0
    for point in equity_history:
        eq = point["equity"]
        if eq > peak:
            peak = eq
        dd = round((peak - eq) / peak * 100, 2) if peak > 0 else 0.0
        drawdown_series.append({"t": point["t"], "drawdown": dd})

    monthly_returns: dict = {}
    for rec in pl.get("monthly_performance", []):
        key = rec.get("period", rec.get("month", ""))
        monthly_returns[key] = rec.get("net_pnl_pct", rec.get("return_pct", 0.0))

    symbol_stats: dict = {}
    for sym, data in kb.get("symbols", {}).items():
        patterns = data.get("successful_patterns", [])
        if patterns:
            avg_pf = sum(p.get("performance_score", 1.0) for p in patterns) / len(patterns)
            avg_wr = sum(p.get("metrics", {}).get("win_rate_pct", 50) for p in patterns) / len(patterns)
        else:
            avg_pf, avg_wr = 0.0, 0.0
        symbol_stats[sym] = {
            "profit_factor": round(avg_pf, 2),
            "win_rate":      round(avg_wr, 1),
            "total_patterns": len(patterns),
        }

    return {
        "equity_curve":      equity_history,
        "drawdown_series":   drawdown_series,
        "daily_performance": daily_perf[-90:],
        "monthly_returns":   monthly_returns,
        "symbol_stats":      symbol_stats,
        "ea_backtests":      _ea_backtests(),
    }
