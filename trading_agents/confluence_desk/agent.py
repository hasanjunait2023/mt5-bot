"""Confluence Desk — live trading agent (two strategies, one desk).

Ports two MQL5 EAs that passed a 2-year MT5 Strategy Tester backtest into the
python/bridge live framework so they run on the VPS, journal by magic, and show on
the fleet dashboard like every other agent:

  • S13  5-Way Confluence   — XAUUSD, H1 decisions  (ST PF 1.56, +$1,254, 5% DD)
  • S19  Confluence Pullback — EURUSD, M15 + H1 trend (ST PF 1.47, +$582, 2% DD)

Each strategy keeps its own magic so per-strategy P&L attributes cleanly. Decisions
are on CLOSED bars, exactly like the EAs. Demo-execute (real fills on the demo
account) — the backtest is the edge proof; this is the live-data soak before any
real-money gate.

Usage:
  python -m trading_agents.confluence_desk.agent
  python -m trading_agents.confluence_desk.agent --risk 0.5 --dd 6.0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from trading_agents.scalp.indicators import ema, atr, rsi  # battle-tested, reused
from trading_agents.risk_limits import dd_usd_breached, daily_dd_usd_limit

LOG_DIR = BASE_DIR / "logs" / "confluence"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "_agent.log"
STATE_PATH = LOG_DIR / "_agent_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("Confluence.Desk")

try:
    from trading_agents import telegram_hq as _tghq
    _TG_ON = True
except Exception:
    _tghq = None
    _TG_ON = False

try:
    from trading_agents.trade_journal import open_trade as _journal_open
    _JOURNAL = True
except Exception:
    _JOURNAL = False
    def _journal_open(*a, **kw):  # type: ignore
        pass

POLL_INTERVAL_S = 30
_INVALID_FILL = 10030

# ── Strategy catalog ──────────────────────────────────────────────────────────
# Each strategy re-validated on its own 2yr data before going live (port-divergence
# guard). max_day is PER SYMBOL.
#   S13: XAUUSD H1 — port PF 1.50 ≈ EA 1.56 → LIVE.
#   S19: port is symbol-sensitive — GBPUSD PF 1.87, USDJPY PF 1.71 (LIVE), but
#        EURUSD only 0.94 (dropped). Matches the EA's own note (JPY/GBP strong).
STRATS = {
    "S13": {"symbols": ["XAUUSD"], "tf": "H1", "magic": 20261300, "max_day": 3,
            "max_spread_pts": 400, "name": "5-Way Confluence", "live": True},
    "S19": {"symbols": ["GBPUSD", "USDJPY"], "tf": "M15", "magic": 20261900, "max_day": 6,
            "max_spread_pts": 30, "name": "Confluence Pullback", "live": True},
}


def _tg(msg: str, level: str = "INFO") -> None:
    if _TG_ON and _tghq is not None:
        try:
            _tghq.send("confluence", msg, level=level)
        except Exception:
            pass


# ── Indicators not in scalp.indicators (computed at a bar shift) ──────────────
def _ema_series(vals: list[float], period: int) -> list[float]:
    if len(vals) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(vals[:period]) / period]
    for v in vals[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out  # aligned so out[-1] = EMA at vals[-1]


def _macd(closes: list[float], fast=12, slow=26, sig=9):
    """Return (macd, signal, hist) at the last value of `closes`."""
    ef, es = _ema_series(closes, fast), _ema_series(closes, slow)
    if not ef or not es:
        return None
    n = min(len(ef), len(es))
    macd_line = [ef[-n + i] - es[-n + i] for i in range(n)]
    sg = _ema_series(macd_line, sig)
    if not sg:
        return None
    macd_v = macd_line[-1]
    sig_v = sg[-1]
    return macd_v, sig_v, macd_v - sig_v


def _adx_di(highs, lows, closes, period=14):
    """Wilder ADX + directional indices at the last bar. Returns (adx,+di,-di)."""
    n = len(closes)
    if n < period * 2 + 2:
        return None
    tr, pdm, ndm = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    # Wilder smoothing
    def _wilder(x):
        s = sum(x[:period])
        out = [s]
        for v in x[period:]:
            s = s - s / period + v
            out.append(s)
        return out
    atr_s, pdm_s, ndm_s = _wilder(tr), _wilder(pdm), _wilder(ndm)
    m = min(len(atr_s), len(pdm_s), len(ndm_s))
    dx = []
    for i in range(m):
        a = atr_s[-m + i] or 1e-9
        pdi = 100 * pdm_s[-m + i] / a
        ndi = 100 * ndm_s[-m + i] / a
        denom = (pdi + ndi) or 1e-9
        dx.append(100 * abs(pdi - ndi) / denom)
    if len(dx) < period:
        return None
    adx = sum(dx[-period:]) / period
    a = atr_s[-1] or 1e-9
    return adx, 100 * pdm_s[-1] / a, 100 * ndm_s[-1] / a


def _stoch_kd(highs, lows, closes, kp=14, ksmooth=3, dp=3):
    """Stochastic %K (smoothed) and %D series tail. Returns (K_list, D_list)."""
    n = len(closes)
    if n < kp + ksmooth + dp:
        return None
    raw = []
    for i in range(kp - 1, n):
        hh = max(highs[i - kp + 1:i + 1]); ll = min(lows[i - kp + 1:i + 1])
        raw.append(100 * (closes[i] - ll) / ((hh - ll) or 1e-9))
    ksm = [sum(raw[i - ksmooth + 1:i + 1]) / ksmooth for i in range(ksmooth - 1, len(raw))]
    d = [sum(ksm[i - dp + 1:i + 1]) / dp for i in range(dp - 1, len(ksm))]
    return ksm, d


# ── Bridge plumbing (mirrors scalp/agent.py) ─────────────────────────────────
def _mt5_connect() -> bool:
    from mt5_bridge import bridge_client as mt5
    if mt5.initialize():
        acc = mt5.account_info()
        if acc:
            log.info("MT5 connected: #%s @ %s | $%.2f equity", acc.login, acc.server, acc.equity)
            return True
    log.error("MT5 init failed: %s", mt5.last_error())
    return False


def _is_demo(acc) -> bool:
    s = (getattr(acc, "server", "") or "").lower()
    return any(k in s for k in ("trial", "demo", "test", "practice", "contest"))


def _fetch_bars(symbol: str, tf_str: str, n: int) -> Optional[dict]:
    from mt5_bridge import bridge_client as mt5
    tf_map = {"M1": mt5.TIMEFRAME_M1, "M3": mt5.TIMEFRAME_M3, "M5": mt5.TIMEFRAME_M5,
              "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
    rates = mt5.copy_rates_from_pos(symbol, tf_map.get(tf_str, mt5.TIMEFRAME_M15), 0, n)
    if rates is None or len(rates) < 220:
        return None
    return {
        "time":  [int(r["time"]) for r in rates],
        "open":  [float(r["open"]) for r in rates],
        "high":  [float(r["high"]) for r in rates],
        "low":   [float(r["low"]) for r in rates],
        "close": [float(r["close"]) for r in rates],
    }


def _has_open(symbol: str, magic: int) -> bool:
    from mt5_bridge import bridge_client as mt5
    pos = mt5.positions_get(symbol=symbol)
    return pos is not None and any(p.magic == magic for p in pos)


def _calc_lots(symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    from mt5_bridge import bridge_client as mt5
    acc, sym = mt5.account_info(), mt5.symbol_info(symbol)
    if acc is None or sym is None:
        return 0.0
    sl_dist = abs(entry - stop)
    if sl_dist < sym.point or sym.trade_tick_size <= 0:
        return 0.0
    value_lot = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0:
        return 0.0
    lots = round((acc.equity * risk_pct / 100.0) / value_lot / sym.volume_step) * sym.volume_step
    cap = (acc.equity * 0.02) / value_lot                       # 2% hard cap
    return round(max(sym.volume_min, min(lots, sym.volume_max, cap)), 2)


def _place_order(symbol, side, sl, tp, risk_pct, magic, strat) -> Optional[tuple]:
    from mt5_bridge import bridge_client as mt5
    tick, sym = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    entry = tick.ask if side == "BUY" else tick.bid
    if abs(entry - sl) < sym.point * 5:
        log.warning("%s: SL too tight, skip", strat); return None
    lots = _calc_lots(symbol, entry, sl, risk_pct)
    if lots <= 0:
        log.warning("%s: lot=0, skip", strat); return None
    fm = int(getattr(sym, "filling_mode", 0) or 0)
    fills = ([mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN] if fm & 1
             else [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN] if fm & 2
             else [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC])
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
           "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
           "price": entry, "sl": round(sl, sym.digits), "tp": round(tp, sym.digits),
           "deviation": 20, "magic": magic, "comment": f"Confluence_{strat}",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": fills[0]}
    res = mt5.order_send(req); fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and fi < len(fills):
        req["type_filling"] = fills[fi]; fi += 1; res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER %s %s/%s @ %.5f SL=%.5f TP=%.5f lots=%.2f", side, symbol, strat, entry, sl, tp, lots)
        _tg(f"Confluence {strat} {side} {symbol} @ {entry:.5f} SL={sl:.5f} TP={tp:.5f} lots={lots}")
        return int(res.order), lots, entry
    log.error("%s: order FAILED retcode=%s", strat, res.retcode if res else "None")
    return None


# ── Signals (faithful ports; decide on the last CLOSED bar) ──────────────────
def _s13_signal(b: dict) -> Optional[dict]:
    """5-Way Confluence on XAUUSD H1. shift1=last closed, shift2=prev."""
    c = b["close"][:-1]; o = b["open"][:-1]; h = b["high"][:-1]; lo = b["low"][:-1]
    if len(c) < 210:
        return None
    e9, e20, e50, e200 = (ema(c, 9), ema(c, 20), ema(c, 50), ema(c, 200))
    c1, o1, h1, l1 = c[-1], o[-1], h[-1], lo[-1]
    rng = h1 - l1
    if rng <= 0 or c1 <= 0:
        return None
    m1 = _macd(c); m2 = _macd(c[:-1])
    if not m1 or not m2:
        return None
    hist1, hist2 = m1[2], m2[2]
    r1 = rsi(c, 14); a1 = atr(h, lo, c, 14)
    if a1 <= 0:
        return None
    stack_up = e9 > e20 > e50 > e200
    stack_dn = e9 < e20 < e50 < e200
    spread_up = (e9 - e50) / c1 > 0.003
    spread_dn = (e50 - e9) / c1 > 0.003
    macd_bull = m1[0] > 0 and m1[0] > m1[1] and hist1 > hist2
    macd_bear = m1[0] < 0 and m1[0] < m1[1] and hist1 < hist2
    near20 = abs(c1 - e20) / c1 < 0.005
    strong = abs(c1 - o1) > rng * 0.50
    buy = stack_up and spread_up and macd_bull and 45 < r1 < 65 and near20 and strong and c1 > o1
    sell = stack_dn and spread_dn and macd_bear and 35 < r1 < 55 and near20 and strong and c1 < o1
    if not buy and not sell:
        return None
    min_sl = a1 * 0.50
    if buy:
        dist = max(c1 - e50, min_sl)
        return {"side": "BUY", "sl": c1 - dist, "tp": c1 + dist * 2.5}
    dist = max(e50 - c1, min_sl)
    return {"side": "SELL", "sl": c1 + dist, "tp": c1 - dist * 2.5}


def _s19_signal(b: dict, h1_close200: float) -> Optional[dict]:
    """Confluence Pullback on EURUSD M15 (+ H1 EMA200 trend, session-gated)."""
    c = b["close"][:-1]; o = b["open"][:-1]; hi = b["high"][:-1]; lo = b["low"][:-1]
    if len(c) < 60:
        return None
    e21 = ema(c, 21); r1 = rsi(c, 14); a1 = atr(hi, lo, c, 14)
    if a1 <= 0:
        return None
    adx = _adx_di(hi, lo, c, 14)
    st = _stoch_kd(hi, lo, c, 14, 3, 3)
    if not adx or not st or adx[0] < 22.0:
        return None
    pdi, ndi = adx[1], adx[2]
    k, d = st
    if len(k) < 3 or len(d) < 3:
        return None
    k1, k2, d1, d2 = k[-1], k[-2], d[-1], d[-2]
    c1, o1, h1b, l1b = c[-1], o[-1], hi[-1], lo[-1]
    rng = max(h1b - l1b, 1e-9)
    body = abs(c1 - o1) / rng
    pull = abs(c1 - e21) <= 0.6 * a1
    up = c1 > h1_close200
    buyX = k2 < 25 and k2 <= d2 and k1 > d1 and pdi > ndi
    selX = k2 > 75 and k2 >= d2 and k1 < d1 and ndi > pdi
    buy = up and pull and buyX and 40 <= r1 <= 68 and c1 > o1 and body >= 0.30
    sell = (not up) and pull and selX and 32 <= r1 <= 60 and c1 < o1 and body >= 0.30
    if not buy and not sell:
        return None
    sld = 1.5 * a1
    if buy:
        return {"side": "BUY", "sl": c1 - sld, "tp": c1 + 2.0 * sld}
    return {"side": "SELL", "sl": c1 + sld, "tp": c1 - 2.0 * sld}


def _in_session(t_unix: int) -> bool:
    h = datetime.fromtimestamp(t_unix, tz=timezone.utc).hour
    return (7 <= h < 12) or (13 <= h < 17)


# ── State ─────────────────────────────────────────────────────────────────────
def _write_state(mode, stats, equity, dd_pct, symbols):
    try:
        STATE_PATH.write_text(json.dumps({
            "agent": "Confluence Desk", "mode": mode, "account": "demo",
            "symbols": symbols, "strat_stats": stats,
            "equity": round(equity, 2), "daily_loss_pct": round(dd_pct, 2),
            "trades_today": sum(s["trades_today"] for s in stats.values()),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────
def run(risk_pct: float, dd_limit: float) -> None:
    from mt5_bridge import bridge_client as mt5
    if not _mt5_connect():
        log.error("No MT5 — aborting"); sys.exit(1)
    acc = mt5.account_info()
    if acc is None:
        log.error("No account — aborting"); sys.exit(1)
    is_demo = _is_demo(acc)
    start_balance = acc.balance
    day = datetime.now(timezone.utc).date()
    stats = {s: {"trades": 0, "trades_today": 0, "live": STRATS[s]["live"],
                 "symbol": ",".join(STRATS[s]["symbols"]), "name": STRATS[s]["name"]} for s in STRATS}
    last_bar: dict = {}     # (sid, symbol) -> last closed bar time
    td: dict = {}           # (sid, symbol) -> trades opened today
    halted = False
    all_syms = sorted({sym for c in STRATS.values() for sym in c["symbols"]})

    log.info("=== Confluence Desk online === %s | risk %.1f%% | DD %.1f%% | account=%s",
             " ".join(f"{s}:{'/'.join(STRATS[s]['symbols'])}" for s in STRATS), risk_pct, dd_limit,
             "DEMO" if is_demo else "REAL")
    _tg(f"🎯 Confluence Desk ONLINE — S13 (XAUUSD H1) + S19 (GBPUSD/USDJPY M15) | risk {risk_pct}% | DD {dd_limit}%")

    while True:
        try:
            acc = mt5.account_info()
            if acc is None:
                log.warning("account_info None — retry 60s"); time.sleep(60); mt5.initialize(); continue
            equity = acc.equity

            # daily roll + DD guard
            today = datetime.now(timezone.utc).date()
            if today != day:
                day = today; start_balance = acc.balance; halted = False
                td.clear()
                for s in stats:
                    stats[s]["trades_today"] = 0
            dd_pct = max((start_balance - equity) / start_balance * 100, 0.0) if start_balance > 0 else 0.0
            breached, dd_usd = dd_usd_breached(start_balance, equity)
            if not halted and breached:
                halted = True
                log.warning("Daily DD $%.2f >= $%.2f — HALT for day", dd_usd, daily_dd_usd_limit())
                _tg(f"Confluence Desk HALTED — daily DD ${dd_usd:.2f}", level="WARNING")
            if halted:
                _write_state("HALTED", stats, equity, dd_pct, all_syms)
                time.sleep(300); continue

            for sid, cfg in STRATS.items():
                tf, magic = cfg["tf"], cfg["magic"]
                for sym in cfg["symbols"]:
                    key = (sid, sym)
                    bars = _fetch_bars(sym, tf, 320)
                    if not bars:
                        continue
                    bar_t = bars["time"][-2]                       # last CLOSED bar
                    if bar_t <= last_bar.get(key, 0):
                        continue
                    last_bar[key] = bar_t
                    if _has_open(sym, magic) or td.get(key, 0) >= cfg["max_day"]:
                        continue
                    # spread guard
                    tick = mt5.symbol_info_tick(sym); syminfo = mt5.symbol_info(sym)
                    if tick and syminfo and syminfo.point > 0:
                        if (tick.ask - tick.bid) / syminfo.point > cfg["max_spread_pts"]:
                            continue

                    if sid == "S13":
                        sig = _s13_signal(bars)
                    else:
                        if not _in_session(bar_t):
                            continue
                        h1 = _fetch_bars(sym, "H1", 260)
                        if not h1:
                            continue
                        sig = _s19_signal(bars, ema(h1["close"][:-1], 200))
                    if not sig:
                        continue

                    log.info("SIGNAL %s %s/%s SL=%.5f TP=%.5f", sig["side"], sym, sid, sig["sl"], sig["tp"])
                    if not cfg["live"]:
                        log.info("[HELD] %s not live — signal logged, no order", sid)
                        continue
                    res = _place_order(sym, sig["side"], sig["sl"], sig["tp"], risk_pct, magic, sid)
                    if res:
                        ticket, lots, fill = res
                        stats[sid]["trades"] += 1
                        stats[sid]["trades_today"] += 1
                        td[key] = td.get(key, 0) + 1
                        if _JOURNAL:
                            _journal_open(ticket=ticket, symbol=sym, direction=sig["side"],
                                          entry_price=fill, sl=sig["sl"], tp=sig["tp"], volume=lots,
                                          source="Confluence", strategies=[sid],
                                          agent="Confluence.Desk", rationale=f"strategy={sid}")

            _write_state("SCANNING", stats, equity, dd_pct, all_syms)
            time.sleep(POLL_INTERVAL_S)
        except Exception as e:  # never let the loop die
            log.error("loop error: %s", e)
            time.sleep(POLL_INTERVAL_S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--risk", type=float, default=0.5, help="Risk %% equity per trade")
    ap.add_argument("--dd", type=float, default=6.0, help="Daily DD %% halt")
    a = ap.parse_args()
    run(a.risk, a.dd)


if __name__ == "__main__":
    main()
