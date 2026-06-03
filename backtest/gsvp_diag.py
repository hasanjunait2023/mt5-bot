"""GS-VP diagnostic — per-playbook + per-symbol breakdown.

Replicates backtest_one's fill/exit logic but tags each trade by the `_pb`
(playbook A=reversion / B=breakout) the signal carried, so we can see which
leg of the strategy makes or loses money per symbol. One-off tuning aid.

Run:  python -m backtest.gsvp_diag --bars 20000
      python -m backtest.gsvp_diag --bars 20000 --symbols BTCUSD XAUUSD
      python -m backtest.gsvp_diag --bars 20000 --half      # in/out-of-sample
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_agents.scalp.backtest import (
    _gsvp_adaptive, _fetch_bars, TYPICAL_SPREADS, STRATEGY_SYMBOLS,
)

_CACHE = Path(__file__).resolve().parent / "_cache"


def _load(symbol: str, bars: int) -> dict | None:
    """Prefer the local cache (offline, bridge-independent); fall back to fetch."""
    f = _CACHE / f"{symbol}_M15.json"
    if f.exists():
        d = json.loads(f.read_text())
        if bars and len(d.get("close", [])) > bars:
            d = {k: (v[-bars:] if isinstance(v, list) else v) for k, v in d.items()}
        return d
    return _fetch_bars(symbol, "M15", bars)


def _run(symbol: str, bars: dict, lo: int, hi: int) -> list[dict]:
    times = bars["time"]
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    spread = TYPICAL_SPREADS.get(symbol, 0.0001)
    trades, position = [], None
    for i in range(max(60, lo), min(hi, len(times) - 1)):
        if position is not None:
            nh, nl = highs[i + 1], lows[i + 1]
            if position["side"] == "BUY":
                if nl <= position["sl"]:
                    trades.append({**position, "pnl": position["sl"] - position["entry"] - spread, "exit": "SL"}); position = None
                elif nh >= position["tp"]:
                    trades.append({**position, "pnl": position["tp"] - position["entry"] - spread, "exit": "TP"}); position = None
            else:
                if nh >= position["sl"]:
                    trades.append({**position, "pnl": position["entry"] - position["sl"] - spread, "exit": "SL"}); position = None
                elif nl <= position["tp"]:
                    trades.append({**position, "pnl": position["entry"] - position["tp"] - spread, "exit": "TP"}); position = None
        if position is None:
            try:
                sig = _gsvp_adaptive(bars, i, spread, symbol)
            except Exception:
                continue
            if sig and sig.get("signal") in ("BUY", "SELL"):
                entry = closes[i + 1] + (spread if sig["signal"] == "BUY" else -spread)
                ok = (sig["sl"] < entry < sig["tp"]) if sig["signal"] == "BUY" else (sig["tp"] < entry < sig["sl"])
                if ok:
                    position = {"side": sig["signal"], "entry": entry, "sl": sig["sl"],
                                "tp": sig["tp"], "pb": sig.get("_pb", "?")}
    return trades


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "pnl": 0.0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    gp, gl = sum(wins), abs(sum(p for p in pnls if p < 0)) or 1e-9
    return {"n": len(pnls), "wr": round(len(wins) / len(pnls) * 100, 1),
            "pf": round(gp / gl, 2), "pnl": round(sum(pnls), 5)}


def _report(symbol: str, trades: list[dict], label: str = "") -> None:
    overall = _stats(trades)
    byp = {pb: _stats([t for t in trades if t["pb"] == pb]) for pb in ("A", "B")}
    print(f"  {symbol:<8}{label:<8} ALL n={overall['n']:>4} WR={overall['wr']:>5}% PF={overall['pf']:>5} "
          f"| A(rev) n={byp['A']['n']:>4} WR={byp['A']['wr']:>5}% PF={byp['A']['pf']:>5} "
          f"| B(brk) n={byp['B']['n']:>4} WR={byp['B']['wr']:>5}% PF={byp['B']['pf']:>5}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=20000)
    ap.add_argument("--symbols", nargs="+", default=STRATEGY_SYMBOLS["GSVP"])
    ap.add_argument("--half", action="store_true", help="split into in/out-of-sample halves")
    args = ap.parse_args()

    print(f"\nGS-VP diagnostic — {args.bars} M15 bars/symbol\n" + "=" * 110)
    for sym in args.symbols:
        bars = _load(sym, args.bars)
        if not bars or not bars.get("close"):
            print(f"  {sym}: NO BARS"); continue
        nb = len(bars["close"])
        if args.half:
            mid = nb // 2
            _report(sym, _run(sym, bars, 60, mid), "[IS]")
            _report(sym, _run(sym, bars, mid, nb), "[OOS]")
        else:
            _report(sym, _run(sym, bars, 60, nb), f"[{nb}b]")
    print("=" * 110)


if __name__ == "__main__":
    main()
