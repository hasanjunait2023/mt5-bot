"""M3 Strength-Scalp Agent — currency-strength biased EMA/RSI scalper.

Pipeline per loop:
  1. Daily $200 DD guard (trading_agents.risk_limits).
  2. Refresh -7..+7 currency strength for all 3 sessions via the shared producer
     (writes logs/strength/_strength_state.json — the SAME file the dashboard
     reads, so page and agent never drift) and use the active session's score.
  3. Scan all 28 FX majors/crosses: bias = sign(strength[base]-strength[quote])
     when |diff| >= 3; momentum gate = ADR not exhausted (<70% used) + M3 ATR
     expanding; entry = EMA200 trend + EMA9/15 cross + RSI band, bias-aligned.
  4. ATR-based SL (1.5xATR) / TP (1.5R), 1% risk, max 1 position/pair, demo exec.

Backtest the identical entry math via GS13 in scalp/backtest.py (PF>=1.3 gate)
before trusting it live.

Usage:
  python -m trading_agents.scalp.m3strength_agent
  python -m trading_agents.scalp.m3strength_agent --paper
  python -m trading_agents.scalp.m3strength_agent --risk 1.0 --dd 6.0
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.strength import producer
from trading_agents.strength.strength import PAIRS28, SESSIONS
from trading_agents.strength.entry import m3_signal, atr_expansion_ok, ADR_USED_MAX
from trading_agents.scalp.indicators import adr, adr_used_frac
from trading_agents.iconic.correlation import split_pair
from trading_agents.risk_limits import agent_dd_breached, daily_dd_usd_limit

LOG_DIR = BASE_DIR / "logs" / "m3strength"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "_agent.log"
STATE_PATH = LOG_DIR / "_agent_state.json"
DAILY_PATH = LOG_DIR / "_agent_daily.json"
PAPER_PATH = LOG_DIR / "_paper_trades.jsonl"

MAGIC = 20260900
# Full 28-pair scan: trades any pair where |strength_diff| >= BIAS_MIN_DIFF=5 AND
# the momentum gate fires (EMA9/15 cross + RSI band + ATR expansion). The strict
# MinDiff=5 filter is the edge — it prevents the over-trading that killed MinDiff=3.
# Override via M3STR_SYMBOLS env to restrict to specific pairs.
_DEFAULT_SYMBOLS = ",".join(PAIRS28)
SYMBOLS = [s.strip() for s in os.getenv(
    "M3STR_SYMBOLS", _DEFAULT_SYMBOLS).split(",") if s.strip()]
TF_ENTRY = "M3"
TF_ADR = "D1"
BARS_M3 = 300
BARS_D1 = 30
POLL_INTERVAL_S = 30
BIAS_MIN_DIFF = 5          # validated: only strong currency divergence
MAX_OPEN = int(os.getenv("M3STR_MAX_OPEN", "5"))   # global concurrency cap
_INVALID_FILL = 10030

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("M3Strength.Agent")

# ── Telegram (optional) ───────────────────────────────────────────────────────
try:
    from trading_agents import telegram_hq as _tghq
    _TG_ON = True
except Exception:
    _tghq, _TG_ON = None, False


def _tg(msg: str, level: str = "INFO") -> None:
    if not _TG_ON or _tghq is None:
        return
    try:
        _tghq.send("live_trading", msg, level=level, title="M3 Strength-Scalp")
    except Exception:
        pass


# ── Journal (optional) ────────────────────────────────────────────────────────
try:
    from trading_agents.trade_journal import open_trade as _journal_open
    _JOURNAL = True
except Exception:
    _JOURNAL = False
    def _journal_open(*a, **kw):  # type: ignore
        pass


# ── Daily state ───────────────────────────────────────────────────────────────
class DailyState:
    def __init__(self, start_balance, date, trades=0, halted=False):
        self.start_balance = start_balance
        self.date = date
        self.trades = trades
        self.halted = halted

    @classmethod
    def load(cls, balance: float) -> "DailyState":
        today = datetime.now(timezone.utc).date()
        if DAILY_PATH.exists():
            try:
                d = json.loads(DAILY_PATH.read_text())
                if d.get("date") == str(today):
                    return cls(d["start_balance"], today, d.get("trades", 0),
                               d.get("halted", False))
            except Exception:
                pass
        inst = cls(balance, today, 0, False)
        inst.save()
        return inst

    def save(self) -> None:
        DAILY_PATH.write_text(json.dumps({
            "date": str(self.date), "start_balance": self.start_balance,
            "trades": self.trades, "halted": self.halted,
        }))

    def roll_if_new_day(self, balance: float) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.date:
            self.date, self.start_balance = today, balance
            self.trades, self.halted = 0, False
            self.save()

    def set_halted(self) -> None:
        self.halted = True
        self.save()

    def add_trade(self) -> None:
        self.trades += 1
        self.save()


# ── MT5 helpers (symbol-generic) ──────────────────────────────────────────────
def _mt5_connect() -> bool:
    try:
        from mt5_bridge import bridge_client as mt5
        if mt5.initialize():
            acc = mt5.account_info()
            if acc:
                log.info("MT5 connected: #%s @ %s | $%.2f equity",
                         acc.login, acc.server, acc.equity)
                return True
        log.error("MT5 init failed: %s", mt5.last_error())
        return False
    except ImportError:
        log.error("MetaTrader5 package not installed — cannot run")
        return False


def _fetch_bars(symbol: str, tf_str: str, n: int) -> Optional[dict]:
    from mt5_bridge import bridge_client as mt5
    tf = getattr(mt5, f"TIMEFRAME_{tf_str}", tf_str)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) < 30:
        return None
    return {
        "time":  [int(r["time"])    for r in rates],
        "high":  [float(r["high"])  for r in rates],
        "low":   [float(r["low"])   for r in rates],
        "close": [float(r["close"]) for r in rates],
    }


def _open_positions() -> dict:
    """{symbol: count} of this agent's open positions (by magic)."""
    from mt5_bridge import bridge_client as mt5
    out: dict = {}
    pos = mt5.positions_get()
    if not pos:
        return out
    for p in pos:
        if getattr(p, "magic", None) == MAGIC:
            out[p.symbol] = out.get(p.symbol, 0) + 1
    return out


def _calc_lots(symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    from mt5_bridge import bridge_client as mt5
    acc = mt5.account_info()
    sym = mt5.symbol_info(symbol)
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
    max_allowed = (acc.equity * 0.02) / value_lot
    return round(max(sym.volume_min, min(lots, sym.volume_max, max_allowed)), 2)


def _place_order(symbol: str, side: str, stop: float, tp: float,
                 risk_pct: float) -> Optional[tuple[int, float]]:
    from mt5_bridge import bridge_client as mt5
    tick = mt5.symbol_info_tick(symbol)
    sym = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    digits = sym.digits
    live_entry = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    if abs(live_entry - stop) < sym.point * 5:
        log.warning("%s: SL too tight, skip", symbol)
        return None
    lots = _calc_lots(symbol, live_entry, stop, risk_pct)
    if lots <= 0:
        log.warning("%s: lot=0, skip", symbol)
        return None

    fm = int(getattr(sym, "filling_mode", 0) or 0)
    if fm & 1:
        fill_order = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2:
        fill_order = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fill_order = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]

    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume": lots, "type": order_type, "price": live_entry,
        "sl": round(stop, digits), "tp": round(tp, digits),
        "deviation": 10, "magic": MAGIC, "comment": "M3Strength",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": fill_order[0],
    }
    res = mt5.order_send(req)
    fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and fi < len(fill_order):
        req["type_filling"] = fill_order[fi]
        fi += 1
        res = mt5.order_send(req)

    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER: %s %s @ %.5f  SL=%.5f  TP=%.5f  lots=%.2f",
                 side, symbol, live_entry, stop, tp, lots)
        _tg(f"M3Strength {side} {symbol} @ {live_entry:.5f}  SL={stop:.5f}  TP={tp:.5f}  lots={lots}")
        return int(res.order), lots
    log.error("%s: order FAILED retcode=%s", symbol, res.retcode if res else "None")
    return None


# ── Paper book (used only with --paper) ───────────────────────────────────────
class PaperBook:
    def __init__(self):
        self._pending: dict = {}   # symbol → trade
        self._closed: list = []
        self._load()

    def _load(self):
        if PAPER_PATH.exists():
            try:
                for line in PAPER_PATH.read_text(encoding="utf-8").splitlines():
                    t = json.loads(line)
                    if t.get("status") == "closed":
                        self._closed.append(t)
            except Exception:
                pass

    @property
    def pf(self) -> float:
        wins = sum(t["pnl"] for t in self._closed if t.get("pnl", 0) > 0)
        loss = abs(sum(t["pnl"] for t in self._closed if t.get("pnl", 0) < 0))
        return round(wins / loss, 2) if loss > 0 else (99.0 if wins > 0 else 0.0)

    @property
    def count(self) -> int:
        return len(self._closed)

    def has(self, symbol: str) -> bool:
        return symbol in self._pending

    def open(self, symbol, side, entry, stop, tp):
        t = {"symbol": symbol, "side": side, "entry": entry, "stop": stop,
             "tp": tp, "status": "open",
             "ts_open": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._pending[symbol] = t
        with PAPER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(t) + "\n")
        log.info("[PAPER] OPEN %s %s @ %.5f SL=%.5f TP=%.5f", side, symbol, entry, stop, tp)

    def tick(self, symbol, high, low):
        pos = self._pending.get(symbol)
        if not pos:
            return
        side, entry, stop, tp = pos["side"], pos["entry"], pos["stop"], pos["tp"]
        hit_sl = low <= stop if side == "BUY" else high >= stop
        hit_tp = high >= tp if side == "BUY" else low <= tp
        if hit_sl or hit_tp:
            ex = stop if hit_sl else tp
            pnl = (ex - entry) if side == "BUY" else (entry - ex)
            pos.update({"status": "closed", "exit": "TP" if hit_tp else "SL",
                        "exit_price": ex, "pnl": round(pnl, 8),
                        "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            self._closed.append(pos)
            del self._pending[symbol]
            with PAPER_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(pos) + "\n")
            log.info("[PAPER] CLOSE %s %s %s  PnL=%.5f  PF=%.2f (%d)",
                     side, symbol, pos["exit"], pnl, self.pf, self.count)


# ── Session selection ─────────────────────────────────────────────────────────
def active_session_score(state: dict) -> tuple[str, dict]:
    """Pick the session whose hour-band contains now; else newyork>london>asian."""
    from trading_agents.scalp.indicators import session_info
    h = session_info(int(time.time()))["hour"]
    sessions = state.get("sessions", {})
    for name, win in SESSIONS.items():
        if win["start_h"] <= h < win["end_h"] and name in sessions:
            return name, sessions[name].get("score", {})
    for name in ("newyork", "london_1h", "asian"):
        if name in sessions:
            return name, sessions[name].get("score", {})
    return "none", {}


# ── State writer ──────────────────────────────────────────────────────────────
def _write_state(mode: str, daily: DailyState, equity: float, sess_name: str,
                 score: dict, open_pos: dict, candidates: list, paper: Optional[PaperBook]) -> None:
    try:
        from mt5_bridge import bridge_client as _mt5
        breached, dd_usd = agent_dd_breached(_mt5, MAGIC)
        STATE_PATH.write_text(json.dumps({
            "mode": mode,
            "magic": MAGIC,
            "symbols": SYMBOLS,
            "active_session": sess_name,
            "score": score,
            "open_positions": open_pos,
            "candidates": candidates[:10],
            "equity": round(equity, 2),
            "daily_dd_usd": round(dd_usd, 2),
            "dd_limit_usd": daily_dd_usd_limit(),
            "trades_today": daily.trades,
            "paper_pf": paper.pf if paper else None,
            "paper_trades": paper.count if paper else None,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")
    except Exception:
        log.exception("state write failed")


# ── Per-pair evaluation ───────────────────────────────────────────────────────
def eval_pair(symbol: str, score: dict) -> Optional[dict]:
    base, quote = split_pair(symbol)
    if base not in score or quote not in score:
        return None
    diff = score[base] - score[quote]
    if abs(diff) < BIAS_MIN_DIFF:
        return None
    bias = "BUY" if diff > 0 else "SELL"

    m3 = _fetch_bars(symbol, TF_ENTRY, BARS_M3)
    if not m3 or len(m3["close"]) < 210:
        return None
    # Drop the still-forming bar → operate on completed bars.
    h, l, c = m3["high"][:-1], m3["low"][:-1], m3["close"][:-1]

    d1 = _fetch_bars(symbol, TF_ADR, BARS_D1)
    if d1 and len(d1["high"]) >= 16:
        adr_val = adr(d1["high"], d1["low"], 14)
        used = adr_used_frac(d1["high"][-1], d1["low"][-1], adr_val)
        if used > ADR_USED_MAX:
            return None
    if not atr_expansion_ok(h, l, c):
        return None

    sig = m3_signal(h, l, c, bias)
    if sig:
        sig["symbol"] = symbol
        sig["diff"] = diff
    return sig


# ── Main loop ─────────────────────────────────────────────────────────────────
def run(risk_pct: float, dd_limit: float, force_paper: bool) -> None:
    from mt5_bridge import bridge_client as mt5

    log.info("=== M3 Strength-Scalp Agent starting ===")
    log.info("Symbols: %d | TF=%s | risk=%.1f%% | DD=$%.0f | max_open=%d | paper=%s",
             len(SYMBOLS), TF_ENTRY, risk_pct, daily_dd_usd_limit(), MAX_OPEN, force_paper)

    if not _mt5_connect():
        log.error("Cannot connect to MT5 — aborting")
        sys.exit(1)

    acc = mt5.account_info()
    daily = DailyState.load(acc.balance)
    paper = PaperBook() if force_paper else None
    _last_bar: dict[str, int] = {}

    while True:
        try:
            acc = mt5.account_info()
            if acc is None:
                log.warning("account_info None — retry in 60s")
                time.sleep(60)
                _mt5_connect()
                continue
            equity = acc.equity
            daily.roll_if_new_day(acc.balance)

            breached, dd_usd = agent_dd_breached(mt5, MAGIC)
            if not daily.halted and breached:
                log.warning("Daily DD $%.2f >= $%.2f — HALTED for the day",
                            dd_usd, daily_dd_usd_limit())
                _tg(f"M3Strength HALTED — daily DD ${dd_usd:.2f}", level="WARNING")
                daily.set_halted()
            if daily.halted:
                _write_state("HALTED", daily, equity, "halted", {}, {}, [], paper)
                time.sleep(300)
                continue

            # 1. Refresh strength (also writes the shared state JSON).
            state = producer.build_state(mt5)
            producer.write_state(state)
            sess_name, score = active_session_score(state)

            open_pos = _open_positions()
            if paper:
                for sym in list(paper._pending.keys()):
                    b = _fetch_bars(sym, TF_ENTRY, 60)
                    if b:
                        paper.tick(sym, b["high"][-2], b["low"][-2])

            # 2. Scan 28 pairs for qualifying setups.
            candidates = []
            for symbol in SYMBOLS:
                base, quote = split_pair(symbol)
                if base in score and quote in score:
                    d = score[base] - score[quote]
                    if abs(d) >= BIAS_MIN_DIFF:
                        candidates.append({"symbol": symbol, "diff": d,
                                           "side": "BUY" if d > 0 else "SELL"})
            candidates.sort(key=lambda x: abs(x["diff"]), reverse=True)

            n_open = sum(open_pos.values()) + (len(paper._pending) if paper else 0)
            for cand in candidates:
                symbol = cand["symbol"]
                if n_open >= MAX_OPEN:
                    log.info("max_open %d reached — %d candidates left unfilled",
                             MAX_OPEN, len(candidates) - candidates.index(cand))
                    break
                if open_pos.get(symbol) or (paper and paper.has(symbol)):
                    continue
                # New-bar gate per symbol (avoid re-eval same M3 bar).
                # NOTE: _fetch_bars returns None when fewer than 30 bars come
                # back, so this MUST request >=30 (a count of 3 silently skipped
                # every candidate → the agent never traded).
                m3t = _fetch_bars(symbol, TF_ENTRY, 60)
                if not m3t:
                    continue
                bar_t = m3t["time"][-2]
                if _last_bar.get(symbol) == bar_t:
                    continue

                sig = eval_pair(symbol, score)
                if _last_bar.get(symbol) != bar_t:
                    _last_bar[symbol] = bar_t
                if not sig:
                    continue

                side, sl, tp = sig["signal"], sig["sl"], sig["tp"]
                log.info("SIGNAL %s %s diff=%+d entry=%.5f SL=%.5f TP=%.5f",
                         side, symbol, sig["diff"], sig["entry"], sl, tp)
                if paper:
                    paper.open(symbol, side, sig["entry"], sl, tp)
                    daily.add_trade()
                    n_open += 1
                else:
                    res = _place_order(symbol, side, sl, tp, risk_pct)
                    if res:
                        ticket, lots = res
                        daily.add_trade()
                        n_open += 1
                        if _JOURNAL:
                            _journal_open(ticket=ticket, symbol=symbol, direction=side,
                                          entry_price=sig["entry"], sl=sl, tp=tp, volume=lots,
                                          source="M3Strength", strategies=["GS13"],
                                          agent="M3Strength.Agent",
                                          rationale=f"strength diff={sig['diff']:+d} sess={sess_name}")

            _write_state("SCANNING", daily, equity, sess_name, score, open_pos, candidates, paper)
            time.sleep(POLL_INTERVAL_S)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            break
        except Exception:
            log.exception("loop error — sleeping 30s")
            time.sleep(30)

    mt5.shutdown()
    log.info("=== M3 Strength-Scalp Agent stopped ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="M3 Strength-Scalp Agent (28-pair)")
    parser.add_argument("--risk", type=float, default=1.0, help="Risk %% per trade")
    parser.add_argument("--dd", type=float, default=6.0, help="Daily DD %% (state only; $ halt via AGENT_DAILY_DD_USD)")
    parser.add_argument("--paper", action="store_true", help="Paper-trade only")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    run(args.risk, args.dd, args.paper)


if __name__ == "__main__":
    main()
