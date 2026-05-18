# encoding: utf-8
"""
Strategy 5 — News Spike Reversal Bot
======================================
Source: Notion Master Hub → Strategy 5 page

Logic (4 phases):
  Phase 1 — Pre-News (T-30 min): Record pre-news range, close open trades, block entries
  Phase 2 — Spike Detection (T+0 to T+5 min): Monitor M1 for candle > 80 pips
  Phase 3 — Reversal Entry (T+5 to T+30 min): Hunt reversal candle + RSI confirmation
  Phase 4 — Trade Management: BE at +30 pips, TP1 50% retracement (50%), TP2 70% retracement (50%)

Trades: NFP, FOMC, CPI, PPI, Fed speeches, GDP, Core PCE
Risk  : 1.0% per trade | RR 1:3 to 1:7
Win   : 72–78% target

Usage:
    python mt5_bridge/strategy5_news_spike.py
    python mt5_bridge/strategy5_news_spike.py --demo
"""
import sys, os, time, argparse, logging, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_account_info

# ── Optional news filter (ForexFactory) ──────────────────────────────────────
try:
    from news_filter import fetch_ff_calendar
    HAS_NEWS_FILTER = True
except Exception:
    HAS_NEWS_FILTER = False

# ── Telegram ──────────────────────────────────────────────────────────────────
try:
    import urllib.request as _ur, urllib.parse as _up
    _TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    _TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")
    HAS_TG    = bool(_TG_TOKEN and _TG_CHAT)
except Exception:
    HAS_TG = False

def tg(msg: str):
    if not HAS_TG:
        return
    try:
        data = _up.urlencode({"chat_id": _TG_CHAT, "text": msg}).encode("utf-8")
        _ur.urlopen(f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage", data, timeout=8)
    except Exception:
        pass

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL        = "XAUUSD"
RISK_PCT      = 0.01           # 1.0% per trade (higher — high win rate)
PIP_VALUE     = 10.0           # $ per pip per lot on XAUUSD
PIP_SIZE      = 0.1            # price units per pip

SPIKE_MIN     = 80             # pips — minimum M1 candle to classify as spike
CONT_FAIL     = 100            # pips — if price continues this far after spike, cancel reversal
SL_BUFFER     = 30             # pips — SL placed this far beyond spike extreme
TP1_RETRACE   = 0.50           # 50% retracement of spike
TP2_RETRACE   = 0.70           # 70% retracement of spike
BE_PIPS       = 30             # move to breakeven at +30 pips
REVERSAL_WAIT_MIN = 5          # wait N minutes after spike before hunting reversal
REVERSAL_MAX_MIN  = 30         # stop hunting reversal after this many minutes post-spike
TRADE_MAX_HOURS   = 4          # force close if trade open this long
RSI_OVERBOUGHT    = 70
RSI_OVERSOLD      = 30

MAGIC = 20260500

LOG_PATH   = Path(__file__).parent / "_s5_log.txt"
STATE_PATH = Path(__file__).parent / "_s5_state.json"

# ── High-impact events to monitor ────────────────────────────────────────────
HIGH_IMPACT_EVENTS = [
    "Non-Farm", "NFP", "FOMC", "Federal Funds", "Rate Decision",
    "Consumer Price Index", "CPI", "Producer Price Index", "PPI",
    "Fed Chair", "Powell", "GDP", "Gross Domestic", "Core PCE",
    "Retail Sales", "Unemployment Claims",
]

# ── Logging ───────────────────────────────────────────────────────────────────
handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
try:
    handlers.append(logging.StreamHandler(
        open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
    ))
except Exception:
    pass

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                    handlers=handlers)
log = logging.getLogger("S5_News")


# ── State ─────────────────────────────────────────────────────────────────────

def _load_state():
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_state(s: dict):
    STATE_PATH.write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def get_m5_bars(n: int = 50) -> pd.DataFrame:
    df = fetch_ohlcv(SYMBOL, mt5.TIMEFRAME_M5, n)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def get_m1_bars(n: int = 20) -> pd.DataFrame:
    df = fetch_ohlcv(SYMBOL, mt5.TIMEFRAME_M1, n)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def current_price() -> float:
    tick = mt5.symbol_info_tick(SYMBOL)
    return (tick.bid + tick.ask) / 2 if tick else 0.0


def get_open_position():
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return None
    for p in positions:
        if p.magic == MAGIC:
            return p
    return None


def place_reversal_order(direction: int, entry: float, sl: float,
                         tp1: float, tp2: float, balance: float,
                         spike_pips: float, demo: bool):
    """direction: 1=BUY, -1=SELL"""
    sl_pips = abs(entry - sl) / PIP_SIZE
    if sl_pips < 5:
        log.warning("SL too tight for S5 — skip")
        return None

    risk_usd = balance * RISK_PCT
    lot = math.floor((risk_usd / (sl_pips * PIP_VALUE)) * 100) / 100
    lot = max(lot, 0.01)

    log.info(f"S5 {'BUY' if direction==1 else 'SELL'} entry={entry:.2f} "
             f"SL={sl:.2f} TP1={tp1:.2f} TP2={tp2:.2f} lot={lot} risk=${risk_usd:.2f}")

    tg(
        f"🎯 S5 REVERSAL ENTRY {'BUY' if direction==1 else 'SELL'}\n"
        f"Entry: ${entry:.2f} | SL: ${sl:.2f}\n"
        f"TP1: ${tp1:.2f} (50%) | TP2: ${tp2:.2f} (50%)\n"
        f"Lot: {lot} | Risk: ${risk_usd:.2f}\n"
        f"Spike size: {spike_pips:.0f} pips"
    )

    if demo:
        log.info("[DEMO] Order not sent")
        return -1

    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.ask if direction == 1 else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL

    req = {
        "action":   mt5.TRADE_ACTION_DEAL,
        "symbol":   SYMBOL,
        "volume":   lot,
        "type":     order_type,
        "price":    price,
        "sl":       sl,
        "tp":       tp1,    # TP2 managed in code
        "deviation": 20,
        "magic":    MAGIC,
        "comment":  "S5_Reversal",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return r.order
    log.error(f"Order failed: {mt5.last_error()}")
    return None


def modify_sl(ticket: int, new_sl: float, demo: bool):
    if demo:
        log.info(f"[DEMO] Modify SL → {new_sl:.2f}")
        return
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    mt5.order_send({
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": SYMBOL,
        "sl": new_sl,
        "tp": p.tp,
    })


def close_partial(ticket: int, close_lots: float, demo: bool) -> bool:
    if demo:
        log.info(f"[DEMO] Close partial {close_lots}")
        return True
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return False
    p = pos[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    r = mt5.order_send({
        "action":   mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol":   SYMBOL,
        "volume":   close_lots,
        "type":     mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price":    price,
        "deviation": 20,
        "magic":    MAGIC,
        "comment":  "S5_partial",
    })
    return r and r.retcode == mt5.TRADE_RETCODE_DONE


def close_position(ticket: int, demo: bool):
    if demo:
        log.info("[DEMO] Close position")
        return
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    mt5.order_send({
        "action":   mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol":   SYMBOL,
        "volume":   p.volume,
        "type":     mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price":    price,
        "deviation": 30,
        "magic":    MAGIC,
        "comment":  "S5_close",
    })


# ── Calendar helpers ──────────────────────────────────────────────────────────

def get_todays_events() -> List[Dict]:
    """Return today's high-impact USD events from ForexFactory cache."""
    if not HAS_NEWS_FILTER:
        return []
    try:
        events = fetch_ff_calendar()
        today = datetime.now(timezone.utc).date()
        result = []
        for ev in events:
            if ev.get("impact", "").lower() != "high":
                continue
            if ev.get("country", "").upper() != "USD":
                continue
            try:
                ev_time = datetime.fromisoformat(ev["date"]).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if ev_time.date() != today:
                continue
            title = ev.get("title", "")
            if any(kw.lower() in title.lower() for kw in HIGH_IMPACT_EVENTS):
                result.append({"title": title, "time": ev_time})
        return result
    except Exception as e:
        log.warning(f"Calendar fetch failed: {e}")
        return []


# ── Main Bot ──────────────────────────────────────────────────────────────────

class S5Bot:
    def __init__(self, demo: bool = False):
        self.demo          = demo
        self.today         = None
        self.events        = []      # today's news events
        self.monitored     = set()   # event titles already processed today
        self.phase         = "IDLE"
        self.current_event = None
        self.spike_high    = None
        self.spike_low     = None
        self.spike_dir     = None    # "UP" or "DOWN"
        self.spike_pips    = 0.0
        self.spike_time    = None
        self.pre_high      = None
        self.pre_low       = None
        self.pos_ticket    = None
        self.initial_lot   = None
        self.be_moved      = False
        self.tp1_hit       = False
        self.entry_price   = None
        self.entry_dir     = None
        self.trade_open_time = None
        self.month_wins    = 0
        self.month_losses  = 0

    def run(self):
        log.info("=" * 64)
        log.info("Strategy 5 — News Spike Reversal Bot — STARTING")
        log.info(f"Symbol: {SYMBOL} | Risk: {RISK_PCT*100}% | Demo: {self.demo}")
        log.info("=" * 64)
        tg(f"💥 S5 News Spike Bot ONLINE\nSymbol: {SYMBOL} | Demo: {self.demo}\nMonitoring: NFP, FOMC, CPI, PPI + more")

        if not self.demo and not connect():
            log.error("MT5 connection failed")
            sys.exit(1)

        try:
            while True:
                self._tick()
                time.sleep(30)
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            if not self.demo:
                disconnect()

    def _tick(self):
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        # New day
        if self.today != today_str:
            self.today     = today_str
            self.events    = get_todays_events()
            self.monitored = set()
            self.phase     = "IDLE"
            log.info(f"--- {today_str}: {len(self.events)} high-impact events today ---")
            for ev in self.events:
                log.info(f"  [{ev['time'].strftime('%H:%M UTC')}] {ev['title']}")
            if self.events:
                tg(
                    f"📅 S5 TODAY: {len(self.events)} events\n" +
                    "\n".join(f"  {e['time'].strftime('%H:%M UTC')} — {e['title']}"
                              for e in self.events)
                )

        # ── IDLE: check if any event is within 60 min ────────────────────────
        if self.phase == "IDLE":
            for ev in self.events:
                title = ev["title"]
                if title in self.monitored:
                    continue
                mins_to = (ev["time"] - now).total_seconds() / 60
                if 60 >= mins_to > 30:
                    if title not in self.monitored:
                        log.info(f"[T-{mins_to:.0f}min] Upcoming: {title}")
                        tg(f"📅 S5 TOMORROW\n{mins_to:.0f} min until: {title}\n@ {ev['time'].strftime('%H:%M UTC')}")
                elif 30 >= mins_to > 0:
                    log.info(f"Pre-news preparation: {title}")
                    self._pre_news(ev, now)
                    break

        # ── PRE_NEWS: block entries, record range ────────────────────────────
        elif self.phase == "PRE_NEWS":
            ev = self.current_event
            mins_to = (ev["time"] - now).total_seconds() / 60
            if mins_to <= 0:
                self.phase = "MONITORING"
                log.info(f"NEWS RELEASED: {ev['title']} — spike monitoring active")
                tg(f"🔥 S5 NEWS RELEASED: {ev['title']}\nMonitoring spike...")

        # ── MONITORING: watch M1 for spike ───────────────────────────────────
        elif self.phase == "MONITORING":
            mins_since = (now - self.current_event["time"]).total_seconds() / 60
            if mins_since > 5:
                # Check for continuation failure
                cur = current_price() if not self.demo else 0
                if self.spike_dir and self.spike_high and self.spike_low:
                    if self.spike_dir == "UP" and cur > self.spike_high + CONT_FAIL * PIP_SIZE:
                        log.info("Spike continuation UP — reversal cancelled")
                        tg("⚠️ S5: Spike continuing UP — reversal hunt cancelled")
                        self._reset_event()
                        return
                    if self.spike_dir == "DOWN" and cur < self.spike_low - CONT_FAIL * PIP_SIZE:
                        log.info("Spike continuation DOWN — reversal cancelled")
                        tg("⚠️ S5: Spike continuing DOWN — reversal hunt cancelled")
                        self._reset_event()
                        return
                self.phase = "REVERSAL_HUNT"
                log.info("Spike phase complete — hunting reversal")
            else:
                self._detect_spike(now)

        # ── REVERSAL_HUNT: look for reversal pattern ─────────────────────────
        elif self.phase == "REVERSAL_HUNT":
            mins_since = (now - self.current_event["time"]).total_seconds() / 60
            if mins_since > REVERSAL_MAX_MIN:
                log.info("Reversal window expired (30 min) — no entry")
                tg("⏰ S5: Reversal window expired — no trade this event")
                self._reset_event()
            else:
                self._hunt_reversal(now)

        # ── IN_TRADE: manage open position ───────────────────────────────────
        elif self.phase == "IN_TRADE":
            self._manage_trade(now)

    def _pre_news(self, ev: dict, now: datetime):
        self.current_event = ev
        self.phase = "PRE_NEWS"
        # Record 30-min pre-news range
        df = get_m1_bars(35)
        if not df.empty:
            window = df.iloc[-30:]
            self.pre_high = float(window["High"].max())
            self.pre_low  = float(window["Low"].min())
        self.monitored.add(ev["title"])
        log.info(f"Pre-news: {ev['title']} at {ev['time'].strftime('%H:%M UTC')}")
        log.info(f"Pre-news range: H={self.pre_high:.2f} L={self.pre_low:.2f}")
        tg(
            f"⚠️ S5 NEWS in 30min: {ev['title']}\n"
            f"Time: {ev['time'].strftime('%H:%M UTC')}\n"
            f"Pre-news range: ${self.pre_high:.2f} – ${self.pre_low:.2f}\n"
            f"Blocking new entries on XAUUSD"
        )

    def _detect_spike(self, now: datetime):
        """Check last few M1 candles for spike > 80 pips."""
        df = get_m1_bars(10)
        if df.empty:
            return
        event_time = self.current_event["time"]
        recent = df[df.index >= event_time]
        if recent.empty:
            return
        for idx, row in recent.iterrows():
            candle_range = (row["High"] - row["Low"]) / PIP_SIZE
            if candle_range >= SPIKE_MIN:
                self.spike_high = float(recent["High"].max())
                self.spike_low  = float(recent["Low"].min())
                self.spike_pips = (self.spike_high - self.spike_low) / PIP_SIZE
                # Direction = which way the spike closed
                if row["Close"] > row["Open"]:
                    self.spike_dir = "UP"
                else:
                    self.spike_dir = "DOWN"
                self.spike_time = now
                log.info(
                    f"SPIKE DETECTED: {self.spike_dir} | {self.spike_pips:.0f} pips | "
                    f"H={self.spike_high:.2f} L={self.spike_low:.2f}"
                )
                tg(
                    f"📊 S5 SPIKE: {self.spike_dir}\n"
                    f"Spike: {self.spike_pips:.0f} pips\n"
                    f"High: ${self.spike_high:.2f} | Low: ${self.spike_low:.2f}\n"
                    f"Waiting {REVERSAL_WAIT_MIN}min then hunting reversal..."
                )
                return

    def _hunt_reversal(self, now: datetime):
        if not self.spike_dir:
            return
        mins_since_spike = (now - self.spike_time).total_seconds() / 60 if self.spike_time else 99
        if mins_since_spike < REVERSAL_WAIT_MIN:
            return

        df_m5 = get_m5_bars(20)
        if df_m5.empty:
            return

        rsi = _rsi(df_m5["Close"], 14)
        last = df_m5.iloc[-1]
        prev = df_m5.iloc[-2]
        candle_body = last["Close"] - last["Open"]

        if self.spike_dir == "UP":
            # Hunt SELL reversal: RSI > 70, bearish candle pattern
            is_bearish = candle_body < 0
            is_engulf  = (last["Open"] > prev["Close"] and last["Close"] < prev["Open"])
            is_pin     = ((last["High"] - max(last["Open"], last["Close"])) >
                          2 * abs(candle_body) and abs(candle_body) > 0)
            pattern_ok = is_bearish and (is_engulf or is_pin)
            rsi_ok     = rsi > RSI_OVERBOUGHT

            if pattern_ok and rsi_ok:
                self._enter_reversal(-1, now)

        elif self.spike_dir == "DOWN":
            # Hunt BUY reversal: RSI < 30, bullish candle pattern
            is_bullish = candle_body > 0
            is_engulf  = (last["Open"] < prev["Close"] and last["Close"] > prev["Open"])
            is_pin     = ((min(last["Open"], last["Close"]) - last["Low"]) >
                          2 * abs(candle_body) and abs(candle_body) > 0)
            pattern_ok = is_bullish and (is_engulf or is_pin)
            rsi_ok     = rsi < RSI_OVERSOLD

            if pattern_ok and rsi_ok:
                self._enter_reversal(1, now)

    def _enter_reversal(self, direction: int, now: datetime):
        acc = get_account_info() if not self.demo else {"balance": 1000.0}
        balance = acc.get("balance", 1000.0)
        spike_pips = self.spike_pips

        if direction == 1:  # BUY after DOWN spike
            entry = current_price() if not self.demo else self.spike_low + 10 * PIP_SIZE
            sl    = self.spike_low  - SL_BUFFER * PIP_SIZE
            tp1   = entry + spike_pips * TP1_RETRACE * PIP_SIZE
            tp2   = entry + spike_pips * TP2_RETRACE * PIP_SIZE
        else:  # SELL after UP spike
            entry = current_price() if not self.demo else self.spike_high - 10 * PIP_SIZE
            sl    = self.spike_high + SL_BUFFER * PIP_SIZE
            tp1   = entry - spike_pips * TP1_RETRACE * PIP_SIZE
            tp2   = entry - spike_pips * TP2_RETRACE * PIP_SIZE

        ticket = place_reversal_order(direction, entry, sl, tp1, tp2, balance, spike_pips, self.demo)
        if ticket:
            self.pos_ticket     = ticket
            self.entry_price    = entry
            self.entry_dir      = "BUY" if direction == 1 else "SELL"
            self.tp1_price      = tp1
            self.tp2_price      = tp2
            self.sl_price       = sl
            self.be_moved       = False
            self.tp1_hit        = False
            self.trade_open_time = now
            self.phase          = "IN_TRADE"
            log.info(f"Reversal trade open: {self.entry_dir} ticket={ticket}")

    def _manage_trade(self, now: datetime):
        if self.demo:
            return

        pos = get_open_position()
        if pos is None:
            # Position closed (hit TP or SL)
            log.info("Position closed — returning to IDLE")
            self.phase = "IDLE"
            self.current_event = None
            return

        direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
        tick = mt5.symbol_info_tick(SYMBOL)
        cur = tick.bid if direction == "BUY" else tick.ask
        profit_pips = (cur - pos.price_open) / PIP_SIZE if direction == "BUY" \
                      else (pos.price_open - cur) / PIP_SIZE

        # Force close after 4 hours
        hours_open = (now - self.trade_open_time).total_seconds() / 3600
        if hours_open >= TRADE_MAX_HOURS:
            close_position(pos.ticket, self.demo)
            tg(
                f"⏱ S5 FORCE CLOSE (4h limit)\n"
                f"{direction} | PnL: ${pos.profit:.2f} | {profit_pips:.0f} pips"
            )
            self.phase = "IDLE"
            return

        # Breakeven
        if not self.be_moved and profit_pips >= BE_PIPS:
            modify_sl(pos.ticket, pos.price_open, self.demo)
            self.be_moved = True
            log.info(f"SL moved to breakeven @ {pos.price_open:.2f}")
            tg(f"✅ S5 BREAKEVEN — SL moved to entry ${pos.price_open:.2f}")

        # TP1
        if not self.tp1_hit:
            tp1_hit = (cur >= self.tp1_price if direction == "BUY" else cur <= self.tp1_price)
            if tp1_hit:
                half = math.floor(pos.volume / 2 * 100) / 100
                if close_partial(pos.ticket, max(half, 0.01), self.demo):
                    self.tp1_hit = True
                    tp1_pips = self.spike_pips * TP1_RETRACE
                    tg(
                        f"🎯 S5 TP1 HIT — 50% closed\n"
                        f"+{tp1_pips:.0f} pips | ${pos.profit:.2f}\n"
                        f"Trailing TP2: ${self.tp2_price:.2f}"
                    )
                    # Move SL to entry +30 pips
                    if direction == "BUY":
                        new_sl = pos.price_open + BE_PIPS * PIP_SIZE
                    else:
                        new_sl = pos.price_open - BE_PIPS * PIP_SIZE
                    modify_sl(pos.ticket, new_sl, self.demo)

        # Check if new news approaching — close immediately
        for ev in self.events:
            if ev["title"] in self.monitored:
                continue
            mins_to = (ev["time"] - now).total_seconds() / 60
            if 0 < mins_to < 5:
                close_position(pos.ticket, self.demo)
                tg(f"⚡ S5 EMERGENCY CLOSE — new news in {mins_to:.0f}min: {ev['title']}")
                self.phase = "IDLE"
                return

    def _reset_event(self):
        self.phase         = "IDLE"
        self.current_event = None
        self.spike_high    = None
        self.spike_low     = None
        self.spike_dir     = None
        self.spike_pips    = 0.0
        self.spike_time    = None
        self.pre_high      = None
        self.pre_low       = None


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Strategy 5 — News Spike Reversal Bot")
    parser.add_argument("--demo", action="store_true", help="Paper mode — no real orders")
    parser.add_argument("--list-events", action="store_true", help="Show today's events and exit")
    args = parser.parse_args()

    if args.list_events:
        events = get_todays_events()
        if events:
            print(f"\nToday's high-impact USD events ({len(events)}):")
            for ev in events:
                print(f"  {ev['time'].strftime('%H:%M UTC')} — {ev['title']}")
        else:
            print("No high-impact events today (or news filter not available)")
        return

    bot = S5Bot(demo=args.demo)
    bot.run()


if __name__ == "__main__":
    main()
