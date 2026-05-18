"""
Strategy 2 — M5 Medium Frequency Scalping
==========================================
Layers:
  Layer 1 : H1 EMA200 bias  (once per session, cached)
  Layer 2 : M5 EMA9/21 fresh crossover
  Layer 3 : RSI14 — in correct zone, not at extreme
  Layer 4 : MACD(12,26,9) histogram matches direction
  Extra   : spread ≤ 25 pips, news filter, session guard

Trade management:
  SL  15-20 pips (fixed 18 pips)
  BE  at +8 pips
  TP1 +20 pips  (close 50 % of position)
  TP2 +40 pips  (close remaining 50 %)
  Time exit: 45 minutes

Session   : 07:00 – 17:00 UTC
Risk      : 0.5 % equity per trade
Max daily DD: 5 % equity
Magic     : 20260200
"""

import os, sys, time, json, math, logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional

import MetaTrader5 as mt5
import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  S2  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "_s2_log.txt"), encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("S2")

# ── constants ────────────────────────────────────────────────────────────────
SYMBOL       = "XAUUSD"
MAGIC        = 20260200
RISK_PCT     = 0.5          # % equity per trade
SL_PIPS      = 18
TP1_PIPS     = 20
TP2_PIPS     = 40
BE_PIPS      = 8
MAX_SPREAD   = 25           # pips
MAX_DAILY_DD = 5.0          # % equity
SESSION_START = 7           # UTC hour
SESSION_END   = 17          # UTC hour
TIME_EXIT_MIN = 45          # minutes
LOOP_SLEEP    = 30          # seconds between main loop iterations
NEWS_BLOCK_MIN = 30         # minutes before/after high-impact news

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")


def tg(msg: str):
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": f"[S2-M5]\n{msg}"},
            timeout=10,
        )
    except Exception:
        pass


# ── helpers ───────────────────────────────────────────────────────────────────
def pip_value() -> float:
    info = mt5.symbol_info(SYMBOL)
    return info.point * 10 if info else 0.1


def pip_to_price(pips: float) -> float:
    return pips * pip_value()


def lot_size(sl_pips: float) -> float:
    acct   = mt5.account_info()
    equity = acct.equity
    risk   = equity * RISK_PCT / 100
    info   = mt5.symbol_info(SYMBOL)
    tick   = mt5.symbol_info_tick(SYMBOL)
    if not info or not tick:
        return info.volume_min if info else 0.01
    sl_price = sl_pips * pip_value()
    contract = info.trade_contract_size
    raw  = risk / (sl_price * contract)
    step = info.volume_step
    lot  = max(info.volume_min, min(info.volume_max, math.floor(raw / step) * step))
    return round(lot, 2)


def spread_ok() -> bool:
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return False
    sp = (tick.ask - tick.bid) / pip_value()
    return sp <= MAX_SPREAD


def in_session() -> bool:
    now = datetime.now(timezone.utc)
    return SESSION_START <= now.hour < SESSION_END


def news_block() -> bool:
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r   = requests.get(url, timeout=8)
        if r.status_code != 200:
            return False
        now  = datetime.now(timezone.utc)
        high = [e for e in r.json() if e.get("impact") in ("High",)]
        for ev in high:
            try:
                ev_dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            delta = abs((ev_dt - now).total_seconds()) / 60
            if delta < NEWS_BLOCK_MIN:
                return True
    except Exception:
        pass
    return False


# ── EMA / RSI / MACD ──────────────────────────────────────────────────────────
def ema(values: np.ndarray, period: int) -> np.ndarray:
    k   = 2 / (period + 1)
    out = np.empty(len(values))
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g  = np.mean(gains[-period:])
    avg_l  = np.mean(losses[-period:])
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def calc_macd(closes: np.ndarray):
    if len(closes) < 35:
        return 0.0, 0.0
    ema12    = ema(closes, 12)
    ema26    = ema(closes, 26)
    macd_line = ema12 - ema26
    signal    = ema(macd_line, 9)
    hist      = macd_line - signal
    return hist[-1], hist[-2] if len(hist) >= 2 else hist[-1]


# ── layer functions ───────────────────────────────────────────────────────────
def layer1_h1_bias() -> str:
    """H1 EMA200 — returns BUY_ONLY / SELL_ONLY / NO_TRADE."""
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 250)
    if bars is None or len(bars) < 205:
        return "NO_TRADE"
    closes = np.array([b["close"] for b in bars])
    e200   = ema(closes, 200)
    price  = closes[-1]
    dist   = abs(price - e200[-1]) / pip_value()
    if dist < 20:
        return "NO_TRADE"
    return "BUY_ONLY" if price > e200[-1] else "SELL_ONLY"


def layer2_m5_cross() -> str:
    """M5 EMA9/21 — fresh crossover on last closed candle.
    Returns BUY / SELL / NONE."""
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 50)
    if bars is None or len(bars) < 25:
        return "NONE"
    closes = np.array([b["close"] for b in bars])
    e9     = ema(closes, 9)
    e21    = ema(closes, 21)
    # fresh crossover = cross on the last completed candle (index -2)
    bull_cross = e9[-2] > e21[-2] and e9[-3] <= e21[-3]
    bear_cross = e9[-2] < e21[-2] and e9[-3] >= e21[-3]
    if bull_cross:
        return "BUY"
    if bear_cross:
        return "SELL"
    return "NONE"


def layer3_rsi(direction: str) -> bool:
    """RSI14 on M5 — must be in correct zone, not at extreme."""
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 30)
    if bars is None or len(bars) < 20:
        return False
    closes = np.array([b["close"] for b in bars])
    rsi    = calc_rsi(closes)
    if direction == "BUY":
        return 40 <= rsi <= 65
    if direction == "SELL":
        return 35 <= rsi <= 60
    return False


def layer4_macd(direction: str) -> bool:
    """MACD(12,26,9) histogram — must match direction and be moving right way."""
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 60)
    if bars is None or len(bars) < 35:
        return False
    closes    = np.array([b["close"] for b in bars])
    hist, prev = calc_macd(closes)
    if direction == "BUY":
        return hist > 0 or (hist > prev)
    if direction == "SELL":
        return hist < 0 or (hist < prev)
    return False


# ── trade execution ───────────────────────────────────────────────────────────
def place_order(direction: str) -> Optional[int]:
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if not tick or not info:
        return None

    sl_dist = pip_to_price(SL_PIPS)
    lot     = lot_size(SL_PIPS)

    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price      = tick.ask
        sl         = round(price - sl_dist, info.digits)
        tp         = round(price + pip_to_price(TP2_PIPS), info.digits)
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price      = tick.bid
        sl         = round(price + sl_dist, info.digits)
        tp         = round(price - pip_to_price(TP2_PIPS), info.digits)

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    20,
        "magic":        MAGIC,
        "comment":      "S2_entry",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        tg(
            f"ENTRY {direction}  {lot} lots @ {price:.2f}\n"
            f"SL {sl:.2f}  TP {tp:.2f}\n"
            f"Ticket #{res.order}"
        )
        return res.order
    log.warning("order_send failed: %s", res)
    return None


def modify_sl(ticket: int, new_sl: float):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p   = pos[0]
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       new_sl,
        "tp":       p.tp,
        "symbol":   SYMBOL,
    }
    mt5.order_send(req)


def close_partial(ticket: int, volume: float):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == 0 else tick.ask
    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       round(volume, 2),
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "deviation":    20,
        "magic":        MAGIC,
        "comment":      "S2_partial",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    mt5.order_send(req)


def close_full(ticket: int, comment: str = "S2_close"):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == 0 else tick.ask
    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       p.volume,
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "deviation":    20,
        "magic":        MAGIC,
        "comment":      comment,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    mt5.order_send(req)


# ── S2Bot class ───────────────────────────────────────────────────────────────
class S2Bot:
    def __init__(self):
        self.ticket:      Optional[int]   = None
        self.direction:   str             = ""
        self.open_price:  float           = 0.0
        self.open_time:   Optional[datetime] = None
        self.initial_lot: float           = 0.0
        self.tp1_hit:     bool            = False
        self.be_set:      bool            = False
        self.h1_bias:     str             = "NO_TRADE"
        self.bias_date:   Optional[date]  = None
        self.daily_start_equity: float    = 0.0
        self.today_date:  Optional[date]  = None
        self.today_trades: int            = 0
        self.today_wins:   int            = 0
        self.today_losses: int            = 0
        self.today_pnl:    float          = 0.0
        self._last_candle_time: Optional[datetime] = None

    # ── daily state reset ─────────────────────────────────────────────────
    def _check_daily_reset(self):
        today = date.today()
        if self.today_date != today:
            if self.today_date is not None:
                self._send_daily_summary()
            self.today_date          = today
            self.today_trades        = 0
            self.today_wins          = 0
            self.today_losses        = 0
            self.today_pnl           = 0.0
            acct                     = mt5.account_info()
            self.daily_start_equity  = acct.equity if acct else 0.0
            self.h1_bias             = "NO_TRADE"
            self.bias_date           = None
            log.info("Daily state reset. Equity %.2f", self.daily_start_equity)

    def _send_daily_summary(self):
        msg = (
            f"Daily Summary — {self.today_date}\n"
            f"Trades: {self.today_trades}  W/L: {self.today_wins}/{self.today_losses}\n"
            f"P&L:  {self.today_pnl:+.2f} USD"
        )
        log.info(msg)
        tg(msg)

    # ── daily DD check ─────────────────────────────────────────────────────
    def _daily_dd_ok(self) -> bool:
        if self.daily_start_equity <= 0:
            return True
        acct = mt5.account_info()
        if not acct:
            return True
        dd = (self.daily_start_equity - acct.equity) / self.daily_start_equity * 100
        if dd >= MAX_DAILY_DD:
            msg = f"Daily DD {dd:.1f}% >= {MAX_DAILY_DD}% — trading halted for today."
            log.warning(msg)
            tg(msg)
            return False
        return True

    # ── bias refresh ──────────────────────────────────────────────────────
    def _refresh_bias(self):
        today = date.today()
        if self.bias_date == today:
            return
        self.h1_bias   = layer1_h1_bias()
        self.bias_date = today
        log.info("H1 bias refreshed: %s", self.h1_bias)

    # ── new M5 candle? ─────────────────────────────────────────────────────
    def _new_m5_candle(self) -> bool:
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
        if bars is None or len(bars) == 0:
            return False
        ct = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc)
        if ct != self._last_candle_time:
            self._last_candle_time = ct
            return True
        return False

    # ── signal check ──────────────────────────────────────────────────────
    def _seek_signal(self) -> Optional[str]:
        if self.h1_bias == "NO_TRADE":
            return None

        m5_cross = layer2_m5_cross()
        if m5_cross == "NONE":
            return None

        if self.h1_bias == "BUY_ONLY" and m5_cross != "BUY":
            return None
        if self.h1_bias == "SELL_ONLY" and m5_cross != "SELL":
            return None

        direction = m5_cross

        if not layer3_rsi(direction):
            log.debug("RSI filter rejected %s", direction)
            return None

        if not layer4_macd(direction):
            log.debug("MACD filter rejected %s", direction)
            return None

        if not spread_ok():
            log.debug("Spread too wide")
            return None

        if news_block():
            log.info("News block active — skip")
            return None

        return direction

    # ── position management ────────────────────────────────────────────────
    def _manage(self):
        if self.ticket is None:
            return

        pos_list = mt5.positions_get(ticket=self.ticket)
        if not pos_list:
            # position closed externally
            self._on_close()
            return

        pos  = pos_list[0]
        tick = mt5.symbol_info_tick(SYMBOL)
        if not tick:
            return

        cur_price = tick.bid if pos.type == 0 else tick.ask
        pnl_pips  = (
            (cur_price - self.open_price) / pip_value()
            if pos.type == 0
            else (self.open_price - cur_price) / pip_value()
        )

        # BE trigger
        if not self.be_set and pnl_pips >= BE_PIPS:
            new_sl = (
                self.open_price + pip_to_price(2)
                if pos.type == 0
                else self.open_price - pip_to_price(2)
            )
            modify_sl(self.ticket, round(new_sl, mt5.symbol_info(SYMBOL).digits))
            self.be_set = True
            log.info("BE set on ticket %d", self.ticket)
            tg(f"BE set  ticket #{self.ticket}  pnl={pnl_pips:.1f} pips")

        # TP1 — close 50 % at +20 pips
        if not self.tp1_hit and pnl_pips >= TP1_PIPS:
            half = round(self.initial_lot * 0.5, 2)
            close_partial(self.ticket, half)
            self.tp1_hit = True
            log.info("TP1 hit, closed %.2f lots", half)
            tg(f"TP1 +{TP1_PIPS}pips  partial close {half} lots  ticket #{self.ticket}")

        # Time exit — 45 min
        if self.open_time:
            elapsed = (datetime.now(timezone.utc) - self.open_time).total_seconds() / 60
            if elapsed >= TIME_EXIT_MIN:
                log.info("Time exit (%.0f min)", elapsed)
                tg(f"Time exit after {elapsed:.0f} min  ticket #{self.ticket}")
                close_full(self.ticket, "S2_time_exit")
                self._on_close()

    def _on_close(self):
        if self.ticket is None:
            return
        pos_list = mt5.positions_get(ticket=self.ticket)
        if not pos_list:
            # try history
            from_time = datetime.now(timezone.utc) - timedelta(hours=1)
            hist = mt5.history_deals_get(from_time, datetime.now(timezone.utc))
            pnl  = 0.0
            if hist:
                for d in hist:
                    if d.position_id == self.ticket:
                        pnl += d.profit
            if pnl > 0:
                self.today_wins   += 1
            else:
                self.today_losses += 1
            self.today_pnl    += pnl
            self.today_trades += 1
            log.info("Position %d closed  pnl=%.2f", self.ticket, pnl)
            tg(f"Position #{self.ticket} closed  P&L {pnl:+.2f} USD")

        self.ticket      = None
        self.direction   = ""
        self.open_price  = 0.0
        self.open_time   = None
        self.initial_lot = 0.0
        self.tp1_hit     = False
        self.be_set      = False

    # ── main loop ─────────────────────────────────────────────────────────
    def _loop(self):
        self._check_daily_reset()

        if not in_session():
            if self.ticket is not None:
                log.info("Session ended — closing open trade.")
                close_full(self.ticket, "S2_session_end")
                self._on_close()
            # daily summary at 17:30
            now = datetime.now(timezone.utc)
            if now.hour == 17 and 30 <= now.minute < 32:
                self._send_daily_summary()
            return

        if not self._daily_dd_ok():
            return

        self._manage()

        if self.ticket is not None:
            return  # one trade at a time

        if not self._new_m5_candle():
            return

        self._refresh_bias()

        direction = self._seek_signal()
        if direction is None:
            return

        ticket = place_order(direction)
        if ticket:
            pos_list = mt5.positions_get(ticket=ticket)
            if pos_list:
                p = pos_list[0]
                self.ticket      = ticket
                self.direction   = direction
                self.open_price  = p.price_open
                self.open_time   = datetime.now(timezone.utc)
                self.initial_lot = p.volume
                self.tp1_hit     = False
                self.be_set      = False
                log.info(
                    "Trade opened: %s  ticket %d  @ %.2f  lot %.2f",
                    direction, ticket, p.price_open, p.volume,
                )

    def run(self):
        if not mt5.initialize():
            log.critical("MT5 initialize failed")
            sys.exit(1)

        log.info("S2 M5-Scalp bot started.")
        tg("S2 M5-Scalp bot started and ready.")

        try:
            while True:
                try:
                    self._loop()
                except Exception as exc:
                    log.exception("Loop error: %s", exc)
                time.sleep(LOOP_SLEEP)
        finally:
            mt5.shutdown()
            log.info("S2 bot shut down.")


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    S2Bot().run()
