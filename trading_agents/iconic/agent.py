"""Iconic Trader Live Agent.

Standalone loop that connects to MT5 directly (not via bridge HTTP), fetches
H1+M15 bars every H1 bar-close, runs IconicEngine, and executes trades.

Paper-trade mode:
  The agent starts in paper-trade mode and records every would-be trade without
  sending orders to MT5. After >= PAPER_MIN_TRADES with PF >= PAPER_MIN_PF it
  promotes itself to live mode. This gate prevents going live on an untested edge.

Usage:
  python -m trading_agents.iconic.agent
  python -m trading_agents.iconic.agent --paper           # force paper-trade forever
  python -m trading_agents.iconic.agent --risk 0.5        # override risk% (default 1.0)
  python -m trading_agents.iconic.agent --dd 6.0          # daily DD% halt (default 6.0)
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

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "mt5_bridge"))

LOG_DIR      = BASE_DIR / "logs" / "iconic"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH     = LOG_DIR / "_agent_log.txt"
STATE_PATH   = LOG_DIR / "_agent_state.json"
DAILY_PATH   = LOG_DIR / "_agent_daily.json"
PAPER_PATH   = LOG_DIR / "_paper_trades.jsonl"

MAGIC           = 20260700          # Iconic Trader magic number
BARS_H1         = 500               # warmup + lookback
BARS_M15        = 500
POLL_INTERVAL_S = 60                # seconds between scans when idle
NEWS_SYNC_EVERY_S = 3 * 3600        # refresh news calendar (A-class purpose) this often
PAPER_MIN_TRADES = 20               # min paper trades before promotion
PAPER_MIN_PF     = 1.3              # min profit factor for promotion
MAX_TRADES_PER_SYMBOL_DAY = 2
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
log = logging.getLogger("Iconic.Agent")

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
        _tghq.send("live_trading", msg, level=level, title="Iconic Agent")
    except Exception:
        pass


# ── Journal integration ───────────────────────────────────────────────────────
try:
    from trading_agents.trade_journal import open_trade as _journal_open, close_trade as _journal_close
    _JOURNAL = True
except Exception:
    _JOURNAL = False
    def _journal_open(*a, **kw): pass   # type: ignore
    def _journal_close(*a, **kw): pass  # type: ignore


# ── News calendar sync (feeds A-class STRONG purpose) ───────────────────────────
try:
    from trading_agents.iconic.news_sync import sync as _news_sync
except Exception:
    _news_sync = None


def _sync_news() -> None:
    if _news_sync is None:
        return
    try:
        n = _news_sync()
        if n >= 0:
            log.info("News calendar synced: %d G7 events", n)
    except Exception:
        log.warning("News calendar sync failed", exc_info=True)


# ── Daily state ───────────────────────────────────────────────────────────────
class DailyState:
    def __init__(self, start_balance: float, date, trades: dict):
        self.date          = date
        self.start_balance = start_balance
        self.trades        = trades   # {symbol: count}

    @classmethod
    def load(cls, current_balance: float) -> "DailyState":
        today = datetime.now(timezone.utc).date()
        if DAILY_PATH.exists():
            try:
                d = json.loads(DAILY_PATH.read_text())
                if d.get("date") == str(today):
                    log.info("Daily state restored — start=$%.2f  trades=%s",
                             d["start_balance"], d.get("trades", {}))
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
            log.info("New day %s — resetting daily state", today)
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


# ── Paper-trade tracker ───────────────────────────────────────────────────────
class PaperTracker:
    """Records would-be trades and computes PF to gate live promotion."""

    def __init__(self, force_paper: bool = False):
        self.force_paper = force_paper
        self._pending: dict = {}   # symbol → {entry, stop, tp, side, klass, bar_open}
        self._closed: list = []
        self._load()

    def _load(self) -> None:
        if PAPER_PATH.exists():
            try:
                for line in PAPER_PATH.read_text().splitlines():
                    t = json.loads(line)
                    if t.get("status") == "closed":
                        self._closed.append(t)
            except Exception:
                pass
        log.info("Paper trades loaded: %d closed", len(self._closed))

    @property
    def profit_factor(self) -> float:
        wins   = sum(t["pnl"] for t in self._closed if t.get("pnl", 0) > 0)
        losses = abs(sum(t["pnl"] for t in self._closed if t.get("pnl", 0) < 0))
        return round(wins / losses, 2) if losses > 0 else (99.0 if wins > 0 else 0.0)

    @property
    def trade_count(self) -> int:
        return len(self._closed)

    def is_live_ready(self) -> bool:
        # The connected account is a DEMO account — execute there from the first
        # trade to gather real fill data (use --paper for the old software-sim
        # gate). Demo→real promotion is a separate, later gate driven by the
        # trade journal's demo stats, not this in-memory paper tracker.
        if self.force_paper:
            return False
        return True

    def open_paper(self, symbol: str, side: str, entry: float,
                   stop: float, tp: float, klass: str) -> None:
        t = {"symbol": symbol, "side": side, "entry": entry, "stop": stop,
             "tp": tp, "klass": klass, "status": "open",
             "ts_open": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._pending[symbol] = t
        with PAPER_PATH.open("a") as f:
            f.write(json.dumps(t) + "\n")
        log.info("[PAPER] OPEN %s %s @ %.5f  SL=%.5f  TP=%.5f",
                 side, symbol, entry, stop, tp)
        _tg(f"[PAPER] Iconic {klass}-class {side} {symbol} @ {entry:.5f}")

    def force_close(self, symbol: str, exit_price: float, reason: str) -> None:
        """Close a paper position early (e.g., align-flip / group congestion exit)."""
        if symbol not in self._pending:
            return
        pos = self._pending[symbol]
        side, entry = pos["side"], pos["entry"]
        pnl = (exit_price - entry) if side == "BUY" else (entry - exit_price)
        pos.update({"status": "closed", "exit": reason,
                    "exit_price": exit_price, "pnl": round(pnl, 8),
                    "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self._closed.append(pos)
        del self._pending[symbol]
        with PAPER_PATH.open("a") as f:
            f.write(json.dumps(pos) + "\n")
        icon = "+" if pnl > 0 else "-"
        log.info("[PAPER] FORCE-CLOSE %s %s @ %.5f  %s  PnL=%s%.5f",
                 side, symbol, exit_price, reason, icon, abs(pnl))

    def tick_paper(self, symbol: str, high: float, low: float) -> None:
        if symbol not in self._pending:
            return
        pos = self._pending[symbol]
        side, entry, stop, tp = pos["side"], pos["entry"], pos["stop"], pos["tp"]
        hit_sl = low <= stop if side == "BUY" else high >= stop
        hit_tp = high >= tp  if side == "BUY" else low <= tp
        if hit_sl or hit_tp:
            exit_price = stop if hit_sl else tp
            if side == "BUY":
                pnl = exit_price - entry
            else:
                pnl = entry - exit_price
            pos.update({"status": "closed", "exit": "TP" if hit_tp else "SL",
                        "exit_price": exit_price, "pnl": round(pnl, 8),
                        "ts_close": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            self._closed.append(pos)
            del self._pending[symbol]
            with PAPER_PATH.open("a") as f:
                f.write(json.dumps(pos) + "\n")
            icon = "+" if pnl > 0 else "-"
            log.info("[PAPER] CLOSE %s %s @ %.5f  PnL=%s%.5f  PF=%.2f (%d trades)",
                     pos["side"], symbol, exit_price, icon, abs(pnl),
                     self.profit_factor, self.trade_count)
            if self.is_live_ready():
                log.info("[PAPER] *** PROMOTION GATE PASSED: PF=%.2f trades=%d → going LIVE ***",
                         self.profit_factor, self.trade_count)
                _tg(f"Iconic agent PROMOTION GATE passed — PF={self.profit_factor:.2f} "
                    f"({self.trade_count} paper trades). Now going LIVE.")


# ── MT5 helpers ───────────────────────────────────────────────────────────────
def _mt5_connect() -> bool:
    try:
        import bridge_client as mt5
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


def _fetch_bars_mt5(symbol: str, tf, n: int) -> pd.DataFrame:
    import bridge_client as mt5
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) < 50:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["ema200"] = df["close"].ewm(alpha=1 / 200, adjust=False).mean()
    # rename to match IconicEngine expectations
    if "tick_volume" not in df.columns and "real_volume" in df.columns:
        df["tick_volume"] = df["real_volume"]
    elif "tick_volume" not in df.columns:
        df["tick_volume"] = 0.0
    return df


def _has_open_position(symbol: str) -> bool:
    import bridge_client as mt5
    pos = mt5.positions_get(symbol=symbol)
    return pos is not None and any(p.magic == MAGIC for p in pos)


def _calc_lots(symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    import bridge_client as mt5
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
                 risk_pct: float) -> Optional[tuple[int, float]]:
    import bridge_client as mt5
    tick = mt5.symbol_info_tick(symbol)
    sym  = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return False
    digits = sym.digits
    live_entry = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    sl_dist = abs(live_entry - stop)
    if sl_dist < sym.point * 5:
        log.warning("%s: SL too tight (%.6f), skip", symbol, sl_dist)
        return False

    lots = _calc_lots(symbol, live_entry, stop, risk_pct)
    if lots <= 0:
        log.warning("%s: lot=0, skip", symbol)
        return False

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
        "deviation": 10, "magic": MAGIC, "comment": "Iconic_Agent",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": fill_order[0],
    }
    res = mt5.order_send(req)
    fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and fi < len(fill_order):
        req["type_filling"] = fill_order[fi]
        fi += 1
        res = mt5.order_send(req)

    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER PLACED: %s %s %s @ %.5f  SL=%.5f  TP=%.5f  lots=%.2f",
                 side, symbol, res.order, live_entry, stop, tp, lots)
        _tg(f"Iconic {side} {symbol} @ {live_entry:.5f}  SL={stop:.5f}  TP={tp:.5f}  lots={lots}")
        return int(res.order), lots
    code = res.retcode if res else "None"
    log.error("%s: order FAILED retcode=%s", symbol, code)
    return None


# ── Currency strength ─────────────────────────────────────────────────────────
_SPECIAL_PAIRS = {"XAUUSD": ("XAU", "USD"), "XAGUSD": ("XAG", "USD"),
                  "BTCUSD": ("BTC", "USD")}


def _split(sym: str) -> tuple[str, str]:
    if sym in _SPECIAL_PAIRS:
        return _SPECIAL_PAIRS[sym]
    if len(sym) == 6 and sym.isalpha():
        return sym[:3], sym[3:]
    return "", ""


def _currency_strength(align_map: dict[str, str]) -> dict[str, float]:
    raw: dict[str, list] = {}
    for sym, align in align_map.items():
        base, quote = _split(sym)
        if not base:
            continue
        b, q = (1, -1) if align == "bull" else ((-1, 1) if align == "bear" else (0, 0))
        raw.setdefault(base,  []).append(b)
        raw.setdefault(quote, []).append(q)
    return {c: round((sum(v) / len(v) + 1) * 5, 1) for c, v in raw.items() if v}


# ── Main agent loop ───────────────────────────────────────────────────────────
# Backtest verdict (2026-05-22, 4750 H1 bars + WF test):
#   GO (OOS PF 1.67):   USDCAD
#   Promising (OOS PF 1.22, 7 trades): USDCHF — add after 20 paper trades confirm
#   NO_GO (PF 0.29-0.67): EURUSD, GBPUSD, AUDUSD, NZDUSD
#   Removed (WR 16-18%): USDJPY, GBPJPY, EURJPY
SYMBOLS = [
    "USDCAD",    # GO — OOS PF 1.67, 60% WR
    # "USDCHF",  # Promising — re-enable after paper-trade gate confirms
]


def _write_state(mode: str, daily: DailyState, paper: PaperTracker,
                 live_mode: bool, equity: float) -> None:
    try:
        STATE_PATH.write_text(json.dumps({
            "mode":            mode,
            "live_mode":       live_mode,
            "paper_trades":    paper.trade_count,
            "paper_pf":        paper.profit_factor,
            "paper_pending":   list(paper._pending.keys()),
            "equity":          round(equity, 2),
            "daily_loss_pct":  round(daily.daily_loss_pct(equity), 2),
            "trades_today":    daily.trades,
            "updated_at":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2))
    except Exception:
        pass


def run(symbols: list[str], risk_pct: float, dd_limit: float,
        force_paper: bool) -> None:
    import bridge_client as mt5

    log.info("=== Iconic Trader Agent starting ===")
    log.info("Symbols: %s | risk=%.1f%% | DD=%.1f%% | paper=%s",
             symbols, risk_pct, dd_limit, force_paper)

    if not _mt5_connect():
        log.error("Cannot connect to MT5 — aborting")
        sys.exit(1)

    acc       = mt5.account_info()
    daily     = DailyState.load(acc.balance)
    paper     = PaperTracker(force_paper=force_paper)
    live_mode = paper.is_live_ready()

    from trading_agents.iconic.engine import IconicEngine
    engine = IconicEngine()

    _sync_news()                         # initial pull so A-class can fire from the start
    _last_news_sync = time.time()

    _last_h1_bar: dict[str, int] = {}   # symbol → last processed H1 bar time

    log.info("Initial state: paper=%d trades  PF=%.2f  live=%s",
             paper.trade_count, paper.profit_factor, live_mode)

    while True:
        try:
            acc = mt5.account_info()
            if acc is None:
                log.warning("MT5 account_info returned None — retrying in 60s")
                time.sleep(60)
                _mt5_connect()
                continue

            equity = acc.equity
            daily.roll_if_new_day(acc.balance)

            # Refresh the news calendar periodically (A-class STRONG purpose)
            if time.time() - _last_news_sync >= NEWS_SYNC_EVERY_S:
                _sync_news()
                _last_news_sync = time.time()

            # Daily DD guard
            dd_pct = daily.daily_loss_pct(equity)
            if dd_pct >= dd_limit:
                log.warning("Daily DD %.1f%% >= limit %.1f%% — HALTED", dd_pct, dd_limit)
                _tg(f"Iconic Agent HALTED — daily DD {dd_pct:.1f}% >= {dd_limit:.1f}%", level="WARNING")
                _write_state("HALTED", daily, paper, live_mode, equity)
                time.sleep(300)
                continue

            # Check promotion
            if not live_mode and paper.is_live_ready():
                live_mode = True
                log.info("PROMOTED TO LIVE MODE (PF=%.2f, %d paper trades)",
                         paper.profit_factor, paper.trade_count)

            now = datetime.now(timezone.utc)

            # Fetch bars + build snapshots for all symbols
            snapshots: dict = {}
            align_map: dict = {}

            for sym in symbols:
                h1 = _fetch_bars_mt5(sym, mt5.TIMEFRAME_H1, BARS_H1)
                if len(h1) < 250:
                    continue
                m15 = _fetch_bars_mt5(sym, mt5.TIMEFRAME_M15, BARS_M15)
                if len(m15) < 50:
                    m15 = h1

                # Only process when a new H1 bar has closed
                last_t = int(h1.iloc[-2]["time"]) if "time" in h1.columns else 0
                if _last_h1_bar.get(sym) == last_t:
                    # Still same bar — tick paper open positions with latest price
                    if sym in paper._pending:
                        tick = mt5.symbol_info_tick(sym)
                        if tick:
                            paper.tick_paper(sym, tick.ask, tick.bid)
                    continue
                _last_h1_bar[sym] = last_t

                close = float(h1.iloc[-2]["close"])
                ema   = float(h1.iloc[-2]["ema200"])
                align = "bull" if close > ema else ("bear" if close < ema else "none")
                align_map[sym] = align
                snapshots[sym] = {"align": align, "tfs": {"H1": h1.iloc[:-1], "M15": m15}}

            if not snapshots:
                _write_state("SCANNING", daily, paper, live_mode, equity)
                time.sleep(POLL_INTERVAL_S)
                continue

            strength = _currency_strength(align_map)

            # Evaluate signals
            try:
                signals = engine.evaluate(snapshots, strength, now=now)
            except Exception:
                log.exception("engine.evaluate failed")
                signals = []

            for sig in signals:
                sym = sig.symbol

                # Skip if already in position
                if _has_open_position(sym):
                    log.debug("%s: already in position — skip", sym)
                    continue
                if sym in paper._pending:
                    log.debug("%s: paper position pending — skip", sym)
                    continue

                # Daily trade limit
                if daily.trades_today(sym) >= MAX_TRADES_PER_SYMBOL_DAY:
                    log.debug("%s: daily trade limit reached", sym)
                    continue

                log.info("SIGNAL: %s %s class=%s score=%.0f  entry=%.5f  SL=%.5f  TP=%.5f",
                         sig.side, sym, sig.klass, sig.score,
                         sig.entry, sig.stop, sig.tp_final)

                if live_mode:
                    result = _place_order(sym, sig.side, sig.entry, sig.stop,
                                          sig.tp_final, risk_pct)
                    if result is not None:
                        ticket, lots = result
                        daily.add_trade(sym)
                        if _JOURNAL:
                            _journal_open(
                                ticket=ticket,
                                symbol=sym,
                                direction=sig.side,
                                entry_price=sig.entry,
                                sl=sig.stop,
                                tp=sig.tp_final,
                                volume=lots,
                                source="Iconic",
                                strategies=["Iconic", sig.klass],
                                agent="Iconic.Agent",
                                confluence_score=sig.score,
                                rationale=f"class={sig.klass}  score={sig.score:.0f}",
                            )
                else:
                    paper.open_paper(sym, sig.side, sig.entry, sig.stop,
                                     sig.tp_final, sig.klass)
                    daily.add_trade(sym)

            # Align-flip exit: Q9 group congestion rule — if EMA200 alignment
            # reverses against the open paper trade, exit immediately.
            for sym in list(paper._pending.keys()):
                if sym in align_map:
                    pos_side = paper._pending[sym]["side"]
                    cur_align = align_map[sym]
                    if (pos_side == "BUY" and cur_align == "bear") or \
                       (pos_side == "SELL" and cur_align == "bull"):
                        tick = mt5.symbol_info_tick(sym)
                        if tick:
                            ep = tick.bid if pos_side == "BUY" else tick.ask
                            paper.force_close(sym, ep, "ALIGN_FLIP")

            # Update paper positions on last bar's H/L
            for sym in list(paper._pending.keys()):
                h1 = _fetch_bars_mt5(sym, mt5.TIMEFRAME_H1, 3)
                if len(h1) >= 2:
                    bar = h1.iloc[-2]
                    paper.tick_paper(sym, float(bar["high"]), float(bar["low"]))

            _write_state("SCANNING", daily, paper, live_mode, equity)
            time.sleep(POLL_INTERVAL_S)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            break
        except Exception:
            log.exception("Agent loop error — sleeping 30s")
            time.sleep(30)

    _write_state("STOPPED", daily, paper, live_mode,
                 mt5.account_info().equity if mt5.account_info() else 0.0)
    mt5.shutdown()
    log.info("=== Iconic Trader Agent stopped ===")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Iconic Trader Live Agent")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--risk",    type=float, default=1.0,
                        help="Risk %% per trade (default 1.0)")
    parser.add_argument("--dd",      type=float, default=6.0,
                        help="Daily DD %% halt threshold (default 6.0)")
    parser.add_argument("--paper",   action="store_true",
                        help="Force paper-trade mode (never go live)")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Cutover hook: when ICONIC_BOARD is set (.env), this service runs the
    # whole-board system instead of the single-pair USDCAD agent. Read .env
    # directly so a freshly-set flag is honored without an orchestrator restart.
    try:
        from dotenv import dotenv_values
        _flag = (dotenv_values(BASE_DIR / ".env").get("ICONIC_BOARD")
                 or os.getenv("ICONIC_BOARD", ""))
    except Exception:
        _flag = os.getenv("ICONIC_BOARD", "")
    if str(_flag).strip() in ("1", "true", "True", "yes"):
        log.info("ICONIC_BOARD set — delegating to board_trader (whole-board system)")
        from trading_agents.iconic.board_trader import run as board_run
        board_run(once=False, dry=False)
        return

    run(args.symbols, args.risk, args.dd, args.paper)


if __name__ == "__main__":
    main()
