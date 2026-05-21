"""JTCC Daily Digest — generates and sends daily performance summary at 00:30 BD time.

Run as cron or persistent loop:
  python -m trading_agents.jtcc.digest --once
  python -m trading_agents.jtcc.digest --loop
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent.parent.parent
TRADES_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_trades.jsonl"
PERF_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_performance.json"
STATE_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_state.json"
LATENCY_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_latency.json"
DIGEST_FILE = BASE_DIR / "logs" / "jtcc" / "_jtcc_digest.json"

BD_TZ = ZoneInfo("Asia/Dhaka")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("jtcc.digest")


def _read_trades_today() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    now = datetime.now(tz=BD_TZ)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    trades = []
    try:
        for line in TRADES_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry.get("ts", ""))
                if ts >= start_of_day:
                    trades.append(entry)
            except Exception:
                continue
    except Exception as e:
        log.error("Read trades failed: %s", e)
    return trades


def _read_json(path: Path, default: dict | None = None) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default or {}


def build_digest() -> dict:
    now = datetime.now(tz=BD_TZ)
    trades = _read_trades_today()
    perf = _read_json(PERF_FILE)
    state = _read_json(STATE_FILE)
    latency = _read_json(LATENCY_FILE).get("stats", {})

    # Categorize today's events
    signals_today = [t for t in trades if t.get("type") == "signal"]
    opens_today = [t for t in trades if t.get("type") == "trade_open"]
    closes_today = [t for t in trades if t.get("type") == "trade_close"]

    # Today's P&L
    today_pnl = sum(c.get("pnl", 0) for c in closes_today)
    today_wins = sum(1 for c in closes_today if c.get("pnl", 0) > 0)
    today_losses = sum(1 for c in closes_today if c.get("pnl", 0) < 0)
    today_wr = round(today_wins / len(closes_today) * 100, 1) if closes_today else 0.0

    # Strategy participation today
    fired_strategies = Counter()
    for sig in signals_today:
        for s in sig.get("strategies_agreed", []):
            fired_strategies[s] += 1

    strategy_pnl_today = defaultdict(float)
    for close in closes_today:
        strat = close.get("strategy", "unknown")
        strategy_pnl_today[strat] += close.get("pnl", 0)

    # Per-symbol breakdown
    by_symbol: dict = defaultdict(lambda: {"signals": 0, "closes": 0, "pnl": 0.0})
    for sig in signals_today:
        by_symbol[sig.get("symbol", "?")]["signals"] += 1
    for close in closes_today:
        sym = close.get("symbol", "?")
        by_symbol[sym]["closes"] += 1
        by_symbol[sym]["pnl"] += close.get("pnl", 0)

    # API efficiency
    api_calls = state.get("daily_api_calls", 0)
    signal_per_call = round(len(signals_today) / api_calls, 2) if api_calls > 0 else 0

    # Latency summary
    latency_summary = {}
    for label in ("l1_full", "l2_strategy_eval", "l3_master", "fmp_fetch"):
        s = latency.get(label, {})
        if s:
            latency_summary[label] = {"p95_ms": s.get("p95_ms", 0), "error_rate": s.get("error_rate_pct", 0)}

    digest = {
        "generated_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "today": {
            "signals_fired": len(signals_today),
            "trades_opened": len(opens_today),
            "trades_closed": len(closes_today),
            "pnl": round(today_pnl, 2),
            "wins": today_wins,
            "losses": today_losses,
            "win_rate_pct": today_wr,
            "api_calls": api_calls,
            "api_calls_remaining": max(0, 15 - api_calls),
            "signal_per_api_call": signal_per_call,
        },
        "by_strategy_fires": dict(fired_strategies.most_common(10)),
        "by_strategy_pnl": dict(sorted(strategy_pnl_today.items(), key=lambda x: -x[1])),
        "by_symbol": {k: dict(v) for k, v in by_symbol.items()},
        "lifetime": {
            "total_trades": perf.get("total_trades", 0),
            "total_pnl": perf.get("total_pnl", 0.0),
            "win_rate_pct": round(perf.get("wins", 0) / max(perf.get("total_trades", 1), 1) * 100, 1),
        },
        "latency": latency_summary,
    }

    # Identify silent strategies (loaded but never fired)
    all_strategies = list(perf.get("strategy_stats", {}).keys())
    fired_lifetime = [s for s, v in perf.get("strategy_stats", {}).items() if v.get("trades", 0) > 0]
    digest["silent_strategies"] = [s for s in all_strategies if s not in fired_lifetime]

    return digest


def format_telegram(digest: dict) -> str:
    t = digest["today"]
    pnl_str = f"{t['pnl']:+.2f}" if t['pnl'] != 0 else "0.00"
    emoji = "📈" if t['pnl'] > 0 else "📉" if t['pnl'] < 0 else "➖"

    lines = [
        f"{emoji} JTCC Daily Digest — {digest['date']}",
        "",
        f"Today's P&L: {pnl_str}",
        f"Trades: {t['trades_closed']} closed ({t['wins']}W / {t['losses']}L) · WR {t['win_rate_pct']}%",
        f"Signals fired: {t['signals_fired']} | API calls: {t['api_calls']}/15 ({t['signal_per_api_call']} sig/call)",
        "",
    ]

    if digest["by_strategy_fires"]:
        lines.append("Top firing strategies:")
        for name, count in list(digest["by_strategy_fires"].items())[:5]:
            lines.append(f"  • {name}: {count}")
        lines.append("")

    if digest["by_strategy_pnl"]:
        sorted_pnl = list(digest["by_strategy_pnl"].items())
        if sorted_pnl[0][1] > 0:
            lines.append(f"Best: {sorted_pnl[0][0]} ({sorted_pnl[0][1]:+.2f})")
        if sorted_pnl[-1][1] < 0:
            lines.append(f"Worst: {sorted_pnl[-1][0]} ({sorted_pnl[-1][1]:+.2f})")
        lines.append("")

    if digest["silent_strategies"]:
        lines.append(f"Silent strategies ({len(digest['silent_strategies'])}): may need tuning")

    lines.append("")
    lines.append(f"Lifetime: {digest['lifetime']['total_trades']} trades · "
                 f"{digest['lifetime']['win_rate_pct']}% WR · "
                 f"{digest['lifetime']['total_pnl']:+.2f}")

    return "\n".join(lines)


def send_digest(digest: dict) -> None:
    try:
        DIGEST_FILE.write_text(json.dumps(digest, indent=2), encoding="utf-8")
    except Exception:
        pass

    msg = format_telegram(digest)
    log.info("Digest:\n%s", msg)

    try:
        from trading_agents.telegram_hq import send as tg_send
        tg_send("digest", msg, level="INFO", title="JTCC Daily Digest")
    except Exception as e:
        log.error("Digest Telegram send failed: %s", e)


def _seconds_until_next_run(target_h: int = 0, target_m: int = 30) -> float:
    now = datetime.now(tz=BD_TZ)
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    parser = argparse.ArgumentParser(description="JTCC Daily Digest")
    parser.add_argument("--once", action="store_true", help="Generate and send once, exit")
    parser.add_argument("--loop", action="store_true", help="Run every day at 00:30 BD time")
    args = parser.parse_args()

    if args.once or (not args.once and not args.loop):
        digest = build_digest()
        send_digest(digest)
        return

    log.info("JTCC Digest loop started — fires daily at 00:30 BD time")
    while True:
        wait_s = _seconds_until_next_run(0, 30)
        log.info("Next digest in %.0fs (%.1fh)", wait_s, wait_s / 3600)
        time.sleep(wait_s)
        try:
            digest = build_digest()
            send_digest(digest)
        except Exception as e:
            log.error("Digest cycle failed: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    main()
