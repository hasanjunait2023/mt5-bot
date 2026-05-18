# encoding: utf-8
"""
Strategy 3 — M1 HFT Sniper (GOLD M1 Momentum Sniper)
======================================================
Source: Notion Master Hub → Strategy 3 page

4-Layer Signal Engine:
  Layer 1 — H1 EMA200 → BUY_ONLY / SELL_ONLY / NO_TRADE for whole session
  Layer 2 — M5 EMA5/13 → confirms direction before each trade
  Layer 3 — M1 EMA5/13 fresh cross + RSI7 (40–60 zone)
  Layer 4 — ATR14 volatility filter (0.50–3.00 on M1)

Entry: ALL 7 checks must pass (any 1 fail = skip candle)
  [1] H1 bias is BUY_ONLY or SELL_ONLY (not NO_TRADE)
  [2] M5 EMA5 > EMA13 (BUY) or < EMA13 (SELL)
  [3] Fresh M1 EMA5/13 crossover
  [4] RSI7 on M1 between 40–60
  [5] ATR14 on M1 between 0.50–3.00
  [6] Spread ≤ 20 pips
  [7] No high-impact news within 15 min

Trade management:
  +4 pips  → SL to breakeven
  TP1 10 pips → close 60%
  TP2 15 pips → close 40%
  15 min time exit

Risk: 0.3% per trade | 30–50 trades/day | Sessions: London + NY open only

Usage:
    python mt5_bridge/strategy3_m1_hft.py
    python mt5_bridge/strategy3_m1_hft.py --demo
    python mt5_bridge/strategy3_m1_hft.py --symbol XAUUSD --risk 0.3
"""
import sys, os, time, argparse, logging, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_account_info

try:
    from news_filter import is_news_blackout
    HAS_NEWS = True
except Exception:
    HAS_NEWS = False

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
SYMBOL       = "XAUUSD"
RISK_PCT     = 0.003          # 0.3% per trade
PIP_SIZE     = 0.1            # XAUUSD: 1 pip = $0.10 price move
PIP_VALUE    = 10.0           # $ per pip per standard lot

EMA_FAST_M1  = 5
EMA_SLOW_M1  = 13
EMA_FAST_M5  = 5
EMA_SLOW_M5  = 13
EMA_TREND_H1 = 200
RSI_PERIOD   = 7
ATR_PERIOD   = 14

H1_NOZONE    = 20             # pips — if price within this of EMA200 → NO_TRADE
RSI_MIN      = 40             # RSI must be in momentum zone
RSI_MAX      = 60
ATR_MIN      = 0.50           # below = ranging
ATR_MAX      = 3.00           # above = news spike
MAX_SPREAD   = 20             # pips
NEWS_BLOCK   = 15             # minutes around high-impact events

TP1_PIPS     = 10
TP2_PIPS     = 15
TP1_CLOSE    = 0.60           # close 60% at TP1
BE_PIPS      = 4
TIME_EXIT_MIN= 15             # force close after 15 min

SESSION_START_H = 7           # 07:00 UTC (London pre-open)
SESSION_END_H   = 17          # 17:00 UTC

MAGIC = 20260300

LOG_PATH   = Path(__file__).parent / "_s3_log.txt"
STATE_PATH = Path(__file__).parent / "_s3_state.json"

handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
try:
    handlers.append(logging.StreamHandler(
        open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
    ))
except Exception:
    pass
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)
log = logging.getLogger("S3_HFT")


# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(n).mean()

def add_indicators(df: pd.DataFrame, fast: int, slow: int,
                   rsi_p: int = 0, atr_p: int = 0) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = _ema(df["Close"], fast)
    df["ema_slow"] = _ema(df["Close"], slow)
    if rsi_p:
        df["rsi"] = _rsi(df["Close"], rsi_p)
    if atr_p:
        df["atr"] = _atr(df, atr_p)
    return df


# ── Data fetch ────────────────────────────────────────────────────────────────

def fetch(symbol: str, tf: int, n: int) -> pd.DataFrame:
    df = fetch_ohlcv(symbol, tf, n)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index, utc=True)
    return df


# ── Layer checks ──────────────────────────────────────────────────────────────

def layer1_h1_bias(symbol: str) -> str:
    """Returns 'BUY_ONLY', 'SELL_ONLY', or 'NO_TRADE'."""
    df = fetch(symbol, mt5.TIMEFRAME_H1, 250)
    if df.empty or len(df) < EMA_TREND_H1:
        return "NO_TRADE"
    ema200 = float(_ema(df["Close"], EMA_TREND_H1).iloc[-1])
    price  = float(df["Close"].iloc[-1])
    dist   = abs(price - ema200) / PIP_SIZE
    if dist < H1_NOZONE:
        return "NO_TRADE"
    return "BUY_ONLY" if price > ema200 else "SELL_ONLY"


def layer2_m5_trend(symbol: str, bias: str) -> bool:
    """True if M5 EMA5/13 aligns with bias."""
    df = fetch(symbol, mt5.TIMEFRAME_M5, 30)
    if df.empty:
        return False
    df = add_indicators(df, EMA_FAST_M5, EMA_SLOW_M5)
    fast = float(df["ema_fast"].iloc[-1])
    slow = float(df["ema_slow"].iloc[-1])
    if bias == "BUY_ONLY":
        return fast > slow
    if bias == "SELL_ONLY":
        return fast < slow
    return False


def layer3_m1_cross(symbol: str, bias: str):
    """
    Returns (is_fresh_cross: bool, rsi_val: float, atr_val: float, bar_time).
    Fresh cross = EMA crossed on the last completed candle (index -2).
    """
    df = fetch(symbol, mt5.TIMEFRAME_M1, 60)
    if len(df) < 20:
        return False, 50.0, 0.0, None
    df = add_indicators(df, EMA_FAST_M1, EMA_SLOW_M1, RSI_PERIOD, ATR_PERIOD)
    df = df.dropna()
    if len(df) < 3:
        return False, 50.0, 0.0, None

    prev_fast  = float(df["ema_fast"].iloc[-3])
    prev_slow  = float(df["ema_slow"].iloc[-3])
    curr_fast  = float(df["ema_fast"].iloc[-2])
    curr_slow  = float(df["ema_slow"].iloc[-2])
    rsi        = float(df["rsi"].iloc[-2])
    atr        = float(df["atr"].iloc[-2])
    bar_time   = df.index[-2]

    cross_up   = prev_fast <= prev_slow and curr_fast > curr_slow
    cross_dn   = prev_fast >= prev_slow and curr_fast < curr_slow

    if bias == "BUY_ONLY"  and cross_up:
        return True, rsi, atr, bar_time
    if bias == "SELL_ONLY" and cross_dn:
        return True, rsi, atr, bar_time
    return False, rsi, atr, bar_time


def get_spread_pips(symbol: str) -> float:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return 99.0
    return (tick.ask - tick.bid) / PIP_SIZE


def news_ok(symbol: str, now: datetime) -> bool:
    if not HAS_NEWS:
        return True
    return not is_news_blackout(symbol, now)


# ── Position sizing ───────────────────────────────────────────────────────────

def calc_lot(balance: float, sl_pips: float) -> float:
    risk_usd = balance * RISK_PCT
    lot = math.floor((risk_usd / (sl_pips * PIP_VALUE)) * 100) / 100
    return max(lot, 0.01)


# ── Order helpers ─────────────────────────────────────────────────────────────

def place_market(symbol: str, direction: int, sl: float, tp1: float,
                 lot: float, demo: bool) -> Optional[int]:
    """direction: 1=BUY, -1=SELL. Returns ticket or None."""
    if demo:
        log.info(f"[DEMO] {'BUY' if direction==1 else 'SELL'} {lot}L SL={sl:.2f} TP1={tp1:.2f}")
        return -1
    tick = mt5.symbol_info_tick(symbol)
    sym  = mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    price = tick.ask if direction == 1 else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
    req = {
        "action":   mt5.TRADE_ACTION_DEAL,
        "symbol":   symbol,
        "volume":   lot,
        "type":     order_type,
        "price":    price,
        "sl":       round(sl, sym.digits),
        "tp":       round(tp1, sym.digits),
        "deviation": 10,
        "magic":    MAGIC,
        "comment":  "S3_HFT",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        return r.order
    log.error(f"Order failed: {mt5.last_error()}")
    return None


def get_position(magic: int = MAGIC) -> Optional[object]:
    pos = mt5.positions_get(symbol=SYMBOL)
    if not pos:
        return None
    for p in pos:
        if p.magic == magic:
            return p
    return None


def modify_sl(ticket: int, new_sl: float, demo: bool):
    if demo:
        return
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket,
                    "symbol": SYMBOL, "sl": new_sl, "tp": pos[0].tp})


def close_partial(ticket: int, lots: float, demo: bool) -> bool:
    if demo:
        log.info(f"[DEMO] Close partial {lots}L")
        return True
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return False
    p = pos[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    r = mt5.order_send({
        "action":   mt5.TRADE_ACTION_DEAL,
        "position": ticket, "symbol": SYMBOL, "volume": lots,
        "type":     mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price":    price, "deviation": 20, "magic": MAGIC, "comment": "S3_partial",
    })
    return r and r.retcode == mt5.TRADE_RETCODE_DONE


def close_position(ticket: int, demo: bool, reason: str = "close"):
    if demo:
        log.info(f"[DEMO] Close position ({reason})")
        return
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "position": ticket,
        "symbol": SYMBOL, "volume": p.volume,
        "type": mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price": price, "deviation": 30, "magic": MAGIC, "comment": f"S3_{reason}",
    })


# ── Bot ───────────────────────────────────────────────────────────────────────

class S3Bot:
    def __init__(self, symbol: str = SYMBOL, risk_pct: float = RISK_PCT,
                 demo: bool = False):
        self.symbol      = symbol
        self.risk_pct    = risk_pct
        self.demo        = demo
        self.bias        = "NO_TRADE"
        self.bias_checked_h = -1
        self.last_bar    = None
        self.pos_ticket  = None
        self.pos_dir     = None
        self.pos_open_time = None
        self.pos_lot     = None
        self.be_moved    = False
        self.tp1_hit     = False
        self.daily_state = {"date": "", "trades": 0, "wins": 0, "losses": 0,
                            "pnl": 0.0, "start_balance": 0.0}
        self.last_daily_summary = -1

    def run(self):
        log.info("=" * 64)
        log.info(f"Strategy 3 — M1 HFT Sniper — {self.symbol}")
        log.info(f"Risk: {self.risk_pct*100:.1f}% | Demo: {self.demo}")
        log.info("=" * 64)
        tg(f"⚡ S3 M1 HFT ONLINE\n{self.symbol} | Risk {self.risk_pct*100:.1f}% | Demo {self.demo}")

        if not self.demo and not connect():
            log.error("MT5 connection failed")
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
            self._roll_day(now)
            h = now.hour

            in_session = SESSION_START_H <= h < SESSION_END_H

            # Daily summary at 17:30 UTC
            if h == 17 and now.minute == 30 and self.last_daily_summary != now.date():
                self._send_daily_summary()
                self.last_daily_summary = now.date()

            if not in_session:
                # Close any lingering positions outside session
                if self.pos_ticket:
                    p = get_position()
                    if p:
                        close_position(p.ticket, self.demo, "session_end")
                        tg(f"🕔 S3 Session ended — position closed | PnL ${p.profit:.2f}")
                    self._reset_trade()
                time.sleep(30)
                continue

            # Refresh H1 bias once per hour
            if h != self.bias_checked_h:
                self.bias = layer1_h1_bias(self.symbol)
                self.bias_checked_h = h
                log.info(f"H1 Bias: {self.bias}")

            # Manage open position
            if self.pos_ticket:
                self._manage(now)
                time.sleep(5)
                continue

            # No position — look for new signal
            if self.bias == "NO_TRADE":
                time.sleep(10)
                continue

            self._seek_signal(now)
            time.sleep(5)

    def _seek_signal(self, now: datetime):
        # Layer 2 — M5 trend
        if not layer2_m5_trend(self.symbol, self.bias):
            return

        # Layer 3 — M1 cross + RSI + ATR
        crossed, rsi, atr, bar_time = layer3_m1_cross(self.symbol, self.bias)
        if not crossed:
            return
        if bar_time == self.last_bar:
            return  # already processed this bar

        # Layer 4 checks
        if not (RSI_MIN <= rsi <= RSI_MAX):
            return
        if not (ATR_MIN <= atr <= ATR_MAX):
            return

        # Spread
        spread = get_spread_pips(self.symbol) if not self.demo else 10.0
        if spread > MAX_SPREAD:
            return

        # News
        if not news_ok(self.symbol, now):
            return

        self.last_bar = bar_time

        # Enter trade
        direction = 1 if self.bias == "BUY_ONLY" else -1
        tick = mt5.symbol_info_tick(self.symbol) if not self.demo else None
        if self.demo:
            entry = 2000.0
        else:
            entry = tick.ask if direction == 1 else tick.bid

        sl_pips = 7
        sl  = entry - sl_pips * PIP_SIZE if direction == 1 else entry + sl_pips * PIP_SIZE
        tp1 = entry + TP1_PIPS * PIP_SIZE if direction == 1 else entry - TP1_PIPS * PIP_SIZE

        acc = get_account_info() if not self.demo else {"balance": 1000.0}
        balance = acc.get("balance", 1000.0)
        lot = calc_lot(balance, sl_pips)

        ticket = place_market(self.symbol, direction, sl, tp1, lot, self.demo)
        if ticket:
            self.pos_ticket    = ticket
            self.pos_dir       = "BUY" if direction == 1 else "SELL"
            self.pos_open_time = now
            self.pos_lot       = lot
            self.be_moved      = False
            self.tp1_hit       = False
            self.daily_state["trades"] += 1
            label = "🟢" if direction == 1 else "🔴"
            log.info(f"{label} S3 {self.pos_dir} {lot}L entry={entry:.2f} "
                     f"SL={sl:.2f} TP1={tp1:.2f} RSI={rsi:.1f} ATR={atr:.2f}")
            tg(
                f"{label} S3 {self.symbol} {self.pos_dir}\n"
                f"Entry: ${entry:.2f} | SL: ${sl:.2f} | TP1: ${tp1:.2f}\n"
                f"Lot: {lot} | RSI7: {rsi:.1f} | ATR: {atr:.2f}\n"
                f"Risk: ${balance * self.risk_pct:.2f}"
            )

    def _manage(self, now: datetime):
        if self.demo:
            if (now - self.pos_open_time).total_seconds() > TIME_EXIT_MIN * 60:
                log.info("[DEMO] Time exit")
                self._reset_trade()
            return

        pos = get_position()
        if pos is None:
            # Closed by SL or TP
            self._on_close(now)
            return

        direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
        tick = mt5.symbol_info_tick(self.symbol)
        cur = tick.bid if direction == "BUY" else tick.ask
        profit_pips = (cur - pos.price_open) / PIP_SIZE if direction == "BUY" \
                      else (pos.price_open - cur) / PIP_SIZE

        # Time exit — 15 min
        mins_open = (now - self.pos_open_time).total_seconds() / 60
        if mins_open >= TIME_EXIT_MIN:
            close_position(pos.ticket, self.demo, "time_exit")
            tg(f"⏱ S3 TIME EXIT\n{direction} {mins_open:.0f}min | PnL ${pos.profit:.2f}")
            self._on_close(now, pos.profit)
            return

        # Breakeven at +4 pips
        if not self.be_moved and profit_pips >= BE_PIPS:
            modify_sl(pos.ticket, pos.price_open, self.demo)
            self.be_moved = True
            log.info(f"BE moved @ entry {pos.price_open:.2f}")

        # TP1 at +10 pips — close 60%
        if not self.tp1_hit and profit_pips >= TP1_PIPS:
            close_lots = math.floor(pos.volume * TP1_CLOSE * 100) / 100
            close_lots = max(close_lots, 0.01)
            if close_partial(pos.ticket, close_lots, self.demo):
                self.tp1_hit = True
                log.info(f"TP1 hit — closed {close_lots}L @ +{TP1_PIPS} pips")
                tg(f"🎯 S3 TP1 +{TP1_PIPS}pips — 60% closed\n${pos.profit:.2f}")
                # Move SL to +6 pips (lock some profit)
                lock_sl = pos.price_open + 6 * PIP_SIZE if direction == "BUY" \
                          else pos.price_open - 6 * PIP_SIZE
                modify_sl(pos.ticket, lock_sl, self.demo)

    def _on_close(self, now: datetime, pnl: float = None):
        if pnl is None:
            # Try to get from deal history
            try:
                deals = mt5.history_deals_get(
                    (now - timedelta(minutes=30)).timestamp(), now.timestamp()
                )
                if deals:
                    last = [d for d in deals if d.magic == MAGIC]
                    pnl = last[-1].profit if last else 0.0
                else:
                    pnl = 0.0
            except Exception:
                pnl = 0.0

        if pnl > 0:
            self.daily_state["wins"]   += 1
            result_icon = "✅"
        else:
            self.daily_state["losses"] += 1
            result_icon = "❌"
        self.daily_state["pnl"] += pnl

        log.info(f"{result_icon} S3 Closed | PnL ${pnl:.2f} | "
                 f"Day: {self.daily_state['wins']}W/{self.daily_state['losses']}L")
        tg(
            f"{result_icon} S3 CLOSED\n"
            f"PnL: ${pnl:.2f}\n"
            f"Day: {self.daily_state['wins']}W / {self.daily_state['losses']}L | "
            f"${self.daily_state['pnl']:.2f}"
        )
        self._reset_trade()

    def _reset_trade(self):
        self.pos_ticket    = None
        self.pos_dir       = None
        self.pos_open_time = None
        self.pos_lot       = None
        self.be_moved      = False
        self.tp1_hit       = False

    def _roll_day(self, now: datetime):
        today = now.strftime("%Y-%m-%d")
        if self.daily_state["date"] != today:
            acc = get_account_info() if not self.demo else {"balance": 1000.0}
            self.daily_state = {
                "date": today, "trades": 0, "wins": 0, "losses": 0,
                "pnl": 0.0, "start_balance": acc.get("balance", 0),
            }

    def _send_daily_summary(self):
        d = self.daily_state
        acc = get_account_info() if not self.demo else {"balance": d["start_balance"]}
        bal = acc.get("balance", 0)
        tg(
            f"📋 S3 DAILY SUMMARY — {d['date']}\n"
            f"Trades: {d['trades']} | {d['wins']}W / {d['losses']}L\n"
            f"Day PnL: ${d['pnl']:.2f}\n"
            f"Balance: ${bal:.2f}"
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Strategy 3 — M1 HFT Sniper")
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--risk",   type=float, default=RISK_PCT * 100,
                        help="Risk %% per trade (default 0.3)")
    parser.add_argument("--demo",   action="store_true")
    parser.add_argument("--check-bias", action="store_true",
                        help="Check current H1 bias and exit")
    args = parser.parse_args()

    if args.check_bias:
        if not connect():
            sys.exit(1)
        bias = layer1_h1_bias(args.symbol)
        m5ok = layer2_m5_trend(args.symbol, bias)
        print(f"H1 Bias  : {bias}")
        print(f"M5 aligned: {m5ok}")
        disconnect()
        return

    bot = S3Bot(symbol=args.symbol, risk_pct=args.risk / 100, demo=args.demo)
    bot.run()


if __name__ == "__main__":
    main()
