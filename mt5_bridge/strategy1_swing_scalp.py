"""
Strategy 1 — Low Frequency Swing Scalp
=======================================
Layers:
  Layer 1 : H4 EMA200 macro bias
  Layer 2 : H1 Order Block (OB) detection — last unfilled OB in direction
  Layer 3 : H1 Fair Value Gap (FVG) — price inside or near FVG
  Layer 4 : M15 entry trigger — M15 EMA21 reclaim + RSI14 signal candle
  Extra   : spread ≤ 30 pips, news filter, London/NY sessions

Trade management:
  SL   50-100 pips (set to OB boundary, capped at 80 pips)
  RR   minimum 1:2
  Partial closes:
    +25 pips  → close 25 %
    +50 pips  → close 25 %
    +100 pips → close 25 %
    +200 pips → close 25 %   (full exit)
  BE: move SL to entry after first partial close
  Max open time: 3 sessions (≈ 24 hours)

Sessions   : London (07:00-12:00 UTC) + NY (13:00-17:00 UTC)
Risk       : 1.0 % equity per trade
Max trades : 5 per day
Magic      : 20260100
"""

import os, sys, time, json, math, logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional

import MetaTrader5 as mt5
import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  S1  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "_s1_log.txt"), encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("S1")

# ── constants ─────────────────────────────────────────────────────────────────
SYMBOL      = "XAUUSD"
MAGIC       = 20260100
RISK_PCT    = 1.0
SL_MAX_PIPS = 80
SL_MIN_PIPS = 50
RR_MIN      = 2.0
MAX_SPREAD  = 30
MAX_TRADES  = 5
NEWS_BLOCK  = 60           # minutes around high-impact news
MAX_HOLD_H  = 24           # force-close after N hours

PARTIALS = [
    (25,  0.25),
    (50,  0.25),
    (100, 0.25),
    (200, 0.25),
]

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")


def tg(msg: str):
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": f"[S1-SWING]\n{msg}"},
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
    raw   = risk / (sl_price * contract)
    step  = info.volume_step
    lot   = max(info.volume_min, min(info.volume_max, math.floor(raw / step) * step))
    return round(lot, 2)


def spread_ok() -> bool:
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return False
    return (tick.ask - tick.bid) / pip_value() <= MAX_SPREAD


def in_session() -> bool:
    now = datetime.now(timezone.utc)
    h   = now.hour
    return (7 <= h < 12) or (13 <= h < 17)


def news_block() -> bool:
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r   = requests.get(url, timeout=8)
        if r.status_code != 200:
            return False
        now  = datetime.now(timezone.utc)
        high = [e for e in r.json() if e.get("impact") == "High"]
        for ev in high:
            try:
                ev_dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            delta = abs((ev_dt - now).total_seconds()) / 60
            if delta < NEWS_BLOCK:
                return True
    except Exception:
        pass
    return False


# ── technical helpers ─────────────────────────────────────────────────────────
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
    return 100 - 100 / (1 + avg_g / avg_l)


def find_order_block(bars, direction: str, lookback: int = 30):
    """Find the most recent unfilled Order Block in the given direction.
    OB = last down-candle before a strong up-move (for BUY) or
         last up-candle before a strong down-move (for SELL).
    Returns (ob_high, ob_low) or None.
    """
    if bars is None or len(bars) < lookback + 2:
        return None

    closes = np.array([b["close"] for b in bars])
    highs  = np.array([b["high"]  for b in bars])
    lows   = np.array([b["low"]   for b in bars])

    for i in range(len(bars) - 2, max(0, len(bars) - lookback), -1):
        c0, c1 = bars[i], bars[i + 1]
        if direction == "BUY":
            # bearish candle followed by strong bullish
            if (c0["close"] < c0["open"]
                    and c1["close"] > c1["open"]
                    and (c1["close"] - c1["open"]) > 1.5 * abs(c0["close"] - c0["open"])):
                ob_high = c0["high"]
                ob_low  = c0["low"]
                # must not have been fully filled since formation
                price_now = closes[-1]
                if price_now >= ob_low:  # price is at or above OB
                    return (ob_high, ob_low)
        else:
            # bullish candle followed by strong bearish
            if (c0["close"] > c0["open"]
                    and c1["close"] < c1["open"]
                    and (c1["open"] - c1["close"]) > 1.5 * abs(c0["close"] - c0["open"])):
                ob_high = c0["high"]
                ob_low  = c0["low"]
                price_now = closes[-1]
                if price_now <= ob_high:
                    return (ob_high, ob_low)
    return None


def find_fvg(bars, direction: str):
    """Fair Value Gap — 3-candle imbalance.
    Returns (fvg_high, fvg_low) of most recent unfilled FVG, or None.
    """
    if bars is None or len(bars) < 5:
        return None

    closes = np.array([b["close"] for b in bars])
    for i in range(len(bars) - 3, max(0, len(bars) - 20), -1):
        c0, c1, c2 = bars[i], bars[i + 1], bars[i + 2]
        if direction == "BUY":
            # bullish FVG: c2.low > c0.high
            if c2["low"] > c0["high"]:
                fvg_high = c2["low"]
                fvg_low  = c0["high"]
                # price approaching from above (within 50 pips)
                price_now = closes[-1]
                if fvg_low <= price_now <= fvg_high + pip_to_price(50):
                    return (fvg_high, fvg_low)
        else:
            # bearish FVG: c2.high < c0.low
            if c2["high"] < c0["low"]:
                fvg_high = c0["low"]
                fvg_low  = c2["high"]
                price_now = closes[-1]
                if fvg_low - pip_to_price(50) <= price_now <= fvg_high:
                    return (fvg_high, fvg_low)
    return None


# ── layers ─────────────────────────────────────────────────────────────────────
def layer1_h4_bias() -> str:
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H4, 0, 250)
    if bars is None or len(bars) < 205:
        return "NO_TRADE"
    closes = np.array([b["close"] for b in bars])
    e200   = ema(closes, 200)
    price  = closes[-1]
    dist   = abs(price - e200[-1]) / pip_value()
    if dist < 30:
        return "NO_TRADE"
    return "BUY_ONLY" if price > e200[-1] else "SELL_ONLY"


def layer2_h1_ob(direction: str):
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 60)
    return find_order_block(bars, direction)


def layer3_h1_fvg(direction: str):
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 30)
    return find_fvg(bars, direction)


def layer4_m15_trigger(direction: str) -> bool:
    """M15 EMA21 reclaim + RSI14 in correct zone."""
    bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 40)
    if bars is None or len(bars) < 25:
        return False
    closes = np.array([b["close"] for b in bars])
    e21    = ema(closes, 21)
    rsi    = calc_rsi(closes)

    if direction == "BUY":
        # price just crossed back above EMA21
        cross = closes[-2] <= e21[-2] and closes[-1] > e21[-1]
        rsi_ok = 40 <= rsi <= 65
    else:
        cross  = closes[-2] >= e21[-2] and closes[-1] < e21[-1]
        rsi_ok = 35 <= rsi <= 60

    return cross and rsi_ok


# ── trade execution ───────────────────────────────────────────────────────────
def place_order(direction: str, sl_pips: float, tp_pips: float) -> Optional[int]:
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if not tick or not info:
        return None

    lot = lot_size(sl_pips)
    sl_dist = pip_to_price(sl_pips)
    tp_dist = pip_to_price(tp_pips)

    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        sl    = round(price - sl_dist, info.digits)
        tp    = round(price + tp_dist, info.digits)
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        sl    = round(price + sl_dist, info.digits)
        tp    = round(price - tp_dist, info.digits)

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      "S1_entry",
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
    p = pos[0]
    mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       new_sl,
        "tp":       p.tp,
        "symbol":   SYMBOL,
    })


def close_partial(ticket: int, volume: float, comment: str = "S1_partial"):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == 0 else tick.ask
    mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       round(volume, 2),
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      comment,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })


def close_full(ticket: int, comment: str = "S1_close"):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == 0 else tick.ask
    mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       p.volume,
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      comment,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })


# ── S1Bot class ───────────────────────────────────────────────────────────────
class S1Bot:
    def __init__(self):
        self.ticket:      Optional[int]      = None
        self.direction:   str                = ""
        self.open_price:  float              = 0.0
        self.open_time:   Optional[datetime] = None
        self.initial_lot: float              = 0.0
        self.partials_hit: list              = []   # list of pip levels already closed
        self.be_set:      bool               = False
        self.h4_bias:     str                = "NO_TRADE"
        self.bias_date:   Optional[date]     = None
        self.today_date:  Optional[date]     = None
        self.today_trades: int               = 0
        self.today_wins:   int               = 0
        self.today_losses: int               = 0
        self.today_pnl:    float             = 0.0
        self._last_m15_time: Optional[datetime] = None

    def _check_daily_reset(self):
        today = date.today()
        if self.today_date != today:
            if self.today_date is not None:
                self._send_summary()
            self.today_date   = today
            self.today_trades = 0
            self.today_wins   = 0
            self.today_losses = 0
            self.today_pnl    = 0.0
            self.h4_bias      = "NO_TRADE"
            self.bias_date    = None
            log.info("Daily reset.")

    def _send_summary(self):
        msg = (
            f"Daily Summary — {self.today_date}\n"
            f"Trades: {self.today_trades}  W/L: {self.today_wins}/{self.today_losses}\n"
            f"P&L: {self.today_pnl:+.2f} USD"
        )
        log.info(msg)
        tg(msg)

    def _refresh_bias(self):
        today = date.today()
        if self.bias_date == today:
            return
        self.h4_bias   = layer1_h4_bias()
        self.bias_date = today
        log.info("H4 bias: %s", self.h4_bias)

    def _new_m15_candle(self) -> bool:
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 1)
        if bars is None or len(bars) == 0:
            return False
        ct = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc)
        if ct != self._last_m15_time:
            self._last_m15_time = ct
            return True
        return False

    # ── signal ────────────────────────────────────────────────────────────
    def _seek_signal(self):
        """Returns (direction, sl_pips, tp_pips) or None."""
        if self.h4_bias == "NO_TRADE":
            return None
        if self.today_trades >= MAX_TRADES:
            return None

        direction = "BUY" if self.h4_bias == "BUY_ONLY" else "SELL"

        ob = layer2_h1_ob(direction)
        if ob is None:
            log.debug("No H1 OB found")
            return None

        fvg = layer3_h1_fvg(direction)
        if fvg is None:
            log.debug("No H1 FVG found")
            return None

        if not layer4_m15_trigger(direction):
            log.debug("M15 trigger not met")
            return None

        if not spread_ok():
            log.debug("Spread too wide")
            return None

        if news_block():
            log.info("News block active")
            return None

        # SL = beyond OB boundary
        tick = mt5.symbol_info_tick(SYMBOL)
        if not tick:
            return None

        ob_high, ob_low = ob
        if direction == "BUY":
            sl_price = ob_low - pip_to_price(5)
            sl_pips  = (tick.ask - sl_price) / pip_value()
        else:
            sl_price = ob_high + pip_to_price(5)
            sl_pips  = (sl_price - tick.bid) / pip_value()

        sl_pips = max(SL_MIN_PIPS, min(SL_MAX_PIPS, sl_pips))
        tp_pips = sl_pips * RR_MIN

        log.info("Signal %s  SL=%.0f pips  TP=%.0f pips", direction, sl_pips, tp_pips)
        return direction, sl_pips, tp_pips

    # ── management ────────────────────────────────────────────────────────
    def _manage(self):
        if self.ticket is None:
            return

        pos_list = mt5.positions_get(ticket=self.ticket)
        if not pos_list:
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

        # Partial closes
        for pip_target, fraction in PARTIALS:
            if pip_target not in self.partials_hit and pnl_pips >= pip_target:
                close_vol = round(self.initial_lot * fraction, 2)
                close_vol = max(close_vol, mt5.symbol_info(SYMBOL).volume_min)
                if close_vol <= pos.volume:
                    close_partial(self.ticket, close_vol, f"S1_tp{pip_target}")
                    self.partials_hit.append(pip_target)
                    log.info("Partial close at +%d pips, vol=%.2f", pip_target, close_vol)
                    tg(f"Partial close +{pip_target} pips  {close_vol} lots  #{self.ticket}")

                    # BE on first partial
                    if not self.be_set:
                        info = mt5.symbol_info(SYMBOL)
                        new_sl = (
                            self.open_price + pip_to_price(2)
                            if pos.type == 0
                            else self.open_price - pip_to_price(2)
                        )
                        modify_sl(self.ticket, round(new_sl, info.digits))
                        self.be_set = True
                        tg(f"BE set  #{self.ticket}")

        # Force close after MAX_HOLD_H hours
        if self.open_time:
            held_h = (datetime.now(timezone.utc) - self.open_time).total_seconds() / 3600
            if held_h >= MAX_HOLD_H:
                log.info("Max hold time reached (%.1f h), closing.", held_h)
                tg(f"Max hold {held_h:.1f}h — force closing #{self.ticket}")
                close_full(self.ticket, "S1_time_exit")
                self._on_close()

    def _on_close(self):
        if self.ticket is None:
            return
        from_time = datetime.now(timezone.utc) - timedelta(hours=2)
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

        self.ticket       = None
        self.direction    = ""
        self.open_price   = 0.0
        self.open_time    = None
        self.initial_lot  = 0.0
        self.partials_hit = []
        self.be_set       = False

    # ── main loop ─────────────────────────────────────────────────────────
    def _loop(self):
        self._check_daily_reset()

        # always manage open trade regardless of session
        self._manage()

        # daily summary at 17:30
        now = datetime.now(timezone.utc)
        if now.hour == 17 and 30 <= now.minute < 32:
            if self.today_trades > 0:
                self._send_summary()

        if not in_session():
            return

        if not self._new_m15_candle():
            return

        if self.ticket is not None:
            return  # one trade at a time

        self._refresh_bias()

        result = self._seek_signal()
        if result is None:
            return

        direction, sl_pips, tp_pips = result
        ticket = place_order(direction, sl_pips, tp_pips)
        if ticket:
            pos_list = mt5.positions_get(ticket=ticket)
            if pos_list:
                p = pos_list[0]
                self.ticket       = ticket
                self.direction    = direction
                self.open_price   = p.price_open
                self.open_time    = datetime.now(timezone.utc)
                self.initial_lot  = p.volume
                self.partials_hit = []
                self.be_set       = False
                log.info(
                    "Trade opened: %s  ticket %d  @ %.2f  lot %.2f  SL %.0f pips  TP %.0f pips",
                    direction, ticket, p.price_open, p.volume, sl_pips, tp_pips,
                )

    def run(self):
        if not mt5.initialize():
            log.critical("MT5 initialize failed")
            sys.exit(1)

        log.info("S1 Swing-Scalp bot started.")
        tg("S1 Swing-Scalp bot started and ready.")

        try:
            while True:
                try:
                    self._loop()
                except Exception as exc:
                    log.exception("Loop error: %s", exc)
                time.sleep(60)
        finally:
            mt5.shutdown()
            log.info("S1 bot shut down.")


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    S1Bot().run()
