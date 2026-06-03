"""GS-VP Live Agent — adaptive volume-profile strategy on M15.

Trades the validated GS-VP setups (GBPUSD + EURUSD robust; XAUUSD optional/cautious)
by placing REAL orders on the connected MT5 account. The current account is a DEMO
(Exness trial), so this is the proving ground: the agent runs live on demo, and only
once a symbol clears the promotion gate (>=20 closed trades, PF >= 1.3) is it flagged
"real-ready". Pointing the bridge at a real account additionally requires --allow-real,
so real money is fail-closed until both the gate passes and the operator opts in.

Modes:
  (default)      real orders on a DEMO account (server name looks like trial/demo)
  --paper        simulate only, never send an order (SL/TP filled off M15 bars)
  --allow-real   permit real orders on a NON-demo account, but ONLY for symbols whose
                 gate has passed; otherwise that symbol falls back to simulate

Usage:
  python -m trading_agents.scalp.gsvp_agent
  python -m trading_agents.scalp.gsvp_agent --symbols GBPUSD EURUSD --risk 1.0 --dd 6.0
  python -m trading_agents.scalp.gsvp_agent --paper
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

LOG_DIR = BASE_DIR / "logs" / "scalp"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "_gsvp_agent.log"
STATE_PATH = LOG_DIR / "_gsvp_agent_state.json"
CLOSED_PATH = LOG_DIR / "_gsvp_trades.jsonl"

GSVP_MAGIC = 20260603
TF = "M15"
BARS = 300
POLL_INTERVAL_S = 20
PAPER_MIN_TRADES = 20
PAPER_MIN_PF = 1.3
MAX_TRADES_PER_DAY = 6
MAX_CONCURRENT = 2
DEFAULT_SYMBOLS = ["GBPUSD", "EURUSD"]   # validated robust set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("GSVP.Agent")

from trading_agents.scalp.backtest import _gsvp_adaptive, TYPICAL_SPREADS
from trading_agents.scalp.agent import DailyState   # reuse DD/day-roll state

try:
    from trading_agents import telegram_hq as _tghq
    _TG_ON = True
except Exception:
    _tghq, _TG_ON = None, False

try:
    from trading_agents.trade_journal import open_trade as _journal_open
    _JOURNAL = True
except Exception:
    _JOURNAL = False
    def _journal_open(*a, **kw): pass   # type: ignore


def _tg(msg: str, level: str = "INFO") -> None:
    if _TG_ON and _tghq is not None:
        try:
            _tghq.send("live_trading", msg, level=level, title="GS-VP Agent")
        except Exception:
            pass


# ── Account / data ────────────────────────────────────────────────────────────
def _is_demo(acc) -> bool:
    s = (getattr(acc, "server", "") or "").lower()
    return any(k in s for k in ("trial", "demo", "test", "practice", "contest"))


def _fetch_bars(symbol: str, n: int) -> Optional[dict]:
    from mt5_bridge import bridge_client as mt5
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, n)
    if rates is None or len(rates) < 60:
        return None
    return {
        "time":   [int(r["time"]) for r in rates],
        "open":   [float(r["open"]) for r in rates],
        "high":   [float(r["high"]) for r in rates],
        "low":    [float(r["low"]) for r in rates],
        "close":  [float(r["close"]) for r in rates],
        "volume": [float(r["tick_volume"]) for r in rates],
    }


def _calc_lots(symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    from mt5_bridge import bridge_client as mt5
    acc, sym = mt5.account_info(), mt5.symbol_info(symbol)
    if acc is None or sym is None:
        return 0.0
    risk_usd = acc.equity * risk_pct / 100.0
    sl_dist = abs(entry - stop)
    if sl_dist < sym.point or sym.trade_tick_size <= 0:
        return 0.0
    value_lot = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0:
        return 0.0
    lots = risk_usd / value_lot
    lots = round(lots / sym.volume_step) * sym.volume_step
    cap = (acc.equity * 0.02) / value_lot if value_lot > 0 else sym.volume_max
    return round(max(sym.volume_min, min(lots, sym.volume_max, cap)), 2)


def _our_positions() -> tuple:
    from mt5_bridge import bridge_client as mt5
    pos = mt5.positions_get(magic=GSVP_MAGIC)
    return tuple(p for p in (pos or ()) if p.magic == GSVP_MAGIC)


def _place_order(symbol: str, side: str, stop: float, tp: float,
                 risk_pct: float) -> Optional[tuple[int, float, float]]:
    from mt5_bridge import bridge_client as mt5
    tick, sym = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    live_entry = tick.ask if side == "BUY" else tick.bid
    if abs(live_entry - stop) < sym.point * 5:
        log.warning("%s: SL too tight, skip", symbol)
        return None
    lots = _calc_lots(symbol, live_entry, stop, risk_pct)
    if lots <= 0:
        log.warning("%s: lot=0, skip", symbol)
        return None
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
        "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
        "sl": round(stop, sym.digits), "tp": round(tp, sym.digits),
        "deviation": 15, "magic": GSVP_MAGIC, "comment": "GSVP",
    }
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER %s %s @ %.5f SL=%.5f TP=%.5f lots=%.2f",
                 side, symbol, live_entry, stop, tp, lots)
        _tg(f"GS-VP {side} {symbol} @ {live_entry:.5f} SL={stop:.5f} TP={tp:.5f} lots={lots}")
        return int(res.order), lots, live_entry
    log.error("%s: order FAILED retcode=%s", symbol, res.retcode if res else "None")
    return None


def _realized_pnl(ticket: int) -> float:
    from mt5_bridge import bridge_client as mt5
    deals = mt5.history_deals_get(position=ticket) or ()
    return float(sum(getattr(d, "profit", 0.0) for d in deals))


# ── Trade book (gate + paper sim) ─────────────────────────────────────────────
class Book:
    """Tracks open GS-VP trades (real tickets or paper) and closed PnL → gate."""

    def __init__(self):
        self.real: dict[int, dict] = {}      # ticket → trade
        self.paper: dict[str, dict] = {}     # symbol → trade (one per symbol)
        self.closed: list[dict] = []
        if CLOSED_PATH.exists():
            for line in CLOSED_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    self.closed.append(json.loads(line))
                except Exception:
                    pass
        log.info("Loaded %d closed GS-VP trades", len(self.closed))

    def _persist(self, t: dict) -> None:
        with CLOSED_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(t) + "\n")

    def count(self, sym: Optional[str] = None) -> int:
        return sum(1 for t in self.closed if sym is None or t["symbol"] == sym)

    def pf(self, sym: Optional[str] = None) -> float:
        ts = [t for t in self.closed if sym is None or t["symbol"] == sym]
        w = sum(t["pnl"] for t in ts if t["pnl"] > 0)
        l = abs(sum(t["pnl"] for t in ts if t["pnl"] < 0))
        return round(w / l, 2) if l > 0 else (99.0 if w > 0 else 0.0)

    def wr(self, sym: str) -> float:
        ts = [t for t in self.closed if t["symbol"] == sym]
        return round(sum(1 for t in ts if t["pnl"] > 0) / len(ts) * 100, 1) if ts else 0.0

    def gate_ready(self, sym: str) -> bool:
        return self.count(sym) >= PAPER_MIN_TRADES and self.pf(sym) >= PAPER_MIN_PF

    def has_position(self, sym: str) -> bool:
        return sym in self.paper or any(t["symbol"] == sym for t in self.real.values())

    def open_count(self) -> int:
        return len(self.paper) + len(self.real)

    def _close(self, t: dict, pnl: float, exit_kind: str) -> None:
        t.update({"status": "closed", "pnl": round(pnl, 5), "exit": exit_kind,
                  "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self.closed.append(t)
        self._persist(t)
        log.info("CLOSE %s %s %s PnL=%.5f | %s PF=%.2f (%d)",
                 t["side"], t["symbol"], exit_kind, pnl, t["symbol"],
                 self.pf(t["symbol"]), self.count(t["symbol"]))
        if self.gate_ready(t["symbol"]):
            log.info("*** %s GATE PASSED — PF=%.2f trades=%d — REAL-READY ***",
                     t["symbol"], self.pf(t["symbol"]), self.count(t["symbol"]))
            _tg(f"GS-VP {t['symbol']} promotion gate PASSED on demo — "
                f"PF={self.pf(t['symbol']):.2f} ({self.count(t['symbol'])} trades). Real-ready.")

    # real
    def add_real(self, ticket: int, sym: str, side: str, entry: float,
                 sl: float, tp: float, lots: float) -> None:
        self.real[ticket] = {"symbol": sym, "side": side, "entry": entry, "sl": sl,
                             "tp": tp, "lots": lots, "ticket": ticket, "mode": "demo-real",
                             "ts_open": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def reconcile_real(self) -> None:
        if not self.real:
            return
        open_now = {p.ticket for p in _our_positions()}
        for ticket in [t for t in self.real if t not in open_now]:
            t = self.real.pop(ticket)
            pnl = _realized_pnl(ticket)
            self._close(t, pnl, "TP" if pnl >= 0 else "SL")

    # paper
    def add_paper(self, sym: str, side: str, entry: float, sl: float, tp: float) -> None:
        self.paper[sym] = {"symbol": sym, "side": side, "entry": entry, "sl": sl,
                           "tp": tp, "mode": "paper",
                           "ts_open": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        log.info("[PAPER] OPEN %s %s @ %.5f SL=%.5f TP=%.5f", side, sym, entry, sl, tp)

    def tick_paper(self, sym: str, high: float, low: float) -> None:
        t = self.paper.get(sym)
        if not t:
            return
        buy = t["side"] == "BUY"
        hit_sl = low <= t["sl"] if buy else high >= t["sl"]
        hit_tp = high >= t["tp"] if buy else low <= t["tp"]
        if hit_sl or hit_tp:
            px = t["sl"] if hit_sl else t["tp"]
            pnl = (px - t["entry"]) if buy else (t["entry"] - px)
            del self.paper[sym]
            self._close(t, pnl, "TP" if hit_tp else "SL")


def _write_state(mode: str, symbols: list[str], book: Book, daily: DailyState,
                 equity: float, is_demo: bool) -> None:
    try:
        stats = {s: {"trades": book.count(s), "pf": book.pf(s), "wr": book.wr(s),
                     "gate_ready": book.gate_ready(s), "open": book.has_position(s)}
                 for s in symbols}
        STATE_PATH.write_text(json.dumps({
            "agent": "GS-VP", "mode": mode, "account": "demo" if is_demo else "real",
            "symbols": symbols, "tf": TF, "magic": GSVP_MAGIC,
            "trades": book.count(), "pf": book.pf(),
            "open_positions": book.open_count(), "per_symbol": stats,
            "equity": round(equity, 2), "daily_loss_pct": round(daily.daily_loss_pct(equity), 2),
            "trades_today": daily.trades_today(),
            "gate": {"min_trades": PAPER_MIN_TRADES, "min_pf": PAPER_MIN_PF},
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────
def run(symbols: list[str], risk_pct: float, dd_limit: float,
        force_paper: bool, allow_real: bool) -> None:
    from mt5_bridge import bridge_client as mt5

    log.info("=== GS-VP Agent starting === symbols=%s risk=%.1f%% dd=%.1f%% paper=%s allow_real=%s",
             symbols, risk_pct, dd_limit, force_paper, allow_real)
    if not mt5.initialize():
        log.error("MT5 init failed: %s — aborting", mt5.last_error())
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        log.error("No account info — aborting")
        sys.exit(1)
    is_demo = _is_demo(acc)
    log.info("MT5 #%s @ %s | $%.2f equity | account=%s",
             acc.login, acc.server, acc.equity, "DEMO" if is_demo else "REAL")
    if not is_demo and not allow_real:
        log.warning("REAL account + no --allow-real → SIMULATE only (fail-closed)")

    daily = DailyState.load(acc.balance)
    book = Book()
    last_bar: dict[str, int] = {s: 0 for s in symbols}
    _tg(f"GS-VP Agent started on {'DEMO' if is_demo else 'REAL'} ({acc.server}) — "
        f"{', '.join(symbols)} | risk {risk_pct}% | DD {dd_limit}%")

    while True:
        try:
            acc = mt5.account_info()
            if acc is None:
                log.warning("account_info None — retry 60s")
                time.sleep(60); mt5.initialize(); continue
            equity = acc.equity
            daily.roll_if_new_day(acc.balance)
            book.reconcile_real()

            dd_pct = daily.daily_loss_pct(equity)
            if not daily.halted and dd_pct >= dd_limit:
                log.warning("Daily DD %.1f%% >= %.1f%% — HALT for day", dd_pct, dd_limit)
                _tg(f"GS-VP HALTED — daily DD {dd_pct:.1f}%", level="WARNING")
                daily.set_halted()
            if daily.halted:
                _write_state("HALTED", symbols, book, daily, equity, is_demo)
                time.sleep(300); continue

            for sym in symbols:
                bars = _fetch_bars(sym, BARS)
                if bars is None:
                    continue
                # tick paper positions on the forming bar's extremes
                book.tick_paper(sym, bars["high"][-1], bars["low"][-1])

                bar_t = bars["time"][-2]   # last COMPLETE bar
                if bar_t <= last_bar[sym]:
                    continue
                last_bar[sym] = bar_t

                if book.has_position(sym):
                    continue
                if book.open_count() >= MAX_CONCURRENT:
                    continue
                if daily.trades_today() >= MAX_TRADES_PER_DAY:
                    continue

                spread = TYPICAL_SPREADS.get(sym, 0.0001)
                t_i = len(bars["close"]) - 2
                sig = _gsvp_adaptive(bars, t_i, spread, sym)
                if not sig:
                    continue
                side, sl, tp = sig["signal"], sig["sl"], sig["tp"]
                entry = bars["close"][-2]
                log.info("SIGNAL %s %s [%s] entry=%.5f SL=%.5f TP=%.5f",
                         side, sym, sig.get("_pb", "?"), entry, sl, tp)

                # Routing: demo → real order; real+gate+opt-in → real; else simulate.
                send_real = (not force_paper) and (
                    is_demo or (allow_real and book.gate_ready(sym)))
                if send_real:
                    res = _place_order(sym, side, sl, tp, risk_pct)
                    if res is not None:
                        ticket, lots, fill = res
                        book.add_real(ticket, sym, side, fill, sl, tp, lots)
                        daily.add_trade(live=True)
                        if _JOURNAL:
                            _journal_open(ticket=ticket, symbol=sym, direction=side,
                                          entry_price=fill, sl=sl, tp=tp, volume=lots,
                                          source="GSVP", strategies=["GSVP"],
                                          agent="GSVP.Agent", rationale=f"playbook={sig.get('_pb')}")
                else:
                    book.add_paper(sym, side, entry, sl, tp)
                    daily.add_trade(live=False)

            _write_state("SCANNING", symbols, book, daily, equity, is_demo)
            time.sleep(POLL_INTERVAL_S)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down"); break
        except Exception:
            log.exception("loop error — sleep 30s"); time.sleep(30)

    _write_state("STOPPED", symbols, book, daily,
                 acc.equity if acc else 0.0, is_demo)
    mt5.shutdown()
    log.info("=== GS-VP Agent stopped ===")


def main() -> None:
    ap = argparse.ArgumentParser(description="GS-VP Live Agent (M15 volume profile)")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--risk", type=float, default=1.0, help="risk %% per trade")
    ap.add_argument("--dd", type=float, default=6.0, help="daily DD %% halt")
    ap.add_argument("--paper", action="store_true", help="simulate only, never send orders")
    ap.add_argument("--allow-real", action="store_true",
                    help="permit real orders on a non-demo account (gate-passed symbols only)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    run(args.symbols, args.risk, args.dd, args.paper, args.allow_real)


if __name__ == "__main__":
    main()
