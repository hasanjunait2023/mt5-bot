"""Iconic Scalp Agent — 3-tier wide scanning architecture.

Tier 1 — EXECUTE (proven GO, can promote to live):
  NZDUSD — PF 1.45, 65.2% WR, 100-day backtest with partial exit at 1R.

Tier 2 — PAPER ONLY until per-symbol gate (20 trades + PF >= 1.3 → auto-promote):
  EURUSD, GBPUSD, USDCHF, AUDUSD — scan all, paper-trade independently.

Each symbol has its own paper gate. A symbol that clears the gate auto-promotes to live.
Partial exit at 1R: close 50%, move stop to breakeven on all symbols.

Usage:
  python -m trading_agents.iconic.agent_scalp
  python -m trading_agents.iconic.agent_scalp --paper
  python -m trading_agents.iconic.agent_scalp --risk 0.5
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "mt5_bridge"))

LOG_DIR    = BASE_DIR / "logs" / "iconic_scalp"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH   = LOG_DIR / "_agent_log.txt"
STATE_PATH = LOG_DIR / "_agent_state.json"
DAILY_PATH = LOG_DIR / "_agent_daily.json"
PAPER_PATH = LOG_DIR / "_paper_trades.jsonl"

MAGIC              = 20260701   # distinct from H1 Iconic agent (20260700)
BARS_M15           = 500
BARS_H1            = 500
POLL_INTERVAL_S    = 30
PAPER_MIN_TRADES   = 20
PAPER_MIN_PF       = 1.3
MAX_TRADES_PER_DAY = 2          # per symbol

# Tier 1 — proven GO, eligible for live execution
TIER1_SYMBOLS = ["NZDUSD"]

# Tier 2 — paper-only until each symbol independently passes the gate
TIER2_SYMBOLS = ["EURUSD", "GBPUSD", "USDCHF", "AUDUSD"]

SYMBOLS = TIER1_SYMBOLS + TIER2_SYMBOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("Iconic.Scalp")

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
        _tghq.send("live_trading", msg, level=level, title="Iconic Scalp")
    except Exception:
        pass


# ── Journal ───────────────────────────────────────────────────────────────────
try:
    from trading_agents.trade_journal import open_trade as _journal_open, \
                                            close_trade as _journal_close
    _JOURNAL = True
except Exception:
    _JOURNAL = False
    def _journal_open(*a, **kw): pass   # type: ignore
    def _journal_close(*a, **kw): pass  # type: ignore


# ── Daily state ───────────────────────────────────────────────────────────────
class DailyState:
    def __init__(self, start_balance: float, date, trades: dict):
        self.date          = date
        self.start_balance = start_balance
        self.trades        = trades

    @classmethod
    def load(cls, current_balance: float) -> "DailyState":
        today = datetime.now(timezone.utc).date()
        if DAILY_PATH.exists():
            try:
                d = json.loads(DAILY_PATH.read_text())
                if d.get("date") == str(today):
                    return cls(d["start_balance"], today, d.get("trades", {}))
            except Exception:
                pass
        inst = cls(current_balance, today, {})
        inst.save()
        return inst

    def save(self) -> None:
        DAILY_PATH.write_text(json.dumps(
            {"date": str(self.date), "start_balance": self.start_balance,
             "trades": self.trades}))

    def roll_if_new_day(self, balance: float) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.date:
            self.date = today; self.start_balance = balance; self.trades = {}
            self.save()

    def daily_loss_pct(self, equity: float) -> float:
        if self.start_balance <= 0:
            return 0.0
        return max((self.start_balance - equity) / self.start_balance * 100, 0.0)

    def add_trade(self, symbol: str) -> None:
        self.trades[symbol] = self.trades.get(symbol, 0) + 1
        self.save()

    def trades_today(self, symbol: str) -> int:
        return self.trades.get(symbol, 0)


# ── Scalp paper tracker (per-symbol, partial exit at 1R) ──────────────────────
class ScalpPaperTracker:
    """Per-symbol paper tracker with partial exit simulation.

    Each symbol tracks its own closed-trade list for independent promotion gates.
    When a position reaches 1R profit:
      - Locks in partial_pnl = 0.5 × risk_dist (50% closed)
      - Moves virtual stop to breakeven
      - Remaining 50% continues to TP or BE stop
    """

    def __init__(self, force_paper: bool = False):
        self.force_paper       = force_paper
        self._pending: dict    = {}   # symbol → position dict
        self._closed: list     = []   # all closed trades
        self._closed_by_sym: dict = {}  # symbol → list of closed trades
        self._load()

    def _load(self) -> None:
        if PAPER_PATH.exists():
            try:
                for line in PAPER_PATH.read_text().splitlines():
                    t = json.loads(line)
                    if t.get("status") == "closed":
                        self._closed.append(t)
                        sym = t.get("symbol", "")
                        self._closed_by_sym.setdefault(sym, []).append(t)
            except Exception:
                pass
        log.info("Scalp paper: %d total closed across %d symbols",
                 len(self._closed), len(self._closed_by_sym))

    def _record_close(self, pos: dict) -> None:
        self._closed.append(pos)
        sym = pos.get("symbol", "")
        self._closed_by_sym.setdefault(sym, []).append(pos)

    # ── Overall stats ──
    @property
    def profit_factor(self) -> float:
        wins   = sum(t["pnl"] for t in self._closed if t.get("pnl", 0) > 0)
        losses = abs(sum(t["pnl"] for t in self._closed if t.get("pnl", 0) < 0))
        return round(wins / losses, 2) if losses > 0 else (99.0 if wins > 0 else 0.0)

    @property
    def trade_count(self) -> int:
        return len(self._closed)

    # ── Per-symbol stats ──
    def pf_sym(self, sym: str) -> float:
        closed = self._closed_by_sym.get(sym, [])
        wins   = sum(t["pnl"] for t in closed if t.get("pnl", 0) > 0)
        losses = abs(sum(t["pnl"] for t in closed if t.get("pnl", 0) < 0))
        return round(wins / losses, 2) if losses > 0 else (99.0 if wins > 0 else 0.0)

    def count_sym(self, sym: str) -> int:
        return len(self._closed_by_sym.get(sym, []))

    def wr_sym(self, sym: str) -> float:
        closed = self._closed_by_sym.get(sym, [])
        if not closed:
            return 0.0
        return round(sum(1 for t in closed if t.get("pnl", 0) > 0) / len(closed) * 100, 1)

    def ready_sym(self, sym: str) -> bool:
        """True when this symbol independently passed the paper promotion gate."""
        if self.force_paper:
            return False
        return self.count_sym(sym) >= PAPER_MIN_TRADES and self.pf_sym(sym) >= PAPER_MIN_PF

    def open_paper(self, symbol: str, side: str, entry: float,
                   stop: float, tp: float, risk_dist: float, klass: str) -> None:
        pos = {
            "symbol": symbol, "side": side, "entry": entry, "stop": stop, "tp": tp,
            "risk_dist": risk_dist, "klass": klass, "status": "open",
            "partial_done": False, "partial_pnl": 0.0,
            "ts_open": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._pending[symbol] = pos
        with PAPER_PATH.open("a") as f:
            f.write(json.dumps({**pos, "event": "open"}) + "\n")
        log.info("[PAPER] OPEN %s %s @ %.5f  SL=%.5f  TP=%.5f  risk=%.5f",
                 side, symbol, entry, stop, tp, risk_dist)
        _tg(f"[PAPER] Iconic Scalp {klass}-class {side} {symbol} @ {entry:.5f}  "
            f"SL={stop:.5f}  TP={tp:.5f}")

    def tick_paper(self, symbol: str, high: float, low: float) -> None:
        if symbol not in self._pending:
            return
        pos = self._pending[symbol]
        side      = pos["side"]
        entry     = pos["entry"]
        stop      = pos["stop"]
        tp        = pos["tp"]
        risk_dist = pos["risk_dist"]

        if not pos["partial_done"]:
            hit_1r = (high >= entry + risk_dist) if side == "BUY" \
                     else (low  <= entry - risk_dist)
            if hit_1r:
                pos["partial_done"] = True
                pos["partial_pnl"]  = risk_dist
                pos["stop"]         = entry
                log.info("[PAPER] PARTIAL: %s %s 1R hit → stop → BE %.5f",
                         side, symbol, entry)
                _tg(f"[PAPER] Scalp {side} {symbol} partial exit at 1R — stop → BE {entry:.5f}")
                with PAPER_PATH.open("a") as f:
                    f.write(json.dumps({"event": "partial", "symbol": symbol,
                                        "price": entry + risk_dist if side == "BUY"
                                                  else entry - risk_dist,
                                        "ts": datetime.now(timezone.utc).isoformat(
                                            timespec="seconds")}) + "\n")
                stop = entry

        hit_sl = (low  <= stop) if side == "BUY" else (high >= stop)
        hit_tp = (high >= tp)   if side == "BUY" else (low  <= tp)

        if hit_sl or hit_tp:
            exit_price  = stop if hit_sl else tp
            raw_pnl     = (exit_price - entry) if side == "BUY" else (entry - exit_price)
            partial_pnl = pos.get("partial_pnl", 0.0)
            full_pnl    = (0.5 * partial_pnl + 0.5 * raw_pnl) if partial_pnl else raw_pnl
            exit_tag    = "TP" if hit_tp else ("BE_SL" if (hit_sl and pos["partial_done"])
                                                else "SL")
            pos.update({
                "status": "closed", "exit": exit_tag,
                "exit_price": exit_price, "pnl": round(full_pnl, 8),
                "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            self._record_close(pos)
            del self._pending[symbol]
            with PAPER_PATH.open("a") as f:
                f.write(json.dumps(pos) + "\n")
            icon = "+" if full_pnl > 0 else "-"
            log.info("[PAPER] CLOSE %s %s @ %.5f  %s  PnL=%s%.5f  "
                     "[%s] PF=%.2f(%d trades)",
                     side, symbol, exit_price, exit_tag, icon, abs(full_pnl),
                     symbol, self.pf_sym(symbol), self.count_sym(symbol))
            _tg(f"[PAPER] Scalp {exit_tag} {side} {symbol} @ {exit_price:.5f}  "
                f"PnL={icon}{abs(full_pnl):.5f}  PF[{symbol}]={self.pf_sym(symbol):.2f}")
            if self.ready_sym(symbol):
                log.info("[PAPER] *** %s GATE PASSED: PF=%.2f trades=%d → PROMOTE TO LIVE ***",
                         symbol, self.pf_sym(symbol), self.count_sym(symbol))
                _tg(f"Iconic Scalp {symbol} GATE PASSED — "
                    f"PF={self.pf_sym(symbol):.2f} ({self.count_sym(symbol)} trades). "
                    f"Promoting to LIVE.", level="WARNING")

    def force_close(self, symbol: str, exit_price: float, reason: str) -> None:
        if symbol not in self._pending:
            return
        pos = self._pending[symbol]
        side, entry = pos["side"], pos["entry"]
        raw_pnl     = (exit_price - entry) if side == "BUY" else (entry - exit_price)
        partial_pnl = pos.get("partial_pnl", 0.0)
        full_pnl    = (0.5 * partial_pnl + 0.5 * raw_pnl) if partial_pnl else raw_pnl
        pos.update({"status": "closed", "exit": reason,
                    "exit_price": exit_price, "pnl": round(full_pnl, 8),
                    "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self._record_close(pos)
        del self._pending[symbol]
        with PAPER_PATH.open("a") as f:
            f.write(json.dumps(pos) + "\n")
        icon = "+" if full_pnl > 0 else "-"
        log.info("[PAPER] FORCE-CLOSE %s %s @ %.5f  %s  PnL=%s%.5f",
                 side, symbol, exit_price, reason, icon, abs(full_pnl))


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
        log.error("MetaTrader5 not installed — paper-trade only")
        return False


def _fetch_bars(symbol: str, tf, n: int) -> pd.DataFrame:
    import MetaTrader5 as mt5
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) < 50:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["ema200"] = df["close"].ewm(alpha=1 / 200, adjust=False).mean()
    if "tick_volume" not in df.columns and "real_volume" in df.columns:
        df["tick_volume"] = df["real_volume"]
    elif "tick_volume" not in df.columns:
        df["tick_volume"] = 0.0
    return df


def _has_open_position(symbol: str) -> bool:
    import MetaTrader5 as mt5
    pos = mt5.positions_get(symbol=symbol)
    return pos is not None and any(p.magic == MAGIC for p in pos)


def _get_position(symbol: str):
    import MetaTrader5 as mt5
    pos = mt5.positions_get(symbol=symbol)
    if pos:
        matches = [p for p in pos if p.magic == MAGIC]
        return matches[0] if matches else None
    return None


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


_INVALID_FILL = 10030


def _place_order(symbol: str, side: str, entry: float, stop: float, tp: float,
                 risk_pct: float) -> Optional[tuple[int, float]]:
    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick(symbol)
    sym  = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    digits     = sym.digits
    live_entry = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    sl_dist = abs(live_entry - stop)
    if sl_dist < sym.point * 5:
        log.warning("%s: SL too tight (%.6f), skip", symbol, sl_dist)
        return None

    lots = _calc_lots(symbol, live_entry, stop, risk_pct)
    if lots <= 0:
        log.warning("%s: lot=0, skip", symbol)
        return None

    fm = int(getattr(sym, "filling_mode", 0) or 0)
    if fm & 1:   fill_order = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2: fill_order = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:        fill_order = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]

    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume": lots, "type": order_type, "price": live_entry,
        "sl": round(stop, digits), "tp": round(tp, digits),
        "deviation": 10, "magic": MAGIC, "comment": "Iconic_Scalp",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": fill_order[0],
    }
    res = mt5.order_send(req)
    fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and fi < len(fill_order):
        req["type_filling"] = fill_order[fi]; fi += 1
        res = mt5.order_send(req)

    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER PLACED: %s %s %s @ %.5f  SL=%.5f  TP=%.5f  lots=%.2f",
                 side, symbol, res.order, live_entry, stop, tp, lots)
        _tg(f"Iconic Scalp {side} {symbol} @ {live_entry:.5f}  SL={stop:.5f}  "
            f"TP={tp:.5f}  lots={lots}")
        return int(res.order), lots
    code = res.retcode if res else "None"
    log.error("%s: order FAILED retcode=%s", symbol, code)
    return None


def _partial_close(symbol: str, close_lots: float, side: str) -> bool:
    """Close partial position at market (50% at 1R)."""
    import MetaTrader5 as mt5
    pos = _get_position(symbol)
    if pos is None:
        return False
    tick = mt5.symbol_info_tick(symbol)
    sym  = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return False
    close_type  = mt5.ORDER_TYPE_SELL if side == "BUY" else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if side == "BUY" else tick.ask
    close_lots  = round(max(sym.volume_min,
                            round(close_lots / sym.volume_step) * sym.volume_step), 2)
    req = {
        "action":   mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume":   close_lots, "type": close_type, "price": close_price,
        "position": pos.ticket, "deviation": 10, "magic": MAGIC,
        "comment":  "Iconic_Scalp_Partial",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("PARTIAL CLOSE: %s %.2f lots @ %.5f", symbol, close_lots, close_price)
        return True
    log.warning("Partial close failed: %s retcode=%s", symbol,
                res.retcode if res else "None")
    return False


def _modify_sl(symbol: str, new_sl: float) -> bool:
    """Move stop-loss to breakeven after partial close."""
    import MetaTrader5 as mt5
    pos = _get_position(symbol)
    if pos is None:
        return False
    sym = mt5.symbol_info(symbol)
    if sym is None:
        return False
    req = {
        "action": mt5.TRADE_ACTION_SLTP, "symbol": symbol,
        "position": pos.ticket,
        "sl": round(new_sl, sym.digits),
        "tp": pos.tp,
    }
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("SL MODIFIED: %s → %.5f (breakeven)", symbol, new_sl)
        return True
    log.warning("SL modify failed: %s retcode=%s", symbol,
                res.retcode if res else "None")
    return False


# ── Currency strength ─────────────────────────────────────────────────────────
def _currency_strength(align_map: dict) -> dict:
    raw: dict = {}
    for sym, align in align_map.items():
        s = sym.upper().replace("/", "")
        if len(s) == 6 and s.isalpha():
            base, quote = s[:3], s[3:]
        else:
            continue
        b, q = (1, -1) if align == "bull" else ((-1, 1) if align == "bear" else (0, 0))
        raw.setdefault(base, []).append(b)
        raw.setdefault(quote, []).append(q)
    return {c: round((sum(v) / len(v) + 1) * 5, 1) for c, v in raw.items() if v}


# ── State writer ──────────────────────────────────────────────────────────────
def _write_state(mode: str, daily: DailyState, paper: ScalpPaperTracker,
                 sym_live: dict, symbols: list, equity: float) -> None:
    sym_stats = {
        sym: {
            "paper_trades": paper.count_sym(sym),
            "paper_pf":     paper.pf_sym(sym),
            "paper_wr":     paper.wr_sym(sym),
            "live":         sym_live.get(sym, False),
        }
        for sym in symbols
    }
    try:
        STATE_PATH.write_text(json.dumps({
            "mode":           mode,
            "live_mode":      any(sym_live.values()) if sym_live else False,
            "sym_live":       sym_live,
            "sym_stats":      sym_stats,
            "paper_trades":   paper.trade_count,
            "paper_pf":       paper.profit_factor,
            "paper_pending":  [
                {k: v for k, v in pos.items() if k != "event"}
                for pos in paper._pending.values()
            ],
            "equity":         round(equity, 2),
            "daily_loss_pct": round(daily.daily_loss_pct(equity), 2),
            "trades_today":   daily.trades,
            "updated_at":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2))
    except Exception:
        pass


# ── Live partial exit monitor ─────────────────────────────────────────────────
_partial_done: dict[str, bool] = {}   # symbol → True if partial already done


def _check_live_partial(symbol: str, entry: float, stop: float,
                        side: str, lots: float) -> None:
    """Check if live position hit 1R and handle partial close + BE stop."""
    import MetaTrader5 as mt5
    if _partial_done.get(symbol):
        return
    pos = _get_position(symbol)
    if pos is None:
        return
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return
    risk_dist = abs(entry - stop)
    current   = tick.ask if side == "BUY" else tick.bid
    hit_1r    = (current >= entry + risk_dist) if side == "BUY" \
                else (current <= entry - risk_dist)
    if hit_1r:
        close_lots = round(lots * 0.5, 2)
        if _partial_close(symbol, close_lots, side):
            _partial_done[symbol] = True
            _modify_sl(symbol, entry)
            _tg(f"Iconic Scalp {side} {symbol} PARTIAL EXIT at 1R — "
                f"closed {close_lots} lots, stop → BE {entry:.5f}", level="INFO")


# ── Main loop ─────────────────────────────────────────────────────────────────
def run(symbols: list[str], risk_pct: float, dd_limit: float,
        force_paper: bool) -> None:
    import MetaTrader5 as mt5

    log.info("=== Iconic Scalp Agent starting (3-tier) ===")
    log.info("Tier1=%s  Tier2=%s | risk=%.1f%%  DD=%.1f%%  force_paper=%s",
             TIER1_SYMBOLS, TIER2_SYMBOLS, risk_pct, dd_limit, force_paper)

    if not _mt5_connect():
        log.error("Cannot connect to MT5 — aborting")
        sys.exit(1)

    acc   = mt5.account_info()
    daily = DailyState.load(acc.balance)
    paper = ScalpPaperTracker(force_paper=force_paper)

    # Per-symbol live status; each symbol promotes independently
    sym_live: dict[str, bool] = {sym: paper.ready_sym(sym) for sym in symbols}
    for sym in symbols:
        status = "LIVE (gate passed from prior session)" if sym_live[sym] \
                 else f"PAPER ({paper.count_sym(sym)} trades, PF={paper.pf_sym(sym):.2f})"
        log.info("  %s: %s", sym, status)

    from trading_agents.iconic.engine_scalp import IconicScalpEngine, SCALP_SETUP_TF
    engine = IconicScalpEngine()

    _live_positions: dict[str, dict] = {}
    _last_m15_bar:   dict[str, int]  = {}

    _tg(f"Iconic Scalp Agent started — {len(symbols)} symbols | "
        f"paper={paper.trade_count} total closed")

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

            dd_pct = daily.daily_loss_pct(equity)
            if dd_pct >= dd_limit:
                log.warning("Daily DD %.1f%% >= limit — HALTED", dd_pct)
                _tg(f"Iconic Scalp HALTED — daily DD {dd_pct:.1f}%", level="WARNING")
                _write_state("HALTED", daily, paper, sym_live, symbols, equity)
                time.sleep(300)
                continue

            # Check per-symbol promotion gate
            for sym in symbols:
                if not sym_live.get(sym) and paper.ready_sym(sym):
                    sym_live[sym] = True
                    log.info("PROMOTED %s TO LIVE (PF=%.2f, %d trades)",
                             sym, paper.pf_sym(sym), paper.count_sym(sym))

            now = datetime.now(timezone.utc)

            # Monitor live positions + paper tick
            for sym in symbols:
                tick = mt5.symbol_info_tick(sym)
                if tick is None:
                    continue
                high_approx = max(tick.ask, tick.bid)
                low_approx  = min(tick.ask, tick.bid)

                if sym_live.get(sym) and sym in _live_positions:
                    lp = _live_positions[sym]
                    _check_live_partial(sym, lp["entry"], lp["stop"],
                                        lp["side"], lp["lots"])
                    if not _has_open_position(sym):
                        del _live_positions[sym]
                        _partial_done.pop(sym, None)
                        log.info("Live position %s closed (TP/SL)", sym)

                paper.tick_paper(sym, high_approx, low_approx)

            # New M15 bar scan
            snapshots: dict = {}
            align_map: dict = {}

            for sym in symbols:
                m15 = _fetch_bars(sym, mt5.TIMEFRAME_M15, BARS_M15)
                if len(m15) < 250:
                    continue
                h1 = _fetch_bars(sym, mt5.TIMEFRAME_H1, BARS_H1)
                if len(h1) < 200:
                    h1 = m15

                last_t = int(m15.iloc[-2]["time"]) if "time" in m15.columns else 0
                if _last_m15_bar.get(sym) == last_t:
                    continue
                _last_m15_bar[sym] = last_t

                close = float(m15.iloc[-2]["close"])
                ema   = float(m15.iloc[-2]["ema200"])
                align = "bull" if close > ema else ("bear" if close < ema else "none")
                align_map[sym] = align

                if len(h1) >= 200:
                    h1_close = float(h1.iloc[-2]["close"])
                    h1_ema   = float(h1.iloc[-2]["ema200"])
                    h1_align = "bull" if h1_close > h1_ema \
                               else ("bear" if h1_close < h1_ema else "none")
                    if h1_align != "none":
                        align = h1_align

                snapshots[sym] = {
                    "align": align,
                    "tfs": {
                        SCALP_SETUP_TF: m15.iloc[:-1],
                        "M3": m15.iloc[:-1],
                        "H1": h1.iloc[:-1],
                    },
                }

            if not snapshots:
                _write_state("SCANNING", daily, paper, sym_live, symbols, equity)
                time.sleep(POLL_INTERVAL_S)
                continue

            strength = _currency_strength(align_map)

            try:
                signals = engine.evaluate(snapshots, strength, now=now)
            except Exception:
                log.exception("engine.evaluate failed")
                signals = []

            for sig in signals:
                sym = sig.symbol

                if _has_open_position(sym) or sym in paper._pending:
                    log.debug("%s: position already open — skip", sym)
                    continue

                if daily.trades_today(sym) >= MAX_TRADES_PER_DAY:
                    log.debug("%s: daily limit reached", sym)
                    continue

                mode_label = "LIVE" if sym_live.get(sym) else "PAPER"
                log.info("SIGNAL [%s]: %s %s class=%s score=%.0f  "
                         "entry=%.5f  SL=%.5f  TP=%.5f  RR=%.1f",
                         mode_label, sig.side, sym, sig.klass, sig.score,
                         sig.entry, sig.stop, sig.tp_final, sig.rr_final)
                for r in sig.reasons:
                    log.debug("  %s", r)

                if sym_live.get(sym):
                    result = _place_order(sym, sig.side, sig.entry, sig.stop,
                                          sig.tp_final, risk_pct)
                    if result is not None:
                        ticket, lots = result
                        _live_positions[sym] = {
                            "entry": sig.entry, "stop": sig.stop,
                            "side": sig.side, "lots": lots, "ticket": ticket,
                        }
                        _partial_done[sym] = False
                        daily.add_trade(sym)
                        if _JOURNAL:
                            _journal_open(
                                ticket=ticket, symbol=sym,
                                direction=sig.side, entry_price=sig.entry,
                                sl=sig.stop, tp=sig.tp_final, volume=lots,
                                source="IconicScalp",
                                strategies=["IconicScalp", sig.klass],
                                agent="Iconic.Scalp",
                                confluence_score=sig.score,
                                rationale=(f"class={sig.klass} RR={sig.rr_final:.1f} "
                                           f"score={sig.score:.0f}"),
                            )
                else:
                    paper.open_paper(sym, sig.side, sig.entry, sig.stop,
                                     sig.tp_final, sig.risk, sig.klass)
                    daily.add_trade(sym)

            # Align-flip exit on paper positions
            for sym in list(paper._pending.keys()):
                if sym in align_map:
                    pos_side  = paper._pending[sym]["side"]
                    cur_align = align_map[sym]
                    if (pos_side == "BUY" and cur_align == "bear") or \
                       (pos_side == "SELL" and cur_align == "bull"):
                        tick = mt5.symbol_info_tick(sym)
                        if tick:
                            ep = tick.bid if pos_side == "BUY" else tick.ask
                            paper.force_close(sym, ep, "ALIGN_FLIP")

            _write_state("SCANNING", daily, paper, sym_live, symbols, equity)
            time.sleep(POLL_INTERVAL_S)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            break
        except Exception:
            log.exception("Scalp agent loop error — sleeping 30s")
            time.sleep(30)

    acc2 = mt5.account_info()
    _write_state("STOPPED", daily, paper, sym_live, symbols, acc2.equity if acc2 else 0.0)
    mt5.shutdown()
    log.info("=== Iconic Scalp Agent stopped ===")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Iconic Scalp Agent — 3-tier wide scan")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--risk",    type=float, default=1.0)
    parser.add_argument("--dd",      type=float, default=6.0)
    parser.add_argument("--paper",   action="store_true")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    run(args.symbols, args.risk, args.dd, args.paper)


if __name__ == "__main__":
    main()
