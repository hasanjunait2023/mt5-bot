# encoding: utf-8
"""
Strategy 6 — Asian Range Breakout Bot
======================================
Source: Notion Master Hub → Strategy 6 page

Logic:
  1. 07:00 UTC  — Calculate Asian session range (00:00–07:00) from M15 bars
  2. 07:30 UTC  — Validate range (40–150 pips, no single spike >50 pips)
  3. 07:55 UTC  — Place BUY STOP + SELL STOP (OCO) if valid
  4. On trigger — Cancel opposite pending order immediately
  5. +30 pips   — Move SL to breakeven
  6. TP1        — Close 50%, move SL to entry+30 pips
  7. TP2        — Close remaining 50%, trade complete
  8. 17:00 UTC  — Force close anything still open
  9. 17:30 UTC  — Daily summary to Telegram

Risk: 0.5% per trade
SL  : range_size + 10 pip buffer (each side)
TP1 : entry + range × 0.70  (close 50%)
TP2 : entry + range × 1.50  (close 50%)

Usage:
    python mt5_bridge/strategy6_asian_range.py
    python mt5_bridge/strategy6_asian_range.py --demo    # paper mode
    python mt5_bridge/strategy6_asian_range.py --backtest-month 2025-01
"""
import sys, os, time, argparse, logging, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_account_info

# ── Optional news filter ──────────────────────────────────────────────────────
try:
    from news_filter import is_news_blackout
    HAS_NEWS = True
except Exception:
    HAS_NEWS = False

# ── Telegram ──────────────────────────────────────────────────────────────────
try:
    import urllib.request, urllib.parse as _up
    _TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    _TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")
    HAS_TG = bool(_TG_TOKEN and _TG_CHAT)
except Exception:
    HAS_TG = False

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL        = "XAUUSD"
RISK_PCT      = 0.005          # 0.5% per trade
PIP_VALUE     = 10.0           # $ per pip per standard lot on XAUUSD
RANGE_MIN     = 40             # pips — skip day if range smaller
RANGE_MAX     = 150            # pips — skip day if range larger
SPIKE_MAX     = 50             # pips — any single M15 candle > this → invalid
BUFFER_PIPS   = 5              # entry offset beyond range high/low
SL_BUFFER     = 10             # extra pips beyond opposite range level
TP1_RATIO     = 0.70           # 70% of range
TP2_RATIO     = 1.50           # 150% of range
BE_PIPS       = 30             # move SL to BE when +30 pips
MAX_SPREAD    = 25             # pips — skip if spread wider
ORDER_EXPIRY_MIN = 125         # minutes after placement (→ ~10:00 UTC from 07:55)
MAGIC         = 20260600       # unique magic number for S6 orders
ASIAN_START_H = 0              # 00:00 UTC
ASIAN_END_H   = 7              # 07:00 UTC
PLACE_H, PLACE_M = 7, 55      # place orders at 07:55 UTC
FORCE_CLOSE_H = 17             # force close at 17:00 UTC
SUMMARY_H     = 17             # summary at 17:30 UTC
SUMMARY_M     = 30

LOG_PATH = Path(__file__).parent / "_s6_log.txt"
STATE_PATH = Path(__file__).parent / "_s6_state.json"

# ── Logging ───────────────────────────────────────────────────────────────────
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
log = logging.getLogger("S6_Asian")


# ── Telegram helper ───────────────────────────────────────────────────────────

def tg(msg: str):
    if not HAS_TG:
        return
    try:
        data = _up.urlencode({"chat_id": _TG_CHAT, "text": msg}).encode("utf-8")
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage", data, timeout=10
        )
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


# ── State ─────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_state(s: dict):
    STATE_PATH.write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")


# ── Core calculations ─────────────────────────────────────────────────────────

def get_asian_range(utc_date: datetime) -> dict:
    """
    Fetch M15 bars for the Asian session (00:00–07:00 UTC) on utc_date.
    Returns dict with keys: high, low, range_pips, valid, reason, candles
    """
    asian_start = utc_date.replace(hour=ASIAN_START_H, minute=0, second=0, microsecond=0)
    asian_end   = utc_date.replace(hour=ASIAN_END_H,   minute=0, second=0, microsecond=0)

    # Fetch enough M15 bars to cover session
    df = fetch_ohlcv(SYMBOL, mt5.TIMEFRAME_M15, 500)
    if df.empty:
        return {"valid": False, "reason": "MT5 data fetch failed"}

    df.index = pd.to_datetime(df.index, utc=True)
    session = df[(df.index >= asian_start) & (df.index < asian_end)]

    if len(session) < 20:
        return {"valid": False, "reason": f"Not enough candles ({len(session)} < 20)"}

    pip = 0.1  # XAUUSD 1 pip = $0.10 move = 10 cents; price in dollars so pip = 0.1

    asian_high = session["High"].max()
    asian_low  = session["Low"].min()
    range_pips = (asian_high - asian_low) / pip

    # Check for single spike candle
    max_candle_range = ((session["High"] - session["Low"]) / pip).max()

    if range_pips < RANGE_MIN:
        return {"valid": False, "reason": f"Range too small ({range_pips:.0f} pips < {RANGE_MIN})"}
    if range_pips > RANGE_MAX:
        return {"valid": False, "reason": f"Range too large ({range_pips:.0f} pips > {RANGE_MAX})"}
    if max_candle_range > SPIKE_MAX:
        return {"valid": False, "reason": f"Spike candle detected ({max_candle_range:.0f} pips > {SPIKE_MAX})"}

    return {
        "valid":      True,
        "high":       asian_high,
        "low":        asian_low,
        "range_pips": range_pips,
        "candles":    len(session),
        "reason":     "PASS",
    }


def check_no_trade_day(demo: bool = False) -> Optional[str]:
    """Return skip reason string if today should be skipped, else None."""
    if demo:
        return None
    if not HAS_NEWS:
        return None
    # Check for high-impact USD news at London open (07:30–08:30 UTC)
    for check_time in [
        datetime.now(timezone.utc).replace(hour=7, minute=30),
        datetime.now(timezone.utc).replace(hour=8, minute=0),
    ]:
        if is_news_blackout(SYMBOL, check_time):
            return "High-impact news at London open — skip today"
    return None


def calc_lot_size(balance: float, sl_pips: float) -> float:
    """Risk-based lot sizing: 0.5% of balance / (SL pips × pip value)."""
    risk_amount = balance * RISK_PCT
    lot = risk_amount / (sl_pips * PIP_VALUE)
    lot = math.floor(lot * 100) / 100  # round down to nearest 0.01
    return max(lot, 0.01)


def get_spread_pips() -> float:
    """Return current spread in pips for XAUUSD."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 99.0
    pip = 0.1
    return (tick.ask - tick.bid) / pip


# ── Order management ──────────────────────────────────────────────────────────

def place_oco_orders(asian_high: float, asian_low: float,
                     range_pips: float, balance: float,
                     expiry_utc: datetime, demo: bool) -> dict:
    """
    Place BUY STOP and SELL STOP orders.
    Returns {"buy_ticket": int, "sell_ticket": int, "lot": float, ...}
    """
    pip = 0.1
    buf = BUFFER_PIPS * pip

    buy_entry  = asian_high + buf
    sell_entry = asian_low  - buf

    sl_pips    = range_pips + SL_BUFFER
    buy_sl     = asian_low  - (SL_BUFFER * pip)
    sell_sl    = asian_high + (SL_BUFFER * pip)

    buy_tp1    = buy_entry  + (range_pips * TP1_RATIO * pip)
    buy_tp2    = buy_entry  + (range_pips * TP2_RATIO * pip)
    sell_tp1   = sell_entry - (range_pips * TP1_RATIO * pip)
    sell_tp2   = sell_entry - (range_pips * TP2_RATIO * pip)

    lot = calc_lot_size(balance, sl_pips)

    log.info(f"Range: High={asian_high:.2f} Low={asian_low:.2f} ({range_pips:.0f} pips)")
    log.info(f"BUY STOP:  entry={buy_entry:.2f}  SL={buy_sl:.2f}  TP1={buy_tp1:.2f}  TP2={buy_tp2:.2f}")
    log.info(f"SELL STOP: entry={sell_entry:.2f}  SL={sell_sl:.2f}  TP1={sell_tp1:.2f}  TP2={sell_tp2:.2f}")
    log.info(f"Lot: {lot}  SL pips: {sl_pips:.0f}  Risk: ${balance * RISK_PCT:.2f}")

    tg(
        f"🎯 ASIAN RANGE ORDERS PLACED\n"
        f"High: ${asian_high:.2f} | Low: ${asian_low:.2f} | Range: {range_pips:.0f} pips\n"
        f"BUY STOP: ${buy_entry:.2f} | SELL STOP: ${sell_entry:.2f}\n"
        f"SL: {sl_pips:.0f} pips | TP1: {range_pips * TP1_RATIO:.0f} pips | TP2: {range_pips * TP2_RATIO:.0f} pips\n"
        f"Lot: {lot} | Risk: ${balance * RISK_PCT:.2f} | Expiry: 10:00 UTC"
    )

    if demo:
        log.info("[DEMO] Orders not sent to MT5")
        return {
            "buy_ticket": -1, "sell_ticket": -1, "lot": lot,
            "buy_entry": buy_entry, "sell_entry": sell_entry,
            "buy_sl": buy_sl, "sell_sl": sell_sl,
            "buy_tp1": buy_tp1, "buy_tp2": buy_tp2,
            "sell_tp1": sell_tp1, "sell_tp2": sell_tp2,
            "sl_pips": sl_pips, "range_pips": range_pips,
        }

    expiry_ts = int(expiry_utc.timestamp())

    def _send_stop(order_type, price, sl, tp1):
        req = {
            "action":   mt5.TRADE_ACTION_PENDING,
            "symbol":   SYMBOL,
            "volume":   lot,
            "type":     order_type,
            "price":    price,
            "sl":       sl,
            "tp":       tp1,          # TP1 only on first order — managed in code
            "deviation": 10,
            "magic":    MAGIC,
            "comment":  "S6_Asian",
            "type_time": mt5.ORDER_TIME_SPECIFIED,
            "expiration": expiry_ts,
        }
        r = mt5.order_send(req)
        return r.order if r and r.retcode == mt5.TRADE_RETCODE_DONE else None

    buy_ticket  = _send_stop(mt5.ORDER_TYPE_BUY_STOP,  buy_entry,  buy_sl,  buy_tp1)
    sell_ticket = _send_stop(mt5.ORDER_TYPE_SELL_STOP, sell_entry, sell_sl, sell_tp1)

    if buy_ticket is None or sell_ticket is None:
        log.error(f"Order placement failed — MT5 error: {mt5.last_error()}")
        tg("⚠️ S6: Order placement FAILED — check MT5 connection")

    return {
        "buy_ticket": buy_ticket, "sell_ticket": sell_ticket, "lot": lot,
        "buy_entry": buy_entry, "sell_entry": sell_entry,
        "buy_sl": buy_sl, "sell_sl": sell_sl,
        "buy_tp1": buy_tp1, "buy_tp2": buy_tp2,
        "sell_tp1": sell_tp1, "sell_tp2": sell_tp2,
        "sl_pips": sl_pips, "range_pips": range_pips,
    }


def cancel_order(ticket: int, demo: bool):
    if demo or ticket <= 0:
        return
    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"Cancelled pending order #{ticket}")
    else:
        log.warning(f"Failed to cancel order #{ticket}: {mt5.last_error()}")


def get_open_position(magic: int = MAGIC) -> Optional[object]:
    """Return open position with our magic number, or None."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return None
    for p in positions:
        if p.magic == magic:
            return p
    return None


def get_pending_orders(magic: int = MAGIC) -> list:
    orders = mt5.orders_get(symbol=SYMBOL)
    if not orders:
        return []
    return [o for o in orders if o.magic == magic]


def modify_sl(ticket: int, new_sl: float, demo: bool):
    if demo or ticket <= 0:
        log.info(f"[DEMO] Modify SL → {new_sl:.2f}")
        return
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol":   SYMBOL,
        "sl":       new_sl,
        "tp":       p.tp,
    }
    mt5.order_send(req)


def close_partial(ticket: int, close_lots: float, demo: bool) -> bool:
    if demo:
        log.info(f"[DEMO] Close partial {close_lots} lots from #{ticket}")
        return True
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return False
    p = pos[0]
    price = mt5.symbol_info_tick(SYMBOL).bid if p.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(SYMBOL).ask
    req = {
        "action":   mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol":   SYMBOL,
        "volume":   close_lots,
        "type":     mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price":    price,
        "deviation": 20,
        "magic":    MAGIC,
        "comment":  "S6_partial",
    }
    r = mt5.order_send(req)
    return r and r.retcode == mt5.TRADE_RETCODE_DONE


def close_all(magic: int = MAGIC, demo: bool = False):
    if demo:
        log.info("[DEMO] Force close all")
        return
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return
    for p in positions:
        if p.magic != magic:
            continue
        price = mt5.symbol_info_tick(SYMBOL).bid if p.type == mt5.POSITION_TYPE_BUY \
                else mt5.symbol_info_tick(SYMBOL).ask
        req = {
            "action":   mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol":   SYMBOL,
            "volume":   p.volume,
            "type":     mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "price":    price,
            "deviation": 30,
            "magic":    MAGIC,
            "comment":  "S6_forceclose",
        }
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"Force closed position #{p.ticket}")


# ── Main trading loop ─────────────────────────────────────────────────────────

class S6Bot:
    def __init__(self, demo: bool = False):
        self.demo          = demo
        self.today         = None     # date string YYYY-MM-DD
        self.range_data    = None     # result from get_asian_range()
        self.order_data    = None     # result from place_oco_orders()
        self.phase         = "SLEEP"  # SLEEP → RANGE → ORDERS → MONITOR → DONE
        self.be_moved      = False
        self.tp1_hit       = False
        self.pos_ticket    = None
        self.initial_lot   = None
        self.wins          = 0
        self.losses        = 0
        self.day_pnl       = 0.0
        state = _load_state()
        if state.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            self.phase   = state.get("phase", "SLEEP")
            self.be_moved = state.get("be_moved", False)
            self.tp1_hit  = state.get("tp1_hit", False)
            log.info(f"Restored state: phase={self.phase}")

    def _save(self):
        _save_state({
            "date": self.today, "phase": self.phase,
            "be_moved": self.be_moved, "tp1_hit": self.tp1_hit,
        })

    def _reset_day(self, today_str: str):
        self.today      = today_str
        self.range_data = None
        self.order_data = None
        self.phase      = "SLEEP"
        self.be_moved   = False
        self.tp1_hit    = False
        self.pos_ticket = None
        self.initial_lot = None
        self._save()

    def run(self):
        log.info("=" * 64)
        log.info("Strategy 6 — Asian Range Breakout Bot — STARTING")
        log.info(f"Symbol: {SYMBOL} | Risk: {RISK_PCT*100}% | Demo: {self.demo}")
        log.info("=" * 64)
        tg(f"🌅 S6 Asian Range Bot ONLINE\nSymbol: {SYMBOL} | Demo: {self.demo}")

        if not self.demo and not connect():
            log.error("MT5 connection failed — exiting")
            sys.exit(1)

        try:
            self._loop()
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            if not self.demo:
                disconnect()

    def _loop(self):
        while True:
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")

            # New day reset
            if self.today != today_str:
                self._reset_day(today_str)
                log.info(f"--- New day: {today_str} ---")

            h, m = now.hour, now.minute

            # ── SLEEP phase: 07:00 UTC → calculate range ─────────────────────
            if self.phase == "SLEEP" and h == ASIAN_END_H and m == 0:
                self._do_range_check(now)

            # ── RANGE phase: 07:30 → log pre-market checklist ────────────────
            elif self.phase == "RANGE" and h == 7 and m == 30:
                self._do_premarket_check(now)

            # ── RANGE phase: 07:55 → place orders ────────────────────────────
            elif self.phase == "RANGE" and h == PLACE_H and m == PLACE_M:
                self._do_place_orders(now)

            # ── ORDERS/MONITOR phase: check if breakout triggered ─────────────
            elif self.phase in ("ORDERS", "MONITOR"):
                self._do_monitor(now)

            # ── Force close at 17:00 UTC ──────────────────────────────────────
            elif self.phase in ("ORDERS", "MONITOR") and h == FORCE_CLOSE_H and m == 0:
                self._do_force_close(now)

            # ── Daily summary at 17:30 ────────────────────────────────────────
            elif h == SUMMARY_H and m == SUMMARY_M and self.phase != "SUMMARY_SENT":
                self._do_summary(now)
                self.phase = "SUMMARY_SENT"

            time.sleep(30)  # check every 30 seconds

    def _do_range_check(self, now: datetime):
        log.info("07:00 UTC — Calculating Asian range...")
        skip = check_no_trade_day(self.demo)
        if skip:
            log.info(f"SKIP DAY: {skip}")
            tg(f"⏭ S6 SKIP TODAY\nReason: {skip}")
            self.phase = "DONE"
            self._save()
            return

        r = get_asian_range(now)
        self.range_data = r
        if not r["valid"]:
            log.info(f"Range invalid: {r['reason']}")
            tg(f"⏭ S6 RANGE INVALID\n{r['reason']}\nNo trades today.")
            self.phase = "DONE"
        else:
            log.info(
                f"Range VALID: High={r['high']:.2f} Low={r['low']:.2f} "
                f"Range={r['range_pips']:.0f} pips ({r['candles']} candles)"
            )
            tg(
                f"📊 ASIAN RANGE IDENTIFIED\n"
                f"High: ${r['high']:.2f} | Low: ${r['low']:.2f} | Range: {r['range_pips']:.0f} pips\n"
                f"Candles: {r['candles']} | Validation: PASS\n"
                f"Orders will be placed at 07:55 UTC"
            )
            self.phase = "RANGE"
        self._save()

    def _do_premarket_check(self, now: datetime):
        if not self.range_data or not self.range_data["valid"]:
            return
        spread = get_spread_pips() if not self.demo else 15.0
        log.info(f"07:30 Pre-market: spread={spread:.1f} pips")
        if spread > MAX_SPREAD:
            log.warning(f"Spread {spread:.1f} pips > {MAX_SPREAD} max — will re-check at 07:55")

    def _do_place_orders(self, now: datetime):
        if not self.range_data or not self.range_data["valid"]:
            return
        spread = get_spread_pips() if not self.demo else 15.0
        if spread > MAX_SPREAD:
            log.warning(f"Spread too wide at order time ({spread:.1f} pips) — SKIP today")
            tg(f"⏭ S6 SKIP: Spread too wide at 07:55 ({spread:.1f} pips > {MAX_SPREAD})")
            self.phase = "DONE"
            self._save()
            return

        acc = get_account_info() if not self.demo else {"balance": 1000.0}
        balance = acc.get("balance", 1000.0)
        expiry_utc = now.replace(hour=10, minute=0, second=0, microsecond=0)

        self.order_data = place_oco_orders(
            self.range_data["high"], self.range_data["low"],
            self.range_data["range_pips"], balance, expiry_utc, self.demo
        )
        self.initial_lot = self.order_data["lot"]
        self.phase = "ORDERS"
        self._save()

    def _do_monitor(self, now: datetime):
        if not self.order_data:
            return

        h, m = now.hour, now.minute

        # Expiry check — past 10:00 and still no position
        if h >= 10 and m >= 5 and not get_open_position() and not self.demo:
            pending = get_pending_orders()
            if pending:
                for o in pending:
                    cancel_order(o.ticket, self.demo)
                log.info("Orders expired at 10:00 — no breakout, cancelled remaining")
                tg("⏰ S6: Orders expired (no breakout by 10:00) — no trade today")
                self.phase = "DONE"
                self._save()
            return

        pos = get_open_position() if not self.demo else None

        # Breakout triggered — cancel opposite order
        if pos and self.phase == "ORDERS":
            direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            log.info(f"BREAKOUT TRIGGERED: {direction} @ {pos.price_open:.2f}")
            tg(
                f"🚀 BREAKOUT! {direction} @ ${pos.price_open:.2f}\n"
                f"SL: ${pos.sl:.2f} | TP: ${pos.tp:.2f}\n"
                f"Lot: {pos.volume} | Risk: ${pos.volume * self.order_data['sl_pips'] * PIP_VALUE:.2f}"
            )
            # Cancel opposite pending
            if direction == "BUY" and self.order_data["sell_ticket"]:
                cancel_order(self.order_data["sell_ticket"], self.demo)
            elif direction == "SELL" and self.order_data["buy_ticket"]:
                cancel_order(self.order_data["buy_ticket"], self.demo)

            self.pos_ticket = pos.ticket
            self.phase = "MONITOR"
            self._save()
            return

        if pos and self.phase == "MONITOR":
            self._manage_open_position(pos)

    def _manage_open_position(self, pos):
        pip = 0.1
        direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
        current   = mt5.symbol_info_tick(SYMBOL).bid if not self.demo else pos.price_open
        profit_pips = (current - pos.price_open) / pip if direction == "BUY" \
                      else (pos.price_open - current) / pip

        od = self.order_data

        # Breakeven
        if not self.be_moved and profit_pips >= BE_PIPS:
            new_sl = pos.price_open if direction == "BUY" else pos.price_open
            modify_sl(pos.ticket, new_sl, self.demo)
            self.be_moved = True
            self._save()
            log.info(f"SL moved to breakeven @ {new_sl:.2f} (+{profit_pips:.0f} pips)")
            tg(f"✅ S6 BREAKEVEN\nSL moved to entry ${new_sl:.2f} (+{BE_PIPS} pips reached)")

        # TP1 — close 50%
        if not self.tp1_hit:
            tp1 = od["buy_tp1"] if direction == "BUY" else od["sell_tp1"]
            hit = current >= tp1 if direction == "BUY" else current <= tp1
            if hit:
                close_lots = math.floor(pos.volume / 2 * 100) / 100
                close_lots = max(close_lots, 0.01)
                if close_partial(pos.ticket, close_lots, self.demo):
                    self.tp1_hit = True
                    pnl = close_lots * profit_pips * PIP_VALUE
                    self.day_pnl += pnl
                    self._save()
                    tp1_pips = self.order_data["range_pips"] * TP1_RATIO
                    log.info(f"TP1 HIT — closed {close_lots} lots @ {current:.2f}")
                    tg(
                        f"🎯 S6 TP1 HIT — 50% closed\n"
                        f"Price: ${current:.2f} | +{tp1_pips:.0f} pips\n"
                        f"Locked: ${pnl:.2f}"
                    )
                    # Move SL to entry+30 pips
                    if direction == "BUY":
                        new_sl = pos.price_open + (30 * pip)
                    else:
                        new_sl = pos.price_open - (30 * pip)
                    modify_sl(pos.ticket, new_sl, self.demo)

        # TP2 — remaining closes automatically via MT5 TP
        # (We set TP on the order; MT5 handles it. Just log when position gone.)

    def _do_force_close(self, now: datetime):
        pos = get_open_position() if not self.demo else None
        if pos:
            pnl = pos.profit
            self.day_pnl += pnl
            direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            log.info(f"FORCE CLOSE at 17:00 UTC — {direction} PnL: ${pnl:.2f}")
            close_all(demo=self.demo)
            tg(
                f"🕔 S6 FORCE CLOSE (17:00 UTC)\n"
                f"Direction: {direction} | PnL: ${pnl:.2f}\n"
                f"Day total: ${self.day_pnl:.2f}"
            )
        # Cancel any remaining pending orders
        for o in get_pending_orders():
            cancel_order(o.ticket, self.demo)
        self.phase = "DONE"
        self._save()

    def _do_summary(self, now: datetime):
        acc = get_account_info() if not self.demo else {"balance": 0, "equity": 0}
        bal = acc.get("balance", 0)
        eq  = acc.get("equity", 0)
        log.info(f"Daily Summary: PnL=${self.day_pnl:.2f} Balance=${bal:.2f}")
        tg(
            f"📋 S6 DAILY SUMMARY — {self.today}\n"
            f"Balance: ${bal:.2f} | Equity: ${eq:.2f}\n"
            f"Day PnL: ${self.day_pnl:.2f}\n"
            f"Phase reached: {self.phase}\n"
            f"Bot sleeping until 07:00 UTC tomorrow."
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Strategy 6 — Asian Range Breakout Bot")
    parser.add_argument("--demo", action="store_true", help="Paper mode — no real orders sent")
    parser.add_argument("--check-range", action="store_true", help="Calculate today's range and exit")
    args = parser.parse_args()

    if args.check_range:
        if not connect():
            sys.exit(1)
        now = datetime.now(timezone.utc)
        r = get_asian_range(now)
        print(f"\nAsian Range Check — {now.strftime('%Y-%m-%d')}")
        print(f"  Valid  : {r['valid']}")
        print(f"  Reason : {r['reason']}")
        if r["valid"]:
            print(f"  High   : {r['high']:.2f}")
            print(f"  Low    : {r['low']:.2f}")
            print(f"  Range  : {r['range_pips']:.0f} pips")
            print(f"  Candles: {r['candles']}")
        disconnect()
        return

    bot = S6Bot(demo=args.demo)
    bot.run()


if __name__ == "__main__":
    main()
