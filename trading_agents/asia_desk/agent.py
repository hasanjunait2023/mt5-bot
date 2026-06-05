"""
Asia Desk — live demo agent for the Asian Range Fade strategy (S1).

Validated edge (2.1yr M15, real cost, in+out-of-sample): Asian-session mean
reversion on JPY pairs. USDJPY PF 1.60/oos 1.46, AUDJPY 1.47/oos 1.40. See
STRATEGY_SPECS.md (S1) + backtest.py. Non-JPY crosses had no edge → JPY only.

Logic (mirrors backtest.py s1_fade EXACTLY so live == tested):
  • Asian range = high/low of 00:00–02:00 UTC.
  • Entry window 02:00–07:00 UTC. RSI(14) must be 30–70 (skip if trending).
  • Touch support → long: SL = low − 12 pips, TP = low + 0.70·width.
  • Touch resistance → short: SL = high + 12 pips, TP = high − 0.70·width.
  • One position per symbol (this magic) at a time; max N entries/symbol/day.
  • Flatten all this-magic positions at 07:00 UTC (London breaks the range).

Demo account, runs on VPS via bridge_client HTTP shim (same as iconic/scalp).

    python -m trading_agents.asia_desk.agent --pairs USDJPY AUDJPY --risk 0.5
"""
import sys, os, time, json, argparse, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "mt5_bridge"))

from trading_agents.risk_limits import dd_usd_breached, daily_dd_usd_limit

MAGIC = 20260800                      # Asia Desk fade
RANGE_H0, RANGE_H1 = 0, 2             # Asian range build window (UTC)
ENTRY_H0, ENTRY_H1 = 2, 7            # entry window (UTC)
FLATTEN_H = 7                         # force-close all positions at/after this UTC hour
TP_FRAC = 0.70                        # target = this fraction of range width
SL_PIPS = 12                          # (legacy) fixed-pip stop, JPY only
SL_ATR = 1.0                          # volatility stop: SL = edge ∓ SL_ATR*ATR(14)
                                      # — required so gold/silver/BTC stops scale to price

STATE_DIR = BASE_DIR / "logs" / "asia_desk"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "_state.json"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("asia_desk")

try:
    from trading_agents import telegram_hq as _tghq
    def tg_alert(msg, level="INFO"):
        try: _tghq.send(msg, topic="live")
        except Exception: pass
except Exception:
    def tg_alert(msg, level="INFO"): pass

try:
    from trading_agents.trade_journal import open_trade as _journal_open, close_trade as _journal_close
except Exception:
    def _journal_open(*a, **kw): pass
    def _journal_close(*a, **kw): pass

PIP = {"USDJPY": 0.01, "AUDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01,
       "NZDJPY": 0.01, "AUDUSD": 0.0001, "XAUUSD": 0.1, "XAGUSD": 0.01,
       "BTCUSD": 1.0}


def _pip(sym):
    return PIP.get(sym, 0.0001)


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50)


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"].shift()
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def get_m15(mt5, symbol, count=400):
    rates = mt5.copy_rates_from_pos(symbol, "M15", 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["hour"] = df["ts"].dt.hour
    df["date"] = df["ts"].dt.date
    df["rsi"] = rsi(df["close"])
    df["atr"] = atr(df)
    return df


def today_range(df):
    """High/low of the 00:00–02:00 UTC window for the latest date present."""
    today = df["date"].iloc[-1]
    w = df[(df["date"] == today) & (df["hour"] >= RANGE_H0) & (df["hour"] < RANGE_H1)]
    if len(w) < 2:
        return None
    return float(w["high"].max()), float(w["low"].min())


def has_open(mt5, symbol):
    pos = mt5.positions_get(symbol=symbol)
    return bool(pos) and any(p.magic == MAGIC for p in pos)


def calc_lots(mt5, symbol, entry, sl, risk_pct):
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
    lots = round((risk_usd / value_lot) / sym.volume_step) * sym.volume_step
    cap = (acc.equity * 0.02) / value_lot
    return round(max(sym.volume_min, min(lots, sym.volume_max, cap)), 2)


def place_order(mt5, symbol, direction, sl, tp, risk_pct):
    tick, sym = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return False
    digits = sym.digits
    if direction == 1:
        otype, entry = mt5.ORDER_TYPE_BUY, tick.ask
    else:
        otype, entry = mt5.ORDER_TYPE_SELL, tick.bid
    if abs(entry - sl) < sym.point * 5:
        log.warning(f"  {symbol}: SL too tight, skip"); return False
    lots = calc_lots(mt5, symbol, entry, sl, risk_pct)
    if lots <= 0:
        log.warning(f"  {symbol}: lot=0, skip"); return False

    fm = int(getattr(sym, "filling_mode", 0) or 0)
    if fm & 1:
        fills = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    elif fm & 2:
        fills = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
    else:
        fills = [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
        "type": otype, "price": entry, "sl": round(sl, digits), "tp": round(tp, digits),
        "deviation": 10, "magic": MAGIC, "comment": "AsiaFade",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": fills[0],
    }
    res = mt5.order_send(req); fi = 1
    while (res is None or res.retcode == 10030) and fi < len(fills):
        req["type_filling"] = fills[fi]; fi += 1; res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"  {symbol}: order FAILED retcode={res.retcode if res else 'None'}")
        return False
    dname = "BUY" if direction == 1 else "SELL"
    acc = mt5.account_info()
    log.info(f"  >> {symbol} {dname} {lots}L @ {entry:.{digits}f} "
             f"SL={sl:.{digits}f} TP={tp:.{digits}f} Eq=${acc.equity:.2f}")
    try:
        _journal_open(ticket=res.order, symbol=symbol, direction=dname,
                      entry_price=entry, sl=round(sl, digits), tp=round(tp, digits),
                      volume=lots, source="AsiaFade", strategies=["Asian Range Fade"],
                      agent="asia_desk", backend="mt5_direct")
    except Exception:
        pass
    tg_alert(f"{'🟢' if direction == 1 else '🔴'} AsiaFade {symbol} {dname}\n"
             f"Entry {entry:.{digits}f} | SL {sl:.{digits}f} | TP {tp:.{digits}f}\n"
             f"Lot {lots} | Eq ${acc.equity:.2f}")
    return True


def flatten(mt5, symbols):
    """Close all this-magic positions (called at/after FLATTEN_H UTC)."""
    pos = mt5.positions_get()
    if not pos:
        return
    for p in pos:
        if p.magic != MAGIC:
            continue
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            continue
        otype = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == 0 else tick.ask
        sym = mt5.symbol_info(p.symbol)
        fm = int(getattr(sym, "filling_mode", 0) or 0)
        fill = mt5.ORDER_FILLING_FOK if fm & 1 else (mt5.ORDER_FILLING_IOC if fm & 2 else mt5.ORDER_FILLING_RETURN)
        mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                        "volume": p.volume, "type": otype, "position": p.ticket,
                        "price": price, "deviation": 20, "magic": MAGIC,
                        "comment": "AsiaFade flat", "type_filling": fill})
        log.info(f"  flat {p.symbol} #{p.ticket} (pre-London)")


def write_state(mt5, symbols, daily, ranges):
    try:
        acc = mt5.account_info()
        pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": "asia_desk", "strategy": "Asian Range Fade (S1)",
            "symbols": symbols, "magic": MAGIC,
            "equity": round(acc.equity, 2) if acc else None,
            "balance": round(acc.balance, 2) if acc else None,
            "open_positions": [{"symbol": p.symbol, "dir": "BUY" if p.type == 0 else "SELL",
                                "volume": p.volume, "entry": p.price_open,
                                "sl": p.sl, "tp": p.tp, "profit": p.profit} for p in pos],
            "daily_trades": daily, "ranges": ranges,
            "session_window_utc": f"{ENTRY_H0:02d}:00-{FLATTEN_H:02d}:00",
        }, open(STATE_PATH, "w"), indent=2)
    except Exception as e:
        log.debug(f"write_state: {e}")


def secs_to_next_m15():
    now = datetime.now(timezone.utc)
    mins = (15 - now.minute % 15)
    nxt = (now.replace(second=0, microsecond=0) + timedelta(minutes=mins))
    return max(5.0, (nxt - now).total_seconds() + 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+",
                    default=["XAUUSD", "BTCUSD", "AUDJPY", "USDJPY", "XAGUSD", "EURJPY", "GBPJPY"])
    ap.add_argument("--risk", type=float, default=0.5)
    ap.add_argument("--max-td", type=int, default=4, help="max entries/symbol/day")
    ap.add_argument("--dry", action="store_true", help="log signals, place NO orders")
    args = ap.parse_args()
    global place_order, flatten
    if args.dry:
        _po, _fl = place_order, flatten
        place_order = lambda *a, **k: (log.info(f"  [DRY] would place: {a[1]} dir={a[2]} sl={a[3]:.3f} tp={a[4]:.3f}") or True)
        flatten = lambda *a, **k: log.info("  [DRY] would flatten")

    import bridge_client as mt5
    log.info(f"Asia Desk start | pairs={args.pairs} risk={args.risk}% magic={MAGIC}")
    for s in args.pairs:
        try: mt5.symbol_select(s, True)
        except Exception: pass

    daily, cur_date, prev_pos, flat_done, start_bal = {}, None, {}, None, None
    while True:
        try:
            now = datetime.now(timezone.utc)
            today = now.date()
            acc = mt5.account_info()
            if today != cur_date:
                daily, cur_date, flat_done = {s: 0 for s in args.pairs}, today, False
                if acc is not None:
                    start_bal = acc.balance
                log.info(f"New day {today} — daily reset")
            if start_bal is None and acc is not None:
                start_bal = acc.balance

            # Daily $ drawdown halt (AGENT_DAILY_DD_USD, default $200) — no new entries
            halted = False
            if acc is not None and start_bal:
                halted, dd_usd = dd_usd_breached(start_bal, acc.equity)
                if halted:
                    log.warning("Asia Desk daily DD $%.2f >= $%.2f — no new entries",
                                dd_usd, daily_dd_usd_limit())

            # journal closes
            cur = {p.ticket: {"symbol": p.symbol, "sl": p.sl, "tp": p.tp,
                              "entry": p.price_open}
                   for p in (mt5.positions_get() or []) if p.magic == MAGIC}
            for tk in set(prev_pos) - set(cur):
                try:
                    deals = mt5.history_deals_get(position=tk)
                    cd = next((d for d in (deals or []) if d.entry == 1), None)
                    if cd:
                        pnl = cd.profit + cd.swap + cd.commission
                        _journal_close(ticket=tk, exit_price=cd.price, pnl=pnl,
                                       outcome="CLOSED",
                                       close_time=datetime.fromtimestamp(cd.time, tz=timezone.utc).isoformat())
                        log.info(f"  [journal] #{tk} closed PnL=${pnl:+.2f}")
                except Exception:
                    pass
            prev_pos = cur

            ranges = {}
            hour = now.hour

            # flatten before London (once per day)
            if hour >= FLATTEN_H and not flat_done:
                flatten(mt5, args.pairs); flat_done = True

            if ENTRY_H0 <= hour < ENTRY_H1 and not halted:
                for sym in args.pairs:
                    try:
                        df = get_m15(mt5, sym)
                        if df is None or len(df) < 30:
                            continue
                        rng = today_range(df)
                        if not rng:
                            continue
                        hi, lo = rng; width = hi - lo
                        ranges[sym] = {"high": hi, "low": lo, "width": round(width, 5)}
                        if width <= 0 or has_open(mt5, sym) or daily.get(sym, 0) >= args.max_td:
                            continue
                        last = df.iloc[-1]
                        a = last["atr"]
                        if not (30 <= last["rsi"] <= 70) or a <= 0 or a != a:
                            continue
                        # volatility-scaled stop (works across FX/metals/crypto)
                        if last["low"] <= lo:          # touch support → long
                            if place_order(mt5, sym, 1, lo - SL_ATR * a, lo + TP_FRAC * width, args.risk):
                                daily[sym] = daily.get(sym, 0) + 1
                        elif last["high"] >= hi:       # touch resistance → short
                            if place_order(mt5, sym, -1, hi + SL_ATR * a, hi - TP_FRAC * width, args.risk):
                                daily[sym] = daily.get(sym, 0) + 1
                    except Exception as e:
                        log.error(f"  {sym}: {e}")

            write_state(mt5, args.pairs, daily, ranges)
        except Exception as e:
            log.error(f"loop error: {e}")
        time.sleep(secs_to_next_m15())


if __name__ == "__main__":
    main()
