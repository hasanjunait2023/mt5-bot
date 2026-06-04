# encoding: utf-8
"""
cpp_live_trader.py — live/demo runner for the unified CPP portfolio.
====================================================================

Trades CPP-FX (EURUSD, GBPUSD, USDJPY) on M15 with the hybrid trade-
confirmation agent gating every entry, strict fixed 1:2, 1% equity risk.

It is also the UNIFIED monitoring + safety layer for ALL five mandated
symbols: Gold/Silver keep trading on the repo's validated MQL5 EAs
(S1/S15/S18) inside the same MT5 account; this process

  • enforces a HARD 6% account-level daily-drawdown breaker (equity-based,
    so it covers CPP-FX *and* the gold/silver EAs), and
  • writes a per-day performance file (_cpp_daily.json) aggregating every
    closed deal on the account regardless of which strategy/magic placed
    it — wins, losses, daily P&L, daily DD vs the 6% line — for the
    dashboard daily-performance panel.

Usage:
    python mt5_bridge/cpp_live_trader.py
    python mt5_bridge/cpp_live_trader.py --pairs EURUSD USDJPY --dd 6 --agent veto
"""
import sys, os, time, json, argparse, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "trading_agents"))

from strategies import confluence_pullback as cpp           # noqa: E402
from trade_confirmation_agent import TradeConfirmationAgent  # noqa: E402

CPP_MAGIC   = 20260519
FX_SYMBOLS  = ["EURUSD", "GBPUSD", "USDJPY"]
BARS        = 600                       # M15 bars to pull (>= warmup)
TF          = mt5.TIMEFRAME_M15
TF_H1       = mt5.TIMEFRAME_H1
STATE_PATH  = Path(__file__).parent / "_cpp_state.json"
DAILY_PATH  = Path(__file__).parent / "_cpp_daily.json"
LOG_PATH    = Path(__file__).parent / "_cpp_log.txt"
PARAMS_FILE = Path(__file__).parent.parent / "configs" / "cpp_params.json"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("CPP_Live")

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")


def tg(msg: str):
    if not (_TG_TOKEN and _TG_CHAT):
        return
    try:
        import urllib.request as ur, urllib.parse as up
        ur.urlopen(f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
                   up.urlencode({"chat_id": _TG_CHAT, "text": msg}).encode(),
                   timeout=8)
    except Exception:
        pass


def load_params() -> dict:
    p = dict(cpp.DEFAULT_PARAMS)
    if PARAMS_FILE.exists():
        try:
            ov = json.loads(PARAMS_FILE.read_text(encoding="utf-8"))
            ov.pop("_comment", None)
            ov.pop("per_symbol", None)
            p.update({k: (tuple(v) if isinstance(v, list) else v)
                      for k, v in ov.items()})
        except Exception as e:
            log.warning("bad cpp_params.json (%s) — defaults", e)
    return p


def fetch(symbol: str, tf: int, n: int) -> pd.DataFrame:
    r = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if r is None or len(r) < 60:
        return pd.DataFrame()
    df = pd.DataFrame(r)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


def calc_lots(symbol: str, sl: float, entry: float, risk_pct: float) -> float:
    acc, sym = mt5.account_info(), mt5.symbol_info(symbol)
    if acc is None or sym is None:
        return 0.0
    risk_usd = acc.equity * risk_pct / 100.0
    sl_dist = abs(entry - sl)
    if sl_dist < sym.point or sym.trade_tick_size <= 0:
        return 0.0
    value_lot = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0:
        return 0.0
    lots = round(risk_usd / value_lot / sym.volume_step) * sym.volume_step
    cap = (acc.equity * 0.02) / value_lot
    return round(max(sym.volume_min, min(lots, sym.volume_max, cap)), 2)


def has_cpp_position(symbol: str) -> bool:
    pos = mt5.positions_get(symbol=symbol)
    return bool(pos) and any(p.magic == CPP_MAGIC for p in pos)


def place(symbol: str, setup: cpp.Setup, sl: float, tp: float,
          risk_pct: float) -> bool:
    tick, sym = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return False
    if setup.direction == "BUY":
        otype, entry = mt5.ORDER_TYPE_BUY, tick.ask
    else:
        otype, entry = mt5.ORDER_TYPE_SELL, tick.bid
    lots = calc_lots(symbol, sl, entry, risk_pct)
    if lots <= 0:
        log.warning("  %s lot=0 skip", symbol)
        return False
    fm = getattr(sym, "filling_mode", 0)
    if fm & mt5.SYMBOL_FILLING_FOK:
        fills = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & mt5.SYMBOL_FILLING_IOC:
        fills = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fills = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
           "type": otype, "price": entry, "sl": round(sl, sym.digits),
           "tp": round(tp, sym.digits), "deviation": 15, "magic": CPP_MAGIC,
           "comment": f"CPP {setup.regime[:4]} s{int(setup.score)}",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": fills[0]}
    res = mt5.order_send(req)
    i = 1
    while (res is None or res.retcode == mt5.TRADE_RETCODE_INVALID_FILL) and i < len(fills):
        req["type_filling"] = fills[i]
        i += 1
        res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("  %s order FAILED retcode=%s", symbol,
                  res.retcode if res else None)
        return False
    acc = mt5.account_info()
    log.info("  >> %s: %s %sL @ %.5f SL=%.5f TP=%.5f | %s",
             symbol, setup.direction, lots, entry, sl, tp, setup.reason)
    tg(f"{'🟢' if setup.direction == 'BUY' else '🔴'} CPP {symbol} "
       f"{setup.direction}\n{setup.reason}\nLot {lots} | Eq ${acc.equity:.2f}")
    return True


# ── unified daily performance aggregator (ALL magics) ──────────────────
def write_daily_perf(start_balance: float, dd_limit: float) -> dict:
    """Aggregate every CLOSED deal today across ALL strategies/magics
    (CPP-FX + gold/silver S1/S15/S18) into the dashboard daily file."""
    acc = mt5.account_info()
    if acc is None:
        return {}
    now = datetime.now(timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(day0, now + timedelta(minutes=1)) or []

    closed = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
    closed.sort(key=lambda d: d.time)
    wins = losses = 0
    per_symbol: dict = {}
    run = start_balance
    trough = start_balance
    realized = 0.0
    trades = []
    for d in closed:
        pnl = d.profit + d.commission + d.swap
        realized += pnl
        run += pnl
        trough = min(trough, run)
        if pnl > 0:
            wins += 1
        else:
            losses += 1
        s = per_symbol.setdefault(d.symbol, {"wins": 0, "losses": 0, "pnl": 0.0})
        s["wins" if pnl > 0 else "losses"] += 1
        s["pnl"] = round(s["pnl"] + pnl, 2)
        trades.append({"symbol": d.symbol, "pnl": round(pnl, 2),
                       "time": datetime.fromtimestamp(
                           d.time, timezone.utc).strftime("%H:%M")})

    floating = sum(p.profit for p in (mt5.positions_get() or []))
    equity_low = min(trough, start_balance + realized + min(0.0, floating))
    daily_dd = max((start_balance - equity_low) / start_balance * 100, 0.0) \
        if start_balance > 0 else 0.0
    total = wins + losses
    payload = {
        "date": now.strftime("%Y-%m-%d"),
        "updated": now.isoformat(),
        "start_balance": round(start_balance, 2),
        "balance": round(acc.balance, 2),
        "equity": round(acc.equity, 2),
        "wins": wins, "losses": losses, "trades": total,
        "win_rate": round(wins / total * 100, 1) if total else 0.0,
        "daily_pnl": round(realized, 2),
        "floating_pnl": round(floating, 2),
        "daily_dd_pct": round(daily_dd, 2),
        "dd_limit_pct": dd_limit,
        "dd_breaker_tripped": daily_dd >= dd_limit,
        "target": {"wins": 15, "losses": 6, "dd": dd_limit},
        "target_hit": (wins >= 15 and losses <= 6 and daily_dd <= dd_limit),
        "per_symbol": per_symbol,
        "recent_trades": trades[-25:],
    }
    tmp = DAILY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(DAILY_PATH)
    return payload


def write_state(running: bool, agent_mode: str, breaker: bool, last: dict):
    acc = mt5.account_info()
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "runner": "cpp_live_trader", "running": running,
        "mt5_connected": acc is not None, "agent_mode": agent_mode,
        "dd_breaker_tripped": breaker, "symbols": FX_SYMBOLS,
        "magic": CPP_MAGIC, "last_signals": last,
        "account": ({"login": acc.login, "balance": round(acc.balance, 2),
                     "equity": round(acc.equity, 2)} if acc else {}),
    }
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def secs_to_next_m15() -> float:
    now = datetime.now(timezone.utc)
    m = (now.minute // 15 + 1) * 15
    nxt = now.replace(minute=0, second=2, microsecond=0) + timedelta(minutes=m)
    return max(2.0, (nxt - now).total_seconds())


def run(pairs, dd_limit, agent_mode, risk_pct, poll_sleep):
    if not mt5.initialize():
        log.error("MT5 init failed: %s", mt5.last_error())
        return
    acc = mt5.account_info()
    log.info("Connected #%s @ %s | Equity $%.2f", acc.login, acc.server,
             acc.equity)
    log.info("CPP-FX %s | risk %.1f%% | agent=%s | hard daily DD %.1f%%",
             pairs, risk_pct, agent_mode, dd_limit)
    tg(f"🟢 CPP live runner up\n{pairs} | risk {risk_pct}% | "
       f"agent {agent_mode} | daily DD breaker {dd_limit}%")

    p = load_params()
    agent = TradeConfirmationAgent({"mode": agent_mode})
    day = datetime.now(timezone.utc).date()
    start_balance = acc.balance
    last_bar: dict = {}
    last_sig: dict = {}
    n_today: dict = {}
    recent_losses = 0
    breaker = False

    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.date() != day:
                day = now.date()
                start_balance = mt5.account_info().balance
                n_today, breaker = {}, False
                log.info("New day %s — daily state reset (start $%.2f)",
                         day, start_balance)

            perf = write_daily_perf(start_balance, dd_limit)
            acc = mt5.account_info()
            daily_dd = perf.get("daily_dd_pct", 0.0)

            if daily_dd >= dd_limit and not breaker:
                breaker = True
                log.warning("HARD DAILY DD %.2f%% >= %.1f%% — no new trades "
                            "today (account-wide)", daily_dd, dd_limit)
                tg(f"⚠️ CPP daily DD breaker TRIPPED {daily_dd:.2f}% "
                   f">= {dd_limit}% — new entries halted for {day}")

            for sym in pairs:
                m15 = fetch(sym, TF, BARS)
                h1 = fetch(sym, TF_H1, BARS)
                if m15.empty or h1.empty:
                    continue
                m, h = cpp.prepare(m15, h1, p)
                bar_t = m.index[-2]                       # last CLOSED bar
                if last_bar.get(sym) == bar_t:
                    continue
                last_bar[sym] = bar_t
                row, prev = m.iloc[-2], m.iloc[-3]
                hpos = h.index.searchsorted(bar_t, side="right") - 1
                if hpos < p["htf_ema"]:
                    continue
                setup = cpp.detect(row, prev, h.iloc[hpos], p,
                                   hour=bar_t.hour)
                last_sig[sym] = (setup.reason if setup else None)
                if setup is None or breaker:
                    continue
                if has_cpp_position(sym):
                    continue
                if n_today.get(sym, 0) >= p["max_trades_day"]:
                    continue
                v = agent.evaluate(setup, {"symbol": sym,
                                           "recent_losses": recent_losses})
                log.info("  %s setup -> agent %s x%.2f (%s)", sym,
                         v.decision, v.size_mult, v.rationale)
                if v.decision == "VETO":
                    continue
                entry = float(row["close"])
                sl, tp, _ = cpp.sl_tp(setup, entry, p)
                if place(sym, setup, sl, tp, risk_pct * v.size_mult):
                    n_today[sym] = n_today.get(sym, 0) + 1

            write_state(True, agent_mode, breaker, last_sig)
            time.sleep(min(poll_sleep, secs_to_next_m15()))
        except KeyboardInterrupt:
            log.info("Stopped by user")
            write_state(False, agent_mode, breaker, last_sig)
            break
        except Exception as e:
            log.exception("loop error: %s", e)
            time.sleep(15)

    mt5.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=FX_SYMBOLS)
    ap.add_argument("--dd", type=float, default=20.0,
                    help="hard account-level daily DD breaker %% (default 20)")
    ap.add_argument("--agent", default="veto",
                    choices=["off", "advisory", "veto"])
    ap.add_argument("--risk", type=float, default=1.0)
    ap.add_argument("--poll", type=float, default=60.0)
    a = ap.parse_args()
    run(a.pairs, a.dd, a.agent, a.risk, a.poll)
