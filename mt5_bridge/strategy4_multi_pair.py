"""
Strategy 4 — Multi-Pair Parallel Execution Engine
===================================================
Base logic : Strategy 3 (M1 HFT 3-layer) cloned for 5 pairs
Pairs      : XAUUSD · XAGUSD · USDJPY · GBPUSD · EURUSD
Architecture: asyncio — 5 coroutines sharing one MT5 connection

Portfolio risk rules:
  - 0.3% risk per trade
  - Max 1.5% total open risk at any time
  - Max 3 simultaneous trades portfolio-wide
  - Group A (metals XAUUSD/XAGUSD): max 1 trade open
  - Group B (USD USDJPY/EURUSD/GBPUSD): max 2 trades open
  - 5% combined daily DD → halt ALL pairs for the day
  - Correlation block: metals group same direction = blocked

Trade mgmt per trade (mirrors S3):
  BE  at +4 pips
  TP1 60% close at pair TP1, SL → +6 pips
  TP2 40% close at pair TP2
  15-min time exit
  Session guard per pair

Telegram:
  - Trade entry/exit alerts per pair
  - Hourly portfolio summary
  - Daily summary at 17:30 UTC

Magic: 20260400
"""

import asyncio
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional

import MetaTrader5 as mt5
import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  S4  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "_s4_log.txt"), encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("S4")

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")
MAGIC     = 20260400


def tg(msg: str):
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": f"[S4-MULTI]\n{msg}"},
            timeout=10,
        )
    except Exception:
        pass


# ── pair configuration ─────────────────────────────────────────────────────────
@dataclass
class PairConfig:
    symbol:       str
    sl_pips:      float
    tp1_pips:     float
    tp2_pips:     float
    atr_min:      float
    atr_max:      float
    max_spread:   float          # pips
    session_hours: List[tuple]   # list of (start_h, end_h) UTC ranges
    group:        str            # "metals" or "usd"

PAIRS: List[PairConfig] = [
    PairConfig("XAUUSD",  7,  10, 15, 0.50,   3.00,  20, [(8, 17)],            "metals"),
    PairConfig("XAGUSD",  8,  12, 18, 0.03,   0.20,  25, [(8, 17)],            "metals"),
    PairConfig("USDJPY",  8,  12, 18, 0.10,   0.50,  1.5,[(0, 4), (13, 17)],   "usd"),
    PairConfig("GBPUSD", 10,  15, 22, 0.0008, 0.003,  2, [(8, 17)],            "usd"),
    PairConfig("EURUSD",  7,  11, 16, 0.0005, 0.0025, 1, [(7, 17)],            "usd"),
]

PAIR_MAP: Dict[str, PairConfig] = {p.symbol: p for p in PAIRS}

# ── portfolio constants ────────────────────────────────────────────────────────
RISK_PCT          = 0.3
MAX_TOTAL_RISK    = 1.5     # %
MAX_OPEN_TRADES   = 3
MAX_METALS_OPEN   = 1
MAX_USD_OPEN      = 2
MAX_DAILY_DD      = 5.0     # %
NEWS_BLOCK_MIN    = 15
LOOP_SLEEP        = 10      # seconds between each pair's scan
BE_PIPS           = 4
TP1_PARTIAL       = 0.60
TP2_PARTIAL       = 0.40
BE_LOCK_PIPS      = 6
TIME_EXIT_MIN     = 15


# ── shared portfolio state ─────────────────────────────────────────────────────
class PortfolioState:
    def __init__(self):
        self._lock              = asyncio.Lock()
        self.open_trades: Dict[str, Optional[int]] = {p.symbol: None for p in PAIRS}
        self.open_dir:    Dict[str, str]            = {p.symbol: "" for p in PAIRS}
        self.daily_start_equity: float              = 0.0
        self.today_date:  Optional[date]            = None
        self.halted:      bool                      = False
        self.per_pair_stats: Dict[str, dict]        = {
            p.symbol: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            for p in PAIRS
        }
        self._last_hourly: Optional[datetime]       = None

    async def reset_day(self):
        async with self._lock:
            today = date.today()
            if self.today_date == today:
                return
            if self.today_date is not None:
                await asyncio.to_thread(self._send_daily_summary)
            self.today_date         = today
            self.halted             = False
            acct                    = mt5.account_info()
            self.daily_start_equity = acct.equity if acct else 0.0
            for sym in self.per_pair_stats:
                self.per_pair_stats[sym] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            log.info("Portfolio daily reset. Equity %.2f", self.daily_start_equity)

    def _send_daily_summary(self):
        lines = ["Daily Portfolio Summary"]
        total_pnl = 0.0
        for sym, s in self.per_pair_stats.items():
            lines.append(f"  {sym}: {s['wins']}W {s['losses']}L  {s['pnl']:+.2f}")
            total_pnl += s["pnl"]
        lines.append(f"Total P&L: {total_pnl:+.2f} USD")
        tg("\n".join(lines))

    async def check_daily_dd(self) -> bool:
        """Returns True if still within DD limit, False if halted."""
        async with self._lock:
            if self.halted:
                return False
            if self.daily_start_equity <= 0:
                return True
            acct = mt5.account_info()
            if not acct:
                return True
            dd = (self.daily_start_equity - acct.equity) / self.daily_start_equity * 100
            if dd >= MAX_DAILY_DD:
                self.halted = True
                msg = (
                    f"PORTFOLIO DD {dd:.1f}% >= {MAX_DAILY_DD}% — ALL PAIRS HALTED\n"
                    f"Balance: {acct.equity:.2f} (was {self.daily_start_equity:.2f})"
                )
                log.warning(msg)
                tg(msg)
                return False
            return True

    async def can_enter(self, symbol: str, direction: str) -> bool:
        """Check all portfolio constraints before entering a new trade."""
        async with self._lock:
            if self.halted:
                return False

            # count open trades
            open_count    = sum(1 for v in self.open_trades.values() if v is not None)
            metals_open   = sum(1 for s, v in self.open_trades.items()
                                if v is not None and PAIR_MAP[s].group == "metals")
            usd_open      = sum(1 for s, v in self.open_trades.items()
                                if v is not None and PAIR_MAP[s].group == "usd")

            if open_count >= MAX_OPEN_TRADES:
                return False

            cfg = PAIR_MAP[symbol]
            if cfg.group == "metals" and metals_open >= MAX_METALS_OPEN:
                return False
            if cfg.group == "usd"    and usd_open    >= MAX_USD_OPEN:
                return False

            # correlation direction block: if other metal is open in same direction, block
            if cfg.group == "metals":
                for sym, v in self.open_trades.items():
                    if v is not None and PAIR_MAP[sym].group == "metals" and sym != symbol:
                        if self.open_dir.get(sym) == direction:
                            return False  # same-direction metals exposure

            return True

    async def register_trade(self, symbol: str, ticket: int, direction: str):
        async with self._lock:
            self.open_trades[symbol] = ticket
            self.open_dir[symbol]    = direction

    async def close_trade(self, symbol: str, pnl: float):
        async with self._lock:
            self.open_trades[symbol] = None
            self.open_dir[symbol]    = ""
            s = self.per_pair_stats[symbol]
            s["trades"] += 1
            s["pnl"]    += pnl
            if pnl > 0:
                s["wins"]   += 1
            else:
                s["losses"] += 1

    async def hourly_summary(self):
        now = datetime.now(timezone.utc)
        if self._last_hourly and (now - self._last_hourly).total_seconds() < 3600:
            return
        self._last_hourly = now
        acct = mt5.account_info()
        if not acct:
            return
        start = self.daily_start_equity or acct.equity
        pct   = (acct.equity - start) / start * 100 if start else 0
        open_n = sum(1 for v in self.open_trades.values() if v is not None)
        lines  = [
            f"PORTFOLIO STATUS — {now.strftime('%H:%M')} UTC",
            f"Balance: ${acct.equity:.2f} ({pct:+.1f}% today)",
            f"Open: {open_n} trades",
            "By pair today:",
        ]
        for sym, s in self.per_pair_stats.items():
            lines.append(f"  {sym}: {s['wins']}W {s['losses']}L  ${s['pnl']:+.2f}")
        tg("\n".join(lines))


# ── math helpers ──────────────────────────────────────────────────────────────
def pip_val(symbol: str) -> float:
    info = mt5.symbol_info(symbol)
    return info.point * 10 if info else 0.0001


def pip_to_price(symbol: str, pips: float) -> float:
    return pips * pip_val(symbol)


def calc_lot(symbol: str, sl_pips: float) -> float:
    acct = mt5.account_info()
    if not acct:
        return 0.01
    risk     = acct.equity * RISK_PCT / 100
    info     = mt5.symbol_info(symbol)
    if not info:
        return 0.01
    sl_price = sl_pips * pip_val(symbol)
    contract = info.trade_contract_size
    raw      = risk / (sl_price * contract) if sl_price * contract > 0 else info.volume_min
    step     = info.volume_step
    return max(info.volume_min, min(info.volume_max, math.floor(raw / step) * step))


def ema(values: np.ndarray, period: int) -> np.ndarray:
    k = 2 / (period + 1)
    out = np.empty(len(values))
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def atr14(bars) -> float:
    if bars is None or len(bars) < 15:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs[-14:]))


def calc_rsi(closes: np.ndarray, period: int = 7) -> float:
    if len(closes) < period + 1:
        return 50.0
    d = np.diff(closes)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag, al = np.mean(g[-period:]), np.mean(l[-period:])
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


# ── pair-specific signal layers (mirrors S3 logic) ────────────────────────────
def _h1_bias(symbol: str) -> str:
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 220)
    if bars is None or len(bars) < 205:
        return "NO_TRADE"
    closes = np.array([b["close"] for b in bars])
    e200   = ema(closes, 200)
    price  = closes[-1]
    dist   = abs(price - e200[-1]) / pip_val(symbol)
    if dist < 20:
        return "NO_TRADE"
    return "BUY_ONLY" if price > e200[-1] else "SELL_ONLY"


def _m5_trend(symbol: str, direction: str) -> bool:
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 30)
    if bars is None or len(bars) < 15:
        return False
    closes = np.array([b["close"] for b in bars])
    e5, e13 = ema(closes, 5), ema(closes, 13)
    if direction == "BUY":
        return e5[-1] > e13[-1]
    return e5[-1] < e13[-1]


def _m1_cross(symbol: str, direction: str, cfg: PairConfig) -> bool:
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 30)
    if bars is None or len(bars) < 20:
        return False
    closes = np.array([b["close"] for b in bars])
    e5, e13 = ema(closes, 5), ema(closes, 13)

    if direction == "BUY":
        cross = e5[-2] <= e13[-2] and e5[-1] > e13[-1]
    else:
        cross = e5[-2] >= e13[-2] and e5[-1] < e13[-1]
    if not cross:
        return False

    rsi = calc_rsi(closes)
    if not (40 <= rsi <= 60):
        return False

    atr = atr14(bars)
    if not (cfg.atr_min <= atr <= cfg.atr_max):
        return False

    return True


def _spread_ok(symbol: str, cfg: PairConfig) -> bool:
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False
    return (tick.ask - tick.bid) / pip_val(symbol) <= cfg.max_spread


def _in_session(cfg: PairConfig) -> bool:
    h = datetime.now(timezone.utc).hour
    return any(s <= h < e for s, e in cfg.session_hours)


def _news_block(symbol: str) -> bool:
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=8
        )
        if r.status_code != 200:
            return False
        now = datetime.now(timezone.utc)
        for ev in r.json():
            if ev.get("impact") != "High":
                continue
            # pair-specific events
            title = ev.get("title", "").lower()
            cur   = ev.get("currency", "").upper()
            sym   = symbol.upper()
            if cur not in ("USD", "XAU", "XAG", "JPY", "GBP", "EUR"):
                continue
            # only block pairs affected by this currency
            if cur == "EUR" and "EURUSD" not in sym:
                continue
            if cur == "GBP" and "GBPUSD" not in sym:
                continue
            if cur == "JPY" and "USDJPY" not in sym:
                continue
            try:
                ev_dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            if abs((ev_dt - now).total_seconds()) / 60 < NEWS_BLOCK_MIN:
                return True
    except Exception:
        pass
    return False


# ── trade execution helpers ───────────────────────────────────────────────────
def _place_order(symbol: str, direction: str, cfg: PairConfig) -> Optional[int]:
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if not tick or not info:
        return None

    lot    = calc_lot(symbol, cfg.sl_pips)
    sl_d   = pip_to_price(symbol, cfg.sl_pips)
    tp2_d  = pip_to_price(symbol, cfg.tp2_pips)

    if direction == "BUY":
        otype = mt5.ORDER_TYPE_BUY
        price = tick.ask
        sl    = round(price - sl_d,  info.digits)
        tp    = round(price + tp2_d, info.digits)
    else:
        otype = mt5.ORDER_TYPE_SELL
        price = tick.bid
        sl    = round(price + sl_d,  info.digits)
        tp    = round(price - tp2_d, info.digits)

    res = mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         otype,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      f"S4_{symbol[:3]}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        tg(f"ENTRY {symbol} {direction}  {lot} lots @ {price:.5g}\n"
           f"SL {sl:.5g}  TP {tp:.5g}  #{res.order}")
        return res.order
    log.warning("%s order failed: %s", symbol, res)
    return None


def _modify_sl(symbol: str, ticket: int, new_sl: float):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       new_sl,
        "tp":       pos[0].tp,
        "symbol":   symbol,
    })


def _close_partial(symbol: str, ticket: int, volume: float):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    ct = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if p.type == 0 else tick.ask
    mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       round(volume, 2),
        "type":         ct,
        "position":     ticket,
        "price":        price,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      "S4_partial",
        "type_filling": mt5.ORDER_FILLING_IOC,
    })


def _close_full(symbol: str, ticket: int, comment: str = "S4_close"):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p = pos[0]
    ct = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if p.type == 0 else tick.ask
    mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       p.volume,
        "type":         ct,
        "position":     ticket,
        "price":        price,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      comment,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })


def _get_closed_pnl(ticket: int) -> float:
    from_time = datetime.now(timezone.utc) - timedelta(hours=2)
    hist = mt5.history_deals_get(from_time, datetime.now(timezone.utc))
    pnl  = 0.0
    if hist:
        for d in hist:
            if d.position_id == ticket:
                pnl += d.profit
    return pnl


# ── per-pair executor ─────────────────────────────────────────────────────────
class PairExecutor:
    def __init__(self, cfg: PairConfig, portfolio: PortfolioState):
        self.cfg       = cfg
        self.portfolio = portfolio
        self.symbol    = cfg.symbol

        self.ticket:    Optional[int]      = None
        self.direction: str                = ""
        self.open_price: float             = 0.0
        self.open_time: Optional[datetime] = None
        self.init_lot:  float              = 0.0
        self.tp1_hit:   bool               = False
        self.be_set:    bool               = False
        self.h1_bias:   str                = "NO_TRADE"
        self.bias_date: Optional[date]     = None
        self._last_m1_time: Optional[datetime] = None

    def _refresh_bias(self):
        today = date.today()
        if self.bias_date == today:
            return
        self.h1_bias   = _h1_bias(self.symbol)
        self.bias_date = today

    def _new_m1_candle(self) -> bool:
        bars = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, 1)
        if bars is None or len(bars) == 0:
            return False
        ct = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc)
        if ct != self._last_m1_time:
            self._last_m1_time = ct
            return True
        return False

    def _seek_signal(self) -> Optional[str]:
        if self.h1_bias == "NO_TRADE":
            return None
        direction = "BUY" if self.h1_bias == "BUY_ONLY" else "SELL"
        if not _m5_trend(self.symbol, direction):
            return None
        if not _m1_cross(self.symbol, direction, self.cfg):
            return None
        if not _spread_ok(self.symbol, self.cfg):
            return None
        if _news_block(self.symbol):
            return None
        return direction

    def _manage(self) -> Optional[float]:
        """Manage open trade. Returns PnL if closed, else None."""
        if self.ticket is None:
            return None

        pos_list = mt5.positions_get(ticket=self.ticket)
        if not pos_list:
            pnl = _get_closed_pnl(self.ticket)
            self._reset_trade()
            return pnl

        pos  = pos_list[0]
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return None

        pv        = pip_val(self.symbol)
        cur_price = tick.bid if pos.type == 0 else tick.ask
        pnl_pips  = (
            (cur_price - self.open_price) / pv
            if pos.type == 0
            else (self.open_price - cur_price) / pv
        )

        # BE trigger
        if not self.be_set and pnl_pips >= BE_PIPS:
            info   = mt5.symbol_info(self.symbol)
            new_sl = (
                self.open_price + pip_to_price(self.symbol, BE_LOCK_PIPS)
                if pos.type == 0
                else self.open_price - pip_to_price(self.symbol, BE_LOCK_PIPS)
            )
            _modify_sl(self.symbol, self.ticket, round(new_sl, info.digits))
            self.be_set = True
            log.info("%s BE set, ticket %d", self.symbol, self.ticket)

        # TP1 partial close
        if not self.tp1_hit and pnl_pips >= self.cfg.tp1_pips:
            vol = round(self.init_lot * TP1_PARTIAL, 2)
            vol = max(vol, mt5.symbol_info(self.symbol).volume_min)
            if vol <= pos.volume:
                _close_partial(self.symbol, self.ticket, vol)
                self.tp1_hit = True
                tg(f"TP1 {self.symbol} +{self.cfg.tp1_pips} pips  partial {vol} lots  #{self.ticket}")

        # Time exit
        if self.open_time:
            elapsed = (datetime.now(timezone.utc) - self.open_time).total_seconds() / 60
            if elapsed >= TIME_EXIT_MIN:
                _close_full(self.symbol, self.ticket, "S4_time_exit")
                pnl = _get_closed_pnl(self.ticket)
                tg(f"Time exit {self.symbol} after {elapsed:.0f} min  #{self.ticket}")
                self._reset_trade()
                return pnl

        return None

    def _reset_trade(self):
        self.ticket     = None
        self.direction  = ""
        self.open_price = 0.0
        self.open_time  = None
        self.init_lot   = 0.0
        self.tp1_hit    = False
        self.be_set     = False

    async def run_loop(self):
        log.info("%s executor started.", self.symbol)
        while True:
            try:
                await self._tick()
            except Exception as exc:
                log.exception("%s loop error: %s", self.symbol, exc)
            await asyncio.sleep(LOOP_SLEEP)

    async def _tick(self):
        # daily reset is handled centrally; just check halt
        if self.portfolio.halted:
            if self.ticket is not None:
                _close_full(self.symbol, self.ticket, "S4_halt")
                pnl = _get_closed_pnl(self.ticket)
                await self.portfolio.close_trade(self.symbol, pnl)
                self._reset_trade()
            return

        if not await self.portfolio.check_daily_dd():
            return

        if not _in_session(self.cfg):
            if self.ticket is not None:
                _close_full(self.symbol, self.ticket, "S4_session_end")
                pnl = _get_closed_pnl(self.ticket)
                await self.portfolio.close_trade(self.symbol, pnl)
                self._reset_trade()
            return

        # manage existing trade
        pnl = self._manage()
        if pnl is not None:
            await self.portfolio.close_trade(self.symbol, pnl)
            return

        if self.ticket is not None:
            return  # one trade at a time per pair

        if not self._new_m1_candle():
            return

        self._refresh_bias()
        direction = self._seek_signal()
        if direction is None:
            return

        if not await self.portfolio.can_enter(self.symbol, direction):
            log.debug("%s: portfolio capacity blocked entry", self.symbol)
            return

        ticket = _place_order(self.symbol, direction, self.cfg)
        if ticket:
            pos_list = mt5.positions_get(ticket=ticket)
            if pos_list:
                p = pos_list[0]
                self.ticket     = ticket
                self.direction  = direction
                self.open_price = p.price_open
                self.open_time  = datetime.now(timezone.utc)
                self.init_lot   = p.volume
                self.tp1_hit    = False
                self.be_set     = False
                await self.portfolio.register_trade(self.symbol, ticket, direction)
                log.info("%s trade opened %s  ticket %d", self.symbol, direction, ticket)


# ── main runner ───────────────────────────────────────────────────────────────
async def _daily_reset_loop(portfolio: PortfolioState):
    while True:
        await portfolio.reset_day()
        await asyncio.sleep(60)


async def _hourly_summary_loop(portfolio: PortfolioState):
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        if 7 <= now.hour < 18:
            await portfolio.hourly_summary()
        # daily summary at 17:30
        if now.hour == 17 and 30 <= now.minute < 32:
            portfolio._send_daily_summary()


async def main():
    if not mt5.initialize():
        log.critical("MT5 initialize failed")
        sys.exit(1)

    log.info("S4 Multi-Pair Engine started — 5 pairs.")
    tg("S4 Multi-Pair Engine started: XAUUSD · XAGUSD · USDJPY · GBPUSD · EURUSD")

    portfolio  = PortfolioState()
    executors  = [PairExecutor(cfg, portfolio) for cfg in PAIRS]

    tasks = [
        _daily_reset_loop(portfolio),
        _hourly_summary_loop(portfolio),
        *[ex.run_loop() for ex in executors],
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        mt5.shutdown()
        log.info("S4 shut down.")


if __name__ == "__main__":
    asyncio.run(main())
