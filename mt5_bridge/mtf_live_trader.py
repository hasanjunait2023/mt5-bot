# encoding: utf-8
"""
mtf_live_trader.py — 24/7 live monitor + auto-trader for MTF EMA Alignment Scalper.
Checks MTF_BEST_PAIRS at every M1 bar close, places market orders via MT5.

Usage:
    python mt5_bridge/mtf_live_trader.py
    python mt5_bridge/mtf_live_trader.py --pairs EURJPY USDJPY --risk 1.5
    python mt5_bridge/mtf_live_trader.py --news
"""
import sys, os, time, argparse, logging, json as _json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from config import (MTF_BEST_PAIRS, MTF_DEFAULT_PARAMS, MTF_DEFAULT_FILTERS,
                    MTF_SYMBOL_PARAMS, MTF_SYMBOL_FILTERS)
from mtf_strategy import (add_mtf_indicators, align_mtf_to_m1,
                           compute_mtf_signals, compute_sl_tp_arrays)

MAGIC        = 20260100
TRACKED_MAGICS = {20260100, 20260600, 20260500, 20260200}  # all bot magics
BARS_M1      = 300
BARS_M3      = 150
BARS_M15     = 100
BAR_WAIT_SEC = 3
LOG_PATH     = Path(__file__).parent / "_live_log.txt"
STATE_PATH   = Path(__file__).parent / "_live_state.json"
DAILY_PATH   = Path(__file__).parent / "_daily_persist.json"
DIV          = "=" * 64

NVIDIA_HB_INTERVAL = 1800  # check NVIDIA API every 30 minutes

try:
    from trading_agents.nvidia_model_router import heartbeat as _nvidia_heartbeat
    _NVIDIA_ENABLED = True
except Exception:
    _NVIDIA_ENABLED = False

try:
    from trading_agents.trade_journal import open_trade as _journal_open, close_trade as _journal_close
    _JOURNAL_ENABLED = True
except Exception:
    _JOURNAL_ENABLED = False
    def _journal_open(*a, **kw): pass   # type: ignore
    def _journal_close(*a, **kw): pass  # type: ignore

# ── Telegram alerts ───────────────────────────────────────────────────────────
try:
    import sys as _sys
    _ROOT = str(Path(__file__).resolve().parents[1])
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)
    from trading_agents import telegram_hq as _tghq
    _TG_ON = True
except Exception:
    _tghq = None  # type: ignore
    _TG_ON = False

def tg_alert(msg: str, level: str = "INFO"):
    if not _TG_ON or _tghq is None:
        return
    try:
        _tghq.send("live_trading", msg, level=level, title="Live Trading")
    except Exception:
        pass

def nvidia_heartbeat() -> Optional[bool]:
    """Ping NVIDIA NIM API. Returns True/False/None (if not configured)."""
    if not _NVIDIA_ENABLED:
        return None
    try:
        return _nvidia_heartbeat()
    except Exception as e:
        log.warning(f"NVIDIA heartbeat error: {e}")
        return False

# ── Logging — file only to avoid stdout filling temp buffer ──────────────────
handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
try:
    handlers.append(
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8",
                 buffering=1, closefd=False)
        )
    )
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=handlers,
)
log = logging.getLogger("MTF_Live")


# ── Daily state ───────────────────────────────────────────────────────────────

class DailyState:
    def __init__(self, start_balance: float, date, trades: Dict[str, int]):
        self.date          = date
        self.start_balance = start_balance
        self.trades        = trades

    @classmethod
    def load(cls, current_balance: float) -> "DailyState":
        """Load from disk if same UTC day; otherwise start fresh and save."""
        today = datetime.now(timezone.utc).date()
        if DAILY_PATH.exists():
            try:
                d = _json.loads(DAILY_PATH.read_text())
                if d.get("date") == str(today):
                    log.info(f"Daily state restored — start=${d['start_balance']:.2f}  trades={d.get('trades', {})}")
                    return cls(d["start_balance"], today, d.get("trades", {}))
            except Exception:
                pass
        inst = cls(current_balance, today, {})
        inst.save()
        return inst

    def save(self):
        DAILY_PATH.write_text(_json.dumps(
            {"date": str(self.date), "start_balance": self.start_balance, "trades": self.trades}
        ))

    def roll_if_new_day(self, balance: float):
        today = datetime.now(timezone.utc).date()
        if today != self.date:
            log.info(f"New day {today} — resetting daily state")
            self.date = today; self.start_balance = balance; self.trades = {}
            self.save()

    def daily_loss_pct(self, equity: float) -> float:
        if self.start_balance <= 0: return 0.0
        return max((self.start_balance - equity) / self.start_balance * 100, 0.0)

    def add_trade(self, symbol: str):
        self.trades[symbol] = self.trades.get(symbol, 0) + 1
        self.save()

    def trades_today(self, symbol: str) -> int:
        return self.trades.get(symbol, 0)


# ── MT5 helpers ───────────────────────────────────────────────────────────────

def mt5_connect() -> bool:
    if mt5.initialize():
        acc = mt5.account_info()
        if acc:
            log.info(f"Connected: #{acc.login} @ {acc.server} "
                     f"| Balance=${acc.balance:.2f} | Equity=${acc.equity:.2f}")
            return True
    log.error(f"MT5 init failed: {mt5.last_error()}")
    return False


def fetch_bars(symbol: str, tf: int, n: int) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) < 50:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    df.rename(columns={"open":"Open","high":"High","low":"Low",
                        "close":"Close","tick_volume":"Volume"}, inplace=True)
    return df


def has_open_position(symbol: str) -> bool:
    pos = mt5.positions_get(symbol=symbol)
    return pos is not None and any(p.magic == MAGIC for p in pos)


def get_open_positions() -> list:
    all_pos = mt5.positions_get()
    return [p for p in all_pos if p.magic == MAGIC] if all_pos else []


# ── Signal detection ──────────────────────────────────────────────────────────

def check_signal(symbol, p, enable, last_bar, news_events=None):
    df1  = fetch_bars(symbol, mt5.TIMEFRAME_M1,  BARS_M1)
    df3  = fetch_bars(symbol, mt5.TIMEFRAME_M3,  BARS_M3)
    df15 = fetch_bars(symbol, mt5.TIMEFRAME_M15, BARS_M15)
    if df1.empty or df3.empty or df15.empty:
        return 0, 0.0, 0.0, None

    df1  = add_mtf_indicators(df1,  p)
    df3  = add_mtf_indicators(df3,  p)
    df15 = add_mtf_indicators(df15, p)
    aligned = align_mtf_to_m1(df1, df3, df15)
    if len(aligned) < 50:
        return 0, 0.0, 0.0, None

    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        return 0, 0.0, 0.0, None
    pip_size = sym_info.point * (10 if sym_info.digits in (4, 2) else 1)

    signals  = compute_mtf_signals(aligned, p, pip_size, symbol,
                                   None, news_events, enable)
    bar_time = signals.index[-2]
    sig_val  = int(signals.iloc[-2])

    if sig_val == 0 or last_bar.get(symbol) == bar_time:
        return 0, 0.0, 0.0, bar_time

    _, sl_arr, tp_arr = compute_sl_tp_arrays(aligned, signals, p)
    sl = float(sl_arr[-2]); tp = float(tp_arr[-2])
    if np.isnan(sl) or np.isnan(tp) or sl <= 0 or tp <= 0:
        return 0, 0.0, 0.0, bar_time

    return sig_val, sl, tp, bar_time


# ── Order placement ───────────────────────────────────────────────────────────

def calc_lots(symbol, sl, entry, risk_pct):
    """
    Position sizing: risk_pct% of current EQUITY (compounds automatically).
    Lot = (Equity × risk_pct%) / (SL_distance × tick_value_per_lot)
    """
    acc  = mt5.account_info()
    sym  = mt5.symbol_info(symbol)
    if acc is None or sym is None: return 0.0
    # Use equity (not balance) so profits compound and losses reduce exposure
    risk_usd   = acc.equity * risk_pct / 100.0
    sl_dist    = abs(entry - sl)
    if sl_dist < sym.point or sym.trade_tick_size <= 0: return 0.0
    value_lot  = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0: return 0.0
    lots = risk_usd / value_lot
    lots = round(lots / sym.volume_step) * sym.volume_step
    # Hard cap: never risk more than 2% even if rounding produces higher value
    max_allowed = (acc.equity * 0.02) / value_lot if value_lot > 0 else sym.volume_max
    return round(max(sym.volume_min, min(lots, sym.volume_max, max_allowed)), 2)


def place_order(symbol, signal, sl, rr, risk_pct):
    tick = mt5.symbol_info_tick(symbol)
    sym  = mt5.symbol_info(symbol)
    if tick is None or sym is None: return False
    digits = sym.digits

    if signal == 1:
        order_type = mt5.ORDER_TYPE_BUY;  entry = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL; entry = tick.bid

    sl_dist = abs(entry - sl)
    if sl_dist < sym.point * 5:
        log.warning(f"  {symbol}: SL too tight, skip")
        return False

    tp   = entry + sl_dist * rr if signal == 1 else entry - sl_dist * rr
    lots = calc_lots(symbol, sl, entry, risk_pct)
    if lots <= 0:
        log.warning(f"  {symbol}: lot=0, skip")
        return False

    # Broker-supported filling mode. Exness rejects a hardcoded IOC on many
    # symbols (retcode 10030 = INVALID_FILL). The MetaTrader5 Python package
    # does NOT expose SYMBOL_FILLING_* constants, so read the raw symbol_info
    # bitmask directly (FOK bit = 1, IOC bit = 2) to pick the preferred
    # ORDER_FILLING_* first, then fall back through the others on rejection.
    fm = int(getattr(sym, "filling_mode", 0) or 0)
    if fm & 1:        # SYMBOL_FILLING_FOK
        fill_order = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2:      # SYMBOL_FILLING_IOC
        fill_order = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fill_order = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]

    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume": lots, "type": order_type, "price": entry,
        "sl": round(sl, digits), "tp": round(tp, digits),
        "deviation": 10, "magic": MAGIC, "comment": "MTF_Scalper",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": fill_order[0],
    }
    _INVALID_FILL = 10030  # TRADE_RETCODE_INVALID_FILL (numeric — constant not always exported)
    res = mt5.order_send(req)
    _fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and _fi < len(fill_order):
        req["type_filling"] = fill_order[_fi]
        _fi += 1
        res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        code = res.retcode if res else "None"
        log.error(f"  {symbol}: order FAILED retcode={code}")
        return False

    direction = "BUY" if signal == 1 else "SELL"
    acc = mt5.account_info()
    log.info(f"  >> {symbol}: {direction} {lots}L @ {entry:.{digits}f} "
             f"SL={sl:.{digits}f} TP={tp:.{digits}f} Equity=${acc.equity:.2f}")
    try:
        _journal_open(
            ticket=res.order, symbol=symbol, direction=direction,
            entry_price=entry, sl=round(sl, digits), tp=round(tp, digits),
            volume=lots, source="MTF_EMA", strategies=["MTF EMA Alignment"],
            agent="mtf_live_trader", backend="mt5_direct",
        )
    except Exception:
        pass
    sl_pips = abs(entry - sl) / sym.point / 10
    tp_pips = abs(tp - entry) / sym.point / 10
    risk_usd = acc.equity * (risk_pct / 100)
    tg_alert(
        f"{'🟢' if signal == 1 else '🔴'} MTF {symbol} {direction}\n"
        f"Entry: {entry:.{digits}f} | SL: {sl:.{digits}f} | TP: {tp:.{digits}f}\n"
        f"Lot: {lots} | SL: {sl_pips:.0f}p | TP: {tp_pips:.0f}p\n"
        f"Risk: ${risk_usd:.2f} | Equity: ${acc.equity:.2f}"
    )
    return True


# ── Trade journal close watcher ───────────────────────────────────────────────

def _get_tracked_positions() -> dict[int, dict]:
    """Return {ticket: {symbol, sl, tp}} for all bot-magic positions."""
    all_pos = mt5.positions_get()
    if not all_pos:
        return {}
    return {
        p.ticket: {"symbol": p.symbol, "sl": p.sl, "tp": p.tp,
                   "entry": p.price_open, "direction": "BUY" if p.type == 0 else "SELL"}
        for p in all_pos if p.magic in TRACKED_MAGICS
    }


def _detect_and_journal_closes(prev: dict[int, dict]) -> dict[int, dict]:
    """Compare prev positions vs current. Journal any that closed. Return current."""
    current = _get_tracked_positions()
    closed_tickets = set(prev) - set(current)
    for ticket in closed_tickets:
        try:
            info = prev[ticket]
            deals = mt5.history_deals_get(position=ticket)
            if not deals:
                continue
            # DEAL_ENTRY_OUT = 1
            close_deal = next((d for d in deals if d.entry == 1), None)
            if close_deal is None:
                continue
            exit_price = close_deal.price
            pnl        = close_deal.profit + close_deal.swap + close_deal.commission
            sl, tp     = info["sl"], info["tp"]
            tol        = abs(tp - info["entry"]) * 0.05  # 5% tolerance
            if tp > 0 and abs(exit_price - tp) <= tol:
                outcome = "TP_HIT"
            elif sl > 0 and abs(exit_price - sl) <= tol:
                outcome = "SL_HIT"
            else:
                outcome = "MANUAL"
            from datetime import datetime, timezone
            close_ts = datetime.fromtimestamp(close_deal.time, tz=timezone.utc).isoformat()
            _journal_close(ticket=ticket, exit_price=exit_price,
                           pnl=pnl, outcome=outcome, close_time=close_ts)
            log.info(f"  [Journal] {info['symbol']} #{ticket} closed "
                     f"{outcome} PnL=${pnl:+.2f}")
        except Exception as e:
            log.debug(f"  [Journal] close detection error #{ticket}: {e}")
    return current


# ── Timing ────────────────────────────────────────────────────────────────────

def secs_to_next_bar() -> float:
    now = datetime.now(timezone.utc)
    nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return (nxt - now).total_seconds()


# ── Status log (file only — no stdout to avoid temp buffer overflow) ──────────

def log_status(symbols, daily, initial_balance, nvidia_alive: Optional[bool] = None):
    acc = mt5.account_info()
    if acc is None: return
    daily_dd = daily.daily_loss_pct(acc.equity)
    total_dd = max((initial_balance - acc.equity) / initial_balance * 100, 0)
    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if nvidia_alive is None:
        nv_tag = "NVIDIA=n/a"
    elif nvidia_alive:
        nv_tag = "NVIDIA=alive"
    else:
        nv_tag = "NVIDIA=DEAD"

    log.info(DIV)
    log.info(f"  {now_str}  Balance=${acc.balance:.2f}  Equity=${acc.equity:.2f}  {nv_tag}")
    log.info(f"  DailyDD={daily_dd:.1f}%  TotalDD={total_dd:.1f}%")

    positions = get_open_positions()
    if positions:
        for p in positions:
            side = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            log.info(f"  OPEN {p.symbol} {side} {p.volume}L "
                     f"entry={p.price_open}  P&L=${p.profit:+.2f}")
    else:
        log.info("  No open positions")

    today = [(s, daily.trades_today(s)) for s in symbols if daily.trades_today(s) > 0]
    if today:
        log.info("  Today: " + " | ".join(f"{s}={n}" for s, n in today))
    log.info(DIV)


# ── Dashboard state writer ────────────────────────────────────────────────────

def write_live_state(symbols: list, daily: DailyState,
                     initial_balance: float, last_signals: dict,
                     nvidia_alive: Optional[bool] = None) -> None:
    """Write structured JSON snapshot for the dashboard (atomic, non-blocking)."""
    acc = mt5.account_info()
    if acc is None:
        return
    daily_pnl = acc.balance - daily.start_balance
    daily_dd  = daily.daily_loss_pct(acc.equity)
    total_dd  = max((initial_balance - acc.equity) / initial_balance * 100, 0.0)

    # All known EA magic numbers: Python live trader + MQL5 EAs
    EA_MAGICS = {
        20260100: "MTF_EMA_Scalper",
        20260516: "ScalpMaster_HFT",
        20260517: "ScalpMaster_HFT_Aggressive",
        20260002: "XAUUSD_Gold_Scalper",
        20260001: "BTCUSD_Scalper",
    }

    all_pos_raw = mt5.positions_get() or []
    positions = []
    ea_positions: dict = {name: [] for name in EA_MAGICS.values()}

    for p in all_pos_raw:
        tick = mt5.symbol_info_tick(p.symbol)
        current = (tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask) if tick else p.price_current
        pos_dict = {
            "ticket": p.ticket, "symbol": p.symbol,
            "direction": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": p.volume, "entry_price": p.price_open,
            "current_price": float(current), "sl": p.sl, "tp": p.tp,
            "swap": p.swap, "profit": p.profit,
            "open_time": int(p.time), "magic": p.magic,
            "ea_name": EA_MAGICS.get(p.magic, f"unknown_{p.magic}"),
        }
        if p.magic == MAGIC:
            positions.append(pos_dict)
        ea_name = EA_MAGICS.get(p.magic)
        if ea_name:
            ea_positions[ea_name].append(pos_dict)

    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trader_running": True, "mt5_connected": True,
        "nvidia_api_alive": nvidia_alive,
        "account": {
            "login": acc.login, "server": acc.server,
            "balance": acc.balance, "equity": acc.equity,
            "margin": acc.margin, "free_margin": acc.margin_free,
            "daily_pnl": round(daily_pnl, 2),
            "daily_dd_pct": round(daily_dd, 2),
            "total_dd_pct": round(total_dd, 2),
            "start_balance": daily.start_balance,
        },
        "positions": positions,
        "ea_positions": ea_positions,
        "daily_trades": dict(daily.trades),
        "last_signals": last_signals,
        "symbols": symbols,
    }
    tmp = STATE_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(_json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except Exception as e:
        log.debug(f"state write error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs",  nargs="+", default=MTF_BEST_PAIRS)
    parser.add_argument("--risk",   type=float, default=1.0,  help="Risk %% of equity per trade (default 1%%)")
    parser.add_argument("--dd",     type=float, default=3.0,  help="Daily DD %% limit before skipping (default 3%%)")
    parser.add_argument("--maxdd",  type=float, default=20.0, help="Max total DD %% before halt (default 20%%)")
    parser.add_argument("--maxtd",  type=int,   default=6,    help="Max trades per symbol per day (default 6)")
    parser.add_argument("--news",   action="store_true")
    args = parser.parse_args()

    if not mt5_connect(): sys.exit(1)

    acc             = mt5.account_info()
    initial_balance = acc.balance
    daily           = DailyState.load(acc.balance)
    p               = MTF_DEFAULT_PARAMS.copy()
    enable          = MTF_DEFAULT_FILTERS.copy()
    enable["currency_strength"] = False
    enable["news"]              = args.news
    symbols         = args.pairs
    rr              = p["RR_Ratio"]
    last_bar: Dict[str, pd.Timestamp] = {}
    last_signals: Dict[str, dict] = {s: {"direction": None, "bar_time": None} for s in symbols}

    news_events = None
    if args.news:
        from news_filter import fetch_ff_calendar
        news_events = fetch_ff_calendar()
        log.info(f"News filter ON — {len(news_events)} events loaded")

    # NVIDIA heartbeat state
    nvidia_alive: Optional[bool] = None
    last_nvidia_hb: float = 0.0

    # Journal close-watcher: snapshot of tracked positions from last iteration
    prev_positions: dict[int, dict] = _get_tracked_positions()
    _daily_dd_alerted: bool = False
    _last_alert_day: Optional[str] = None

    log.info(DIV)
    log.info("  MTF EMA Alignment Scalper — LIVE TRADER")
    log.info(f"  Symbols : {', '.join(symbols)}")
    log.info(f"  Risk    : {args.risk}% | RR 1:{rr} | DailyDD {args.dd}%")
    log.info(f"  Log     : {LOG_PATH}")
    log.info(DIV)
    tg_alert(
        f"🤖 MTF LIVE TRADER ONLINE\n"
        f"Pairs: {', '.join(symbols)}\n"
        f"Risk: {args.risk}% | DD limit: {args.dd}% | Max DD: {args.maxdd}%\n"
        f"Balance: ${initial_balance:.2f}",
        level="INFO"
    )

    try:
        while True:
            time.sleep(max(secs_to_next_bar() + BAR_WAIT_SEC, 1.0))

            acc = mt5.account_info()
            if acc is None:
                log.warning("MT5 disconnected — reconnecting...")
                for _ in range(5):
                    if mt5_connect(): break
                    time.sleep(10)
                acc = mt5.account_info()
                if acc is None:
                    log.error("Cannot reconnect. Stopping.")
                    break

            daily.roll_if_new_day(acc.balance)
            _today = str(daily.date)
            if _today != _last_alert_day:
                _daily_dd_alerted = False
                _last_alert_day = _today

            if args.news:
                from news_filter import fetch_ff_calendar
                news_events = fetch_ff_calendar()

            total_dd = max((initial_balance - acc.equity) / initial_balance * 100, 0)
            if total_dd >= args.maxdd:
                log.error(f"MAX DD {total_dd:.1f}% reached — stopping.")
                tg_alert(
                    f"🚨 MTF BOT HALTED\n"
                    f"Max drawdown {total_dd:.1f}% reached (limit {args.maxdd}%)\n"
                    f"Balance: ${acc.balance:.2f} | Equity: ${acc.equity:.2f}\n"
                    f"Manual review required.",
                    level="CRITICAL"
                )
                break

            daily_dd = daily.daily_loss_pct(acc.equity)
            if daily_dd >= args.dd:
                log.warning(f"Daily DD {daily_dd:.1f}% — skipping rest of day")
                if not _daily_dd_alerted:
                    tg_alert(
                        f"⚠️ MTF DAILY LIMIT HIT\n"
                        f"Daily loss {daily_dd:.1f}% (limit {args.dd}%)\n"
                        f"No new trades until tomorrow.\n"
                        f"Balance: ${acc.balance:.2f}",
                        level="WARNING"
                    )
                    _daily_dd_alerted = True
                log_status(symbols, daily, initial_balance)
                write_live_state(symbols, daily, initial_balance, last_signals, nvidia_alive)
                time.sleep(60)
                continue

            # NVIDIA heartbeat — runs every 30 minutes, non-blocking fallback
            now_ts = time.time()
            if now_ts - last_nvidia_hb >= NVIDIA_HB_INTERVAL:
                nvidia_alive = nvidia_heartbeat()
                last_nvidia_hb = now_ts
                status_str = "alive" if nvidia_alive else ("DEAD" if nvidia_alive is False else "n/a")
                log.info(f"  [NVIDIA HB] API status: {status_str}")

            prev_positions = _detect_and_journal_closes(prev_positions)

            log_status(symbols, daily, initial_balance, nvidia_alive)
            write_live_state(symbols, daily, initial_balance, last_signals, nvidia_alive)

            for symbol in symbols:
                try:
                    if has_open_position(symbol): continue
                    if daily.trades_today(symbol) >= args.maxtd: continue

                    # Apply per-symbol parameter + filter overrides
                    sym_p = p.copy()
                    sym_p.update(MTF_SYMBOL_PARAMS.get(symbol, {}))
                    sym_en = enable.copy()
                    sym_en.update(MTF_SYMBOL_FILTERS.get(symbol, {}))

                    sig, sl, tp_sig, bar_time = check_signal(
                        symbol, sym_p, sym_en, last_bar, news_events)
                    if sig == 0: continue

                    direction = "BUY" if sig == 1 else "SELL"
                    log.info(f"  SIGNAL {symbol} {direction} bar={bar_time.strftime('%H:%M')} UTC")

                    if place_order(symbol, sig, sl, sym_p["RR_Ratio"], args.risk):
                        last_bar[symbol] = bar_time
                        last_signals[symbol] = {"direction": direction, "bar_time": bar_time.isoformat()}
                        daily.add_trade(symbol)

                except Exception as e:
                    log.error(f"  {symbol}: {e}")

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        acc = mt5.account_info()
        if acc:
            pnl = acc.balance - initial_balance
            pnl_pct = (pnl / initial_balance * 100) if initial_balance > 0 else 0
            log.info(DIV)
            log.info(f"  Session end | Start=${initial_balance:.2f} "
                     f"End=${acc.balance:.2f} Net=${pnl:+.2f}")
            log.info(DIV)
            total_trades = sum(daily.trades.values()) if hasattr(daily, "trades") else 0
            if abs(pnl) > 0.01 or total_trades > 0:
                tg_alert(
                    f"📋 MTF SESSION ENDED\n"
                    f"Start: ${initial_balance:.2f} → End: ${acc.balance:.2f}\n"
                    f"Net: ${pnl:+.2f} ({pnl_pct:+.1f}%) | Trades: {total_trades}",
                    level="INFO"
                )
        mt5.shutdown()
        try:
            if STATE_PATH.exists():
                s = _json.loads(STATE_PATH.read_text(encoding="utf-8"))
                s["trader_running"] = False
                s["mt5_connected"]  = False
                STATE_PATH.write_text(_json.dumps(s, default=str), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    main()
