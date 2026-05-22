"""Gold Scalp Live Agent — GS11 (Opening Range) + GS07 (Liquidity Sweep) on XAUUSD M1.

Paper-trade gate: 20 trades, PF >= 1.3 before a strategy goes live.
GS11 is the primary candidate (PF=1.77 backtest). GS07 stays paper until
it independently clears the gate (PF=1.11 backtest, MARGINAL).

Usage:
  python -m trading_agents.scalp.agent
  python -m trading_agents.scalp.agent --paper
  python -m trading_agents.scalp.agent --risk 0.5 --dd 4.0
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

LOG_DIR    = BASE_DIR / "logs" / "scalp"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH   = LOG_DIR / "_agent.log"
STATE_PATH = LOG_DIR / "_agent_state.json"
DAILY_PATH = LOG_DIR / "_agent_daily.json"
PAPER_PATH = LOG_DIR / "_paper_trades.jsonl"

MAGIC           = 20260522
BARS_M1         = 300
POLL_INTERVAL_S = 30
PAPER_MIN_TRADES = 20
PAPER_MIN_PF     = 1.3
MAX_TRADES_PER_DAY = 3
_INVALID_FILL = 10030

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("Scalp.Agent")

# ── Telegram ──────────────────────────────────────────────────────────────────
try:
    from trading_agents import telegram_hq as _tghq
    _TG_ON = True
except Exception:
    _tghq = None
    _TG_ON = False


def _tg(msg: str, level: str = "INFO") -> None:
    if not _TG_ON or _tghq is None:
        return
    try:
        _tghq.send("live_trading", msg, level=level, title="Scalp Agent")
    except Exception:
        pass


# ── Journal ───────────────────────────────────────────────────────────────────
try:
    from trading_agents.trade_journal import open_trade as _journal_open, close_trade as _journal_close
    _JOURNAL = True
except Exception:
    _JOURNAL = False
    def _journal_open(*a, **kw): pass   # type: ignore
    def _journal_close(*a, **kw): pass  # type: ignore


# ── Strategy signal functions (from backtest.py) ──────────────────────────────
from trading_agents.scalp.backtest import (
    _gs11_opening_range_scalper,
    _gs07_liquidity_sweep,
    TYPICAL_SPREADS,
)

SYMBOL = "XAUUSD"
STRATEGIES = ["GS11", "GS07"]


# ── Daily state ───────────────────────────────────────────────────────────────
class DailyState:
    def __init__(self, start_balance: float, date, trades: int):
        self.date = date
        self.start_balance = start_balance
        self.trades = trades

    @classmethod
    def load(cls, current_balance: float) -> "DailyState":
        today = datetime.now(timezone.utc).date()
        if DAILY_PATH.exists():
            try:
                d = json.loads(DAILY_PATH.read_text())
                if d.get("date") == str(today):
                    return cls(d["start_balance"], today, d.get("trades", 0))
            except Exception:
                pass
        inst = cls(current_balance, today, 0)
        inst.save()
        return inst

    def save(self) -> None:
        DAILY_PATH.write_text(json.dumps(
            {"date": str(self.date), "start_balance": self.start_balance,
             "trades": self.trades}))

    def roll_if_new_day(self, balance: float) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.date:
            self.date = today
            self.start_balance = balance
            self.trades = 0
            self.save()

    def daily_loss_pct(self, equity: float) -> float:
        if self.start_balance <= 0:
            return 0.0
        return max((self.start_balance - equity) / self.start_balance * 100, 0.0)

    def add_trade(self) -> None:
        self.trades += 1
        self.save()

    def trades_today(self) -> int:
        return self.trades


# ── Paper tracker ─────────────────────────────────────────────────────────────
class PaperTracker:
    def __init__(self, force_paper: bool = False):
        self.force_paper = force_paper
        self._pending: dict[str, dict] = {}   # "SYMBOL:STRAT" → trade
        self._closed: list[dict] = []
        self._load()

    def _load(self) -> None:
        if PAPER_PATH.exists():
            try:
                for line in PAPER_PATH.read_text(encoding="utf-8").splitlines():
                    t = json.loads(line)
                    if t.get("status") == "closed":
                        self._closed.append(t)
            except Exception:
                pass
        log.info("Paper trades loaded: %d closed", len(self._closed))

    def _pf(self, strat: Optional[str] = None) -> float:
        trades = [t for t in self._closed if strat is None or t.get("strategy") == strat]
        wins   = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
        losses = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
        return round(wins / losses, 2) if losses > 0 else (99.0 if wins > 0 else 0.0)

    @property
    def profit_factor(self) -> float:
        return self._pf()

    @property
    def trade_count(self) -> int:
        return len(self._closed)

    def strat_count(self, strat: str) -> int:
        return sum(1 for t in self._closed if t.get("strategy") == strat)

    def strat_pf(self, strat: str) -> float:
        return self._pf(strat)

    def strat_wr(self, strat: str) -> float:
        trades = [t for t in self._closed if t.get("strategy") == strat]
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        return round(wins / len(trades) * 100, 1)

    def is_live_ready(self, strat: str) -> bool:
        if self.force_paper:
            return False
        n = self.strat_count(strat)
        pf = self.strat_pf(strat)
        return n >= PAPER_MIN_TRADES and pf >= PAPER_MIN_PF

    def _key(self, symbol: str, strat: str) -> str:
        return f"{symbol}:{strat}"

    def has_pending(self, symbol: str, strat: str) -> bool:
        return self._key(symbol, strat) in self._pending

    def open_paper(self, symbol: str, strat: str, side: str,
                   entry: float, stop: float, tp: float) -> None:
        key = self._key(symbol, strat)
        t = {
            "symbol": symbol, "strategy": strat, "side": side,
            "entry": entry, "stop": stop, "tp": tp,
            "status": "open",
            "ts_open": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._pending[key] = t
        with PAPER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(t) + "\n")
        log.info("[PAPER] OPEN %s %s/%s @ %.5f  SL=%.5f  TP=%.5f",
                 side, symbol, strat, entry, stop, tp)
        _tg(f"[PAPER] {strat} {side} {symbol} @ {entry:.5f}  SL={stop:.5f}  TP={tp:.5f}")

    def tick_paper(self, key: str, high: float, low: float) -> None:
        if key not in self._pending:
            return
        pos = self._pending[key]
        side, entry, stop, tp = pos["side"], pos["entry"], pos["stop"], pos["tp"]
        hit_sl = low <= stop if side == "BUY" else high >= stop
        hit_tp = high >= tp  if side == "BUY" else low <= tp
        if hit_sl or hit_tp:
            exit_price = stop if hit_sl else tp
            pnl = (exit_price - entry) if side == "BUY" else (entry - exit_price)
            pos.update({
                "status": "closed",
                "exit": "TP" if hit_tp else "SL",
                "exit_price": exit_price,
                "pnl": round(pnl, 8),
                "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            self._closed.append(pos)
            del self._pending[key]
            with PAPER_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(pos) + "\n")
            strat = pos.get("strategy", "?")
            icon = "+" if pnl > 0 else "-"
            log.info("[PAPER] CLOSE %s %s/%s  %s  PnL=%s%.5f  strat_PF=%.2f (%d trades)",
                     side, pos["symbol"], strat, pos["exit"], icon, abs(pnl),
                     self.strat_pf(strat), self.strat_count(strat))
            if self.is_live_ready(strat):
                log.info("[PAPER] *** %s PROMOTION GATE PASSED — PF=%.2f trades=%d ***",
                         strat, self.strat_pf(strat), self.strat_count(strat))
                _tg(f"Scalp {strat} PROMOTION GATE passed — "
                    f"PF={self.strat_pf(strat):.2f} ({self.strat_count(strat)} trades). Going LIVE.",
                    level="INFO")


# ── MT5 helpers ───────────────────────────────────────────────────────────────
def _mt5_connect() -> bool:
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            acc = mt5.account_info()
            if acc:
                log.info("MT5 connected: #%s @ %s | $%.2f equity",
                         acc.login, acc.server, acc.equity)
                return True
        log.error("MT5 init failed: %s", mt5.last_error())
        return False
    except ImportError:
        log.error("MetaTrader5 package not installed — paper-trade only")
        return False


def _fetch_m1(symbol: str, n: int) -> Optional[dict]:
    import MetaTrader5 as mt5
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, n)
    if rates is None or len(rates) < 60:
        return None
    return {
        "time":        [int(r["time"])  for r in rates],
        "open":        [float(r["open"]) for r in rates],
        "high":        [float(r["high"]) for r in rates],
        "low":         [float(r["low"])  for r in rates],
        "close":       [float(r["close"]) for r in rates],
        "tick_volume": [float(r.get("tick_volume", 0)) for r in rates],
    }


def _has_open_position(symbol: str) -> bool:
    import MetaTrader5 as mt5
    pos = mt5.positions_get(symbol=symbol)
    return pos is not None and any(p.magic == MAGIC for p in pos)


def _calc_lots(symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    import MetaTrader5 as mt5
    acc = mt5.account_info()
    sym = mt5.symbol_info(symbol)
    if acc is None or sym is None:
        return 0.0
    risk_usd  = acc.equity * risk_pct / 100.0
    sl_dist   = abs(entry - stop)
    if sl_dist < sym.point or sym.trade_tick_size <= 0:
        return 0.0
    value_lot = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0:
        return 0.0
    lots = risk_usd / value_lot
    lots = round(lots / sym.volume_step) * sym.volume_step
    max_allowed = (acc.equity * 0.02) / value_lot if value_lot > 0 else sym.volume_max
    return round(max(sym.volume_min, min(lots, sym.volume_max, max_allowed)), 2)


def _place_order(symbol: str, side: str, entry: float, stop: float, tp: float,
                 risk_pct: float, strat: str) -> Optional[tuple[int, float]]:
    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick(symbol)
    sym  = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    digits = sym.digits
    live_entry = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    sl_dist = abs(live_entry - stop)
    if sl_dist < sym.point * 5:
        log.warning("%s/%s: SL too tight (%.5f), skip", symbol, strat, sl_dist)
        return None

    lots = _calc_lots(symbol, live_entry, stop, risk_pct)
    if lots <= 0:
        log.warning("%s/%s: lot=0, skip", symbol, strat)
        return None

    fm = int(getattr(sym, "filling_mode", 0) or 0)
    if fm & 1:
        fill_order = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2:
        fill_order = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fill_order = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]

    req = {
        "action":       mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume":       lots, "type": order_type, "price": live_entry,
        "sl":           round(stop, digits), "tp": round(tp, digits),
        "deviation":    10, "magic": MAGIC, "comment": f"Scalp_{strat}",
        "type_time":    mt5.ORDER_TIME_GTC, "type_filling": fill_order[0],
    }
    res = mt5.order_send(req)
    fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and fi < len(fill_order):
        req["type_filling"] = fill_order[fi]
        fi += 1
        res = mt5.order_send(req)

    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER PLACED: %s %s/%s @ %.5f  SL=%.5f  TP=%.5f  lots=%.2f",
                 side, symbol, strat, live_entry, stop, tp, lots)
        _tg(f"Scalp {strat} {side} {symbol} @ {live_entry:.5f}  SL={stop:.5f}  "
            f"TP={tp:.5f}  lots={lots}")
        return int(res.order), lots
    code = res.retcode if res else "None"
    log.error("%s/%s: order FAILED retcode=%s", symbol, strat, code)
    return None


# ── State writer ──────────────────────────────────────────────────────────────
def _write_state(mode: str, daily: DailyState, paper: PaperTracker,
                 live_strats: dict[str, bool], equity: float) -> None:
    try:
        strat_stats = {}
        for s in STRATEGIES:
            strat_stats[s] = {
                "trades": paper.strat_count(s),
                "pf":     paper.strat_pf(s),
                "wr":     paper.strat_wr(s),
                "live":   live_strats.get(s, False),
            }
        STATE_PATH.write_text(json.dumps({
            "mode":           mode,
            "strategies":     STRATEGIES,
            "symbol":         SYMBOL,
            "paper_trades":   paper.trade_count,
            "paper_pf":       paper.profit_factor,
            "paper_pending":  list(paper._pending.keys()),
            "strat_stats":    strat_stats,
            "equity":         round(equity, 2),
            "daily_loss_pct": round(daily.daily_loss_pct(equity), 2),
            "trades_today":   daily.trades_today(),
            "updated_at":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Signal evaluation ─────────────────────────────────────────────────────────
def _eval_signal(strat: str, bars: dict, spread: float) -> Optional[dict]:
    t_i = len(bars["close"]) - 2   # last complete bar
    if strat == "GS11":
        return _gs11_opening_range_scalper(bars, t_i, spread)
    if strat == "GS07":
        return _gs07_liquidity_sweep(bars, t_i, spread)
    return None


# ── Main loop ─────────────────────────────────────────────────────────────────
def run(risk_pct: float, dd_limit: float, force_paper: bool) -> None:
    import MetaTrader5 as mt5

    log.info("=== Gold Scalp Agent starting ===")
    log.info("Symbol: %s | strategies: %s | risk=%.1f%% | DD=%.1f%% | paper=%s",
             SYMBOL, STRATEGIES, risk_pct, dd_limit, force_paper)

    if not _mt5_connect():
        log.error("Cannot connect to MT5 — aborting")
        sys.exit(1)

    acc   = mt5.account_info()
    daily = DailyState.load(acc.balance)
    paper = PaperTracker(force_paper=force_paper)

    live_strats: dict[str, bool] = {s: paper.is_live_ready(s) for s in STRATEGIES}
    _last_bar_time: dict[str, int] = {s: 0 for s in STRATEGIES}

    spread = TYPICAL_SPREADS.get(SYMBOL, 0.30)

    log.info("Initial state — paper: %d trades  total PF=%.2f  live=%s",
             paper.trade_count, paper.profit_factor, live_strats)

    while True:
        try:
            acc = mt5.account_info()
            if acc is None:
                log.warning("MT5 account_info None — retrying in 60s")
                time.sleep(60)
                _mt5_connect()
                continue

            equity = acc.equity
            daily.roll_if_new_day(acc.balance)

            # Daily DD guard
            dd_pct = daily.daily_loss_pct(equity)
            if dd_pct >= dd_limit:
                log.warning("Daily DD %.1f%% >= limit %.1f%% — HALTED", dd_pct, dd_limit)
                _tg(f"Scalp Agent HALTED — daily DD {dd_pct:.1f}%", level="WARNING")
                _write_state("HALTED", daily, paper, live_strats, equity)
                time.sleep(300)
                continue

            # Fetch M1 bars
            bars = _fetch_m1(SYMBOL, BARS_M1)
            if bars is None:
                log.warning("No M1 bars for %s — sleeping 60s", SYMBOL)
                _write_state("SCANNING", daily, paper, live_strats, equity)
                time.sleep(60)
                continue

            last_bar_t = bars["time"][-2]  # last complete bar timestamp

            # Tick paper positions
            bar_high = bars["high"][-2]
            bar_low  = bars["low"][-2]
            for key in list(paper._pending.keys()):
                paper.tick_paper(key, bar_high, bar_low)

            # Check promotion
            for s in STRATEGIES:
                if not live_strats[s] and paper.is_live_ready(s):
                    live_strats[s] = True
                    log.info("%s PROMOTED TO LIVE MODE", s)

            # Daily trade limit guard
            if daily.trades_today() >= MAX_TRADES_PER_DAY:
                _write_state("SCANNING", daily, paper, live_strats, equity)
                time.sleep(POLL_INTERVAL_S)
                continue

            # Run each strategy if we have a new bar
            for strat in STRATEGIES:
                if last_bar_t <= _last_bar_time[strat]:
                    continue   # same bar, already processed

                _last_bar_time[strat] = last_bar_t

                sig = _eval_signal(strat, bars, spread)
                if sig is None:
                    continue

                side   = sig["signal"]
                sl     = sig["sl"]
                tp_val = sig["tp"]
                entry  = bars["close"][-2]

                key = paper._key(SYMBOL, strat)
                if paper.has_pending(SYMBOL, strat):
                    log.debug("%s/%s: paper position pending — skip", SYMBOL, strat)
                    continue
                if _has_open_position(SYMBOL):
                    log.debug("%s/%s: live position open — skip", SYMBOL, strat)
                    continue

                log.info("SIGNAL: %s %s/%s  entry=%.5f  SL=%.5f  TP=%.5f",
                         side, SYMBOL, strat, entry, sl, tp_val)

                is_live = live_strats[strat]
                if is_live:
                    result = _place_order(SYMBOL, side, entry, sl, tp_val, risk_pct, strat)
                    if result is not None:
                        ticket, lots = result
                        daily.add_trade()
                        if _JOURNAL:
                            _journal_open(
                                ticket=ticket, symbol=SYMBOL, direction=side,
                                entry_price=entry, sl=sl, tp=tp_val, volume=lots,
                                source="Scalp", strategies=[strat],
                                agent="Scalp.Agent",
                                rationale=f"strategy={strat}",
                            )
                else:
                    paper.open_paper(SYMBOL, strat, side, entry, sl, tp_val)
                    daily.add_trade()

            _write_state("SCANNING", daily, paper, live_strats, equity)
            time.sleep(POLL_INTERVAL_S)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            break
        except Exception:
            log.exception("Agent loop error — sleeping 30s")
            time.sleep(30)

    _write_state("STOPPED", daily, paper, live_strats,
                 mt5.account_info().equity if mt5.account_info() else 0.0)
    mt5.shutdown()
    log.info("=== Gold Scalp Agent stopped ===")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Gold Scalp Agent (GS11 + GS07 on XAUUSD M1)")
    parser.add_argument("--risk",  type=float, default=1.0,  help="Risk %% per trade")
    parser.add_argument("--dd",    type=float, default=5.0,  help="Daily DD %% halt threshold")
    parser.add_argument("--paper", action="store_true",      help="Force paper-trade forever")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    run(args.risk, args.dd, args.paper)


if __name__ == "__main__":
    main()
