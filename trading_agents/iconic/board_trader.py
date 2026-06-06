"""Iconic Board Trader — the whole-board autonomous system.

See docs/ICONIC_BOARD_SYSTEM_PLAN.md. Replaces the single-pair agent with the
board-level system Navin teaches: scan the whole 28-pair board → currency
strength → leader + group roll-over → book the leader → monitor/manage → close.

Phase status:
  P1 ✅ scan board → strength → classify_group → board state
  P2 ✅ HARD group-roll-over gate (leaders_only + require_group_rollover)
  P3 ✅ execution on demo + correlation-aware exposure cap (1/group, max 3, 1% each)
  P4 ✅ management (scale-out / stop-to-zero / group-congestion exit)
  P5 ⏳ Eclipse scale-IN (gate lifted: P7 PASSED — PF 2.05, WR 50%, 10 trades, 83d H1)
  P7 ✅ board backtest — H1 FULL: PF 2.05, WR 50%, E[R]=+0.445, 10 trades (2000 bars)

Run:
  python -m trading_agents.iconic.board_trader --once          # one scan, print + write state, no orders
  python -m trading_agents.iconic.board_trader --dry           # loop, decide + write state, NO orders
  python -m trading_agents.iconic.board_trader                 # loop + execute on the (demo) account
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "mt5_bridge"))

from trading_agents.iconic import board as board_mod
from trading_agents.iconic.engine import IconicEngine
from trading_agents.iconic.correlation import split_pair, to_scale7
from trading_agents.risk_limits import agent_dd_breached, daily_dd_usd_limit

LOG_DIR    = BASE_DIR / "logs" / "iconic"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH   = LOG_DIR / "_board_log.txt"
STATE_PATH = LOG_DIR / "_board_state.json"
DAILY_PATH = LOG_DIR / "_board_daily.json"
POS_PATH   = LOG_DIR / "_board_positions.json"   # per-ticket management state
# Canonical health + fleet file (orchestrator health + dashboard /fleet both read
# this path). The board must keep it fresh or the service flaps + fleet shows stale.
AGENT_PATH = LOG_DIR / "_agent_state.json"

MAGIC           = 20260700      # Iconic magic (shared lineage; board is the new owner)
SETUP_TF        = "H1"
PULLBACK_TF     = "M15"
BARS_H1         = 500
BARS_M15        = 400
POLL_INTERVAL_S = 60

RISK_PCT        = 1.0           # % equity risked per board position
DD_LIMIT        = 6.0           # daily drawdown halt %
MAX_CONCURRENT  = 3            # max open board positions
MAX_PER_GROUP   = 1            # leader+sisters are ONE bet → 1 open per dominant currency
_INVALID_FILL   = 10030

# ── P4 management tuning ─────────────────────────────────────────────────────
# Scale-out fractions of the ORIGINAL volume at each engine tp_scale level.
# A-class has 3 levels (hold a runner to the extreme); B-class has 1 (take meat).
SCALE_FRAC_A    = [0.30, 0.30, 0.30]   # leaves ~10% runner for tp_final
SCALE_FRAC_B    = [0.50]               # half off at 1R, rest rides to tp_final
DRAG_BARS       = 6            # setup-TF bars of no-progress → stop-to-zero (BE)
CONGESTION_S7   = 2.0          # |dominant scale7| below this → group reverted → exit
MIN_PARTIAL_LOT = 0.01

# ── P5 Eclipse (home-run scale-IN) — OFF by default ──────────────────────────
# Eclipse pyramids INTO a winning A-class (news-driven) move instead of scaling
# out. P7 backtest passed (PF 2.05) — gate lifted. Enabled on demo only.
ECLIPSE_ENABLED   = True
ECLIPSE_MAX_ADDS  = 2          # max pyramids on top of the initial entry
ECLIPSE_ADD_RISK  = 0.5        # % equity per add (total extra ≤ MAX_ADDS*ADD_RISK)
ECLIPSE_STEP_R    = 1.0        # add each time price advances another 1R in our favour

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("Iconic.Board")

# ── Telegram + journal (best-effort) ────────────────────────────────────────
try:
    from trading_agents import telegram_hq as _tghq
except Exception:
    _tghq = None

def _tg(msg: str, level: str = "INFO") -> None:
    if _tghq is None:
        return
    try:
        _tghq.send("live_trading", msg, level=level, title="Iconic Board")
    except Exception:
        pass

try:
    from trading_agents.trade_journal import open_trade as _journal_open
except Exception:
    def _journal_open(*a, **kw):  # type: ignore
        pass

try:
    from trading_agents.iconic.news_sync import sync as _news_sync
except Exception:
    _news_sync = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_agent_state(*, mode: str, equity: float, dd_pct: float,
                       n_open: int, dry: bool) -> None:
    """Keep _agent_state.json fresh — it is the orchestrator health file AND the
    dashboard /fleet source. symbols = the whole board so the fleet shows the
    28-pair board system, not the retired single pair."""
    try:
        AGENT_PATH.write_text(json.dumps({
            "mode": mode,
            "system": "board",
            "live_mode": not dry,
            "symbols": list(board_mod.BOARD_PAIRS),
            "open_positions": n_open,
            "equity": round(equity, 2),
            "daily_loss_pct": round(dd_pct, 2),
            "updated_at": _utcnow(),
        }, indent=2), encoding="utf-8")
    except Exception:
        log.warning("failed to write agent state")


def _dominant(symbol: str, strength: dict[str, float]) -> Optional[str]:
    """Dominant currency of a pair = the leg with the larger |scale7|."""
    base, quote = split_pair(symbol)
    if not base or not quote:
        return None
    b = abs(to_scale7(strength.get(base, 5.0)))
    q = abs(to_scale7(strength.get(quote, 5.0)))
    return base if b >= q else quote


# ── data ────────────────────────────────────────────────────────────────────
def _fetch(symbol: str, tf, n: int):
    import bridge_client as mt5
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) < 250:
        return None
    df = pd.DataFrame(rates)
    df["ema200"] = df["close"].ewm(alpha=1 / 200, adjust=False).mean()
    if "tick_volume" not in df.columns:
        df["tick_volume"] = df["real_volume"] if "real_volume" in df.columns else 0.0
    return df


def _build_snapshots() -> dict:
    import bridge_client as mt5
    snaps: dict = {}
    for sym in board_mod.BOARD_PAIRS:
        h1 = _fetch(sym, mt5.TIMEFRAME_H1, BARS_H1)
        if h1 is None:
            continue
        m15 = _fetch(sym, mt5.TIMEFRAME_M15, BARS_M15)
        if m15 is None:
            m15 = h1
        closed = h1.iloc[:-1]
        last = closed.iloc[-1]
        align = ("bull" if last["close"] > last["ema200"]
                 else "bear" if last["close"] < last["ema200"] else "none")
        snaps[sym] = {"align": align, "tfs": {SETUP_TF: closed, PULLBACK_TF: m15}}
    return snaps


# ── daily state / DD guard ──────────────────────────────────────────────────
class DailyState:
    def __init__(self, start_balance: float, date):
        self.date = date
        self.start_balance = start_balance

    @classmethod
    def load(cls, balance: float) -> "DailyState":
        today = datetime.now(timezone.utc).date()
        if DAILY_PATH.exists():
            try:
                d = json.loads(DAILY_PATH.read_text())
                if d.get("date") == str(today):
                    return cls(d["start_balance"], today)
            except Exception:
                pass
        inst = cls(balance, today)
        inst.save()
        return inst

    def save(self):
        DAILY_PATH.write_text(json.dumps(
            {"date": str(self.date), "start_balance": self.start_balance}))

    def roll(self, balance: float):
        today = datetime.now(timezone.utc).date()
        if today != self.date:
            self.date, self.start_balance = today, balance
            self.save()

    def dd_pct(self, equity: float) -> float:
        if self.start_balance <= 0:
            return 0.0
        return max((self.start_balance - equity) / self.start_balance * 100, 0.0)


# ── order placement (demo) ───────────────────────────────────────────────────
def _calc_lots(symbol: str, entry: float, stop: float, risk_pct: float) -> float:
    import bridge_client as mt5
    acc, sym = mt5.account_info(), mt5.symbol_info(symbol)
    if acc is None or sym is None:
        return 0.0
    if acc.equity <= 0:
        return 0.0
    risk_usd = acc.equity * risk_pct / 100.0
    sl_dist = abs(entry - stop)
    if sl_dist < sym.point or sym.trade_tick_size <= 0:
        return 0.0
    value_lot = (sl_dist / sym.trade_tick_size) * sym.trade_tick_value
    if value_lot <= 0:
        return 0.0
    lots = risk_usd / value_lot
    lots = round(lots / sym.volume_step) * sym.volume_step
    max_allowed = (acc.equity * 0.02) / value_lot
    return round(max(sym.volume_min, min(lots, sym.volume_max, max_allowed)), 2)


def _place_order(symbol: str, side: str, stop: float, tp: float,
                 risk_pct: float) -> Optional[tuple[int, float, float]]:
    import bridge_client as mt5
    tick, sym = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if tick is None or sym is None:
        return None
    digits = sym.digits
    live_entry = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    if abs(live_entry - stop) < sym.point * 5:
        log.warning("%s SL too tight, skip", symbol)
        return None
    lots = _calc_lots(symbol, live_entry, stop, risk_pct)
    if lots <= 0:
        log.warning("%s lot=0, skip", symbol)
        return None
    fm = int(getattr(sym, "filling_mode", 0) or 0)
    fills = ([mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN] if fm & 1
             else [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN] if fm & 2
             else [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC])
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
           "type": order_type, "price": live_entry, "sl": round(stop, digits),
           "tp": round(tp, digits), "deviation": 10, "magic": MAGIC,
           "comment": "Iconic_Board", "type_time": mt5.ORDER_TIME_GTC,
           "type_filling": fills[0]}
    res = mt5.order_send(req)
    fi = 1
    while (res is None or res.retcode == _INVALID_FILL) and fi < len(fills):
        req["type_filling"] = fills[fi]; fi += 1
        res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDER %s %s @ %.5f SL=%.5f TP=%.5f lots=%.2f",
                 side, symbol, live_entry, stop, tp, lots)
        return int(res.order), lots, live_entry
    log.error("%s order FAILED retcode=%s", symbol, res.retcode if res else "None")
    return None


def _close_position(ticket: int, volume: Optional[float] = None) -> bool:
    """Close a position fully (volume=None) or partially (volume=lots)."""
    import bridge_client as mt5
    req = {"position": int(ticket)}
    if volume and volume > 0:
        req["volume"] = float(volume)
    res = mt5.order_send(req)
    return bool(res and res.retcode == mt5.TRADE_RETCODE_DONE)


def _modify_sl(ticket: int, new_sl: float) -> bool:
    import bridge_client as mt5
    res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                          "position": int(ticket), "sl": float(new_sl)})
    return bool(res and res.retcode == mt5.TRADE_RETCODE_DONE)


# ── per-ticket management state ──────────────────────────────────────────────
def _load_pos() -> dict:
    try:
        if POS_PATH.exists():
            return json.loads(POS_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_pos(d: dict) -> None:
    try:
        POS_PATH.write_text(json.dumps(d, indent=2))
    except Exception:
        log.warning("failed to write board positions state")


# ── connect ───────────────────────────────────────────────────────────────────
def _connect() -> bool:
    try:
        import bridge_client as mt5
        if mt5.initialize():
            acc = mt5.account_info()
            if acc:
                log.info("MT5 connected: #%s @ %s | $%.2f", acc.login, acc.server, acc.equity)
                return True
        log.error("MT5 init failed: %s", mt5.last_error())
    except ImportError:
        log.error("bridge_client unavailable")
    return False


# ── board trader ──────────────────────────────────────────────────────────────
class BoardTrader:
    def __init__(self, *, dry: bool):
        self.dry = dry
        self.engine = IconicEngine(setup_tf=SETUP_TF, pullback_tf=PULLBACK_TF,
                                   m15_entry=True)
        self.scorer = self.engine.scorer

    # open board positions, keyed by symbol → {dom, side}
    def _open_book(self, strength: dict) -> dict[str, dict]:
        import bridge_client as mt5
        out: dict[str, dict] = {}
        pos = mt5.positions_get() or []
        for p in pos:
            if getattr(p, "magic", 0) != MAGIC:
                continue
            side = "BUY" if p.type == 0 else "SELL"
            out[p.symbol] = {"ticket": int(p.ticket), "side": side,
                             "dom": _dominant(p.symbol, strength)}
        return out

    def scan(self, *, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now(timezone.utc)
        snaps = _build_snapshots()
        if not snaps:
            log.warning("no board snapshots")
            return {"running": True, "updated_at": _utcnow(), "n_pairs": 0,
                    "strength": [], "groups": [], "candidates": [], "open": []}

        strength = board_mod.compute_strength(snaps, setup_tf=SETUP_TF)
        scores = self.scorer.classify_group(snaps, strength, now=now)

        groups: dict[str, dict] = {}
        for sym, sc in scores.items():
            if sc.klass not in ("A", "B"):
                continue
            base, quote = split_pair(sym)
            dom = base if abs(sc.base7) >= abs(sc.quote7) else quote
            if not dom:
                continue
            g = groups.setdefault(dom, {"dominant": dom, "side": sc.side,
                                        "members": [], "leader": None})
            g["members"].append({"symbol": sym, "klass": sc.klass,
                                 "score": sc.score, "side": sc.side})
            if sc.is_leader:
                g["leader"] = sym

        signals = self.engine.evaluate(snaps, strength, now=now,
                                       leaders_only=True, require_group_rollover=True)

        open_book = self._open_book(strength)
        # manage existing book first (exits free up exposure slots), then enter
        managed = self._manage(open_book, snaps, strength)
        if managed:
            open_book = self._open_book(strength)   # refresh after any closes
        executed = []
        if not self.dry and signals:
            executed = self._execute(signals, open_book, strength)

        state = {
            "running": True, "updated_at": _utcnow(), "dry": self.dry,
            "n_pairs": len(snaps),
            "strength": board_mod.strength_table(strength),
            "groups": [{**g, "rolled_over": len(g["members"]) >= 2}
                       for g in sorted(groups.values(),
                                       key=lambda x: len(x["members"]), reverse=True)],
            "candidates": [s.to_public() for s in signals],
            "open": [{"symbol": s, **v} for s, v in open_book.items()],
            "executed": executed,
            "managed": managed,
        }
        return state

    def _execute(self, signals, open_book: dict, strength: dict) -> list[dict]:
        """Book leaders with the correlation-aware exposure cap."""
        done = []
        pos_state = _load_pos()
        open_doms = {v["dom"] for v in open_book.values() if v["dom"]}
        n_open = len(open_book)
        for sig in signals:
            sym = sig.symbol
            if sym in open_book:
                continue                                   # already in this pair
            if n_open >= MAX_CONCURRENT:
                log.info("exposure cap %d reached — skip %s", MAX_CONCURRENT, sym)
                break
            dom = _dominant(sym, strength)
            if dom and dom in open_doms:
                log.info("group %s already open — skip %s (1/group)", dom, sym)
                continue
            res = _place_order(sym, sig.side, sig.stop, sig.tp_final, RISK_PCT)
            if res is None:
                continue
            ticket, lots, entry = res
            n_open += 1
            if dom:
                open_doms.add(dom)
            open_book[sym] = {"ticket": ticket, "side": sig.side, "dom": dom}
            # record management state for this ticket (P4)
            pos_state[str(ticket)] = {
                "symbol": sym, "side": sig.side, "klass": sig.klass,
                "entry": entry, "stop": sig.stop, "tp_final": sig.tp_final,
                "tp_scale": list(sig.tp_scale), "orig_volume": lots,
                "scales_taken": [False] * len(sig.tp_scale),
                "sl_at_be": False, "dom": dom, "entry_ts": _utcnow(),
            }
            _tg(f"Iconic Board {sig.klass} {sig.side} {sym} (leader, group {dom}) "
                f"@ {entry:.5f} SL={sig.stop:.5f} TP={sig.tp_final:.5f}")
            try:
                _journal_open(ticket=ticket, symbol=sym, direction=sig.side,
                              entry_price=entry, sl=sig.stop, tp=sig.tp_final,
                              volume=lots, source="IconicBoard",
                              strategies=["IconicBoard", sig.klass],
                              agent="Iconic.Board", confluence_score=sig.score,
                              rationale=f"board leader group={dom} klass={sig.klass}")
            except Exception:
                pass
            done.append({"symbol": sym, "side": sig.side, "klass": sig.klass,
                         "group": dom, "ticket": ticket, "entry": entry})
        _save_pos(pos_state)
        return done

    # ── P4 management of open positions ──────────────────────────────────────
    def _manage(self, open_book: dict, snaps: dict, strength: dict) -> list[dict]:
        """Scale-out 10/20/30 · stop-to-zero on drag · group-congestion / align-flip
        exits. Runs every scan against the live (demo) book. Dry mode skips orders."""
        import bridge_client as mt5
        actions: list[dict] = []
        if self.dry:
            return actions
        pos_state = _load_pos()
        live = {p.symbol: p for p in (mt5.positions_get() or [])
                if getattr(p, "magic", 0) == MAGIC}
        # prune state for tickets no longer open
        live_tickets = {str(int(p.ticket)) for p in live.values()}
        for tk in list(pos_state.keys()):
            if tk not in live_tickets:
                pos_state.pop(tk, None)

        for sym, pos in live.items():
            tk = str(int(pos.ticket))
            st = pos_state.get(tk)
            side = "BUY" if pos.type == 0 else "SELL"
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            px = tick.bid if side == "BUY" else tick.ask
            dom = (st or {}).get("dom") or _dominant(sym, strength)

            # 1) Exit signals (full close) — highest priority.
            align = snaps.get(sym, {}).get("align", "none")
            if (side == "BUY" and align == "bear") or (side == "SELL" and align == "bull"):
                if _close_position(pos.ticket):
                    actions.append({"symbol": sym, "action": "CLOSE", "reason": "ALIGN_FLIP"})
                    pos_state.pop(tk, None); continue
            dom_s7 = abs(to_scale7(strength.get(dom, 5.0))) if dom else 0.0
            if dom and dom_s7 < CONGESTION_S7:
                if _close_position(pos.ticket):
                    actions.append({"symbol": sym, "action": "CLOSE",
                                    "reason": f"GROUP_CONGESTION {dom} s7={dom_s7:.1f}"})
                    pos_state.pop(tk, None); continue

            if st is None:
                continue   # pre-existing position with no scale plan → exits only

            entry = st["entry"]; orig = st["orig_volume"]

            # Eclipse (A-class, home-run): scale IN instead of OUT. Off by default.
            if ECLIPSE_ENABLED and st["klass"] == "A":
                self._eclipse(pos, st, side, px, actions)
                pos_state[tk] = st
                continue

            # 2) Scale-out 10/20/30 at the engine's tp_scale levels.
            fracs = SCALE_FRAC_A if st["klass"] == "A" else SCALE_FRAC_B
            for i, lvl in enumerate(st["tp_scale"]):
                if i >= len(fracs) or st["scales_taken"][i]:
                    continue
                hit = (px >= lvl) if side == "BUY" else (px <= lvl)
                if not hit:
                    continue
                vol = round(orig * fracs[i], 2)
                if vol >= MIN_PARTIAL_LOT and vol < pos.volume and _close_position(pos.ticket, vol):
                    st["scales_taken"][i] = True
                    actions.append({"symbol": sym, "action": "SCALE_OUT",
                                    "level": i + 1, "r": lvl, "vol": vol})
                    if not st["sl_at_be"] and _modify_sl(pos.ticket, entry):
                        st["sl_at_be"] = True
                        actions.append({"symbol": sym, "action": "STOP_TO_ZERO",
                                        "reason": "after first partial"})

            # 3) Stop-to-zero on drag: held many bars, no partial yet, not progressed.
            if not st["sl_at_be"]:
                try:
                    held_bars = self._bars_since(snaps.get(sym), st["entry_ts"])
                except Exception:
                    held_bars = 0
                first_lvl = st["tp_scale"][0] if st["tp_scale"] else None
                not_progressed = first_lvl is not None and (
                    (px < first_lvl) if side == "BUY" else (px > first_lvl))
                if held_bars >= DRAG_BARS and not_progressed and _modify_sl(pos.ticket, entry):
                    st["sl_at_be"] = True
                    actions.append({"symbol": sym, "action": "STOP_TO_ZERO",
                                    "reason": f"drag {held_bars} bars"})

            pos_state[tk] = st

        _save_pos(pos_state)
        return actions

    def _eclipse(self, pos, st: dict, side: str, px: float, actions: list) -> None:
        """Bounded home-run scale-IN (v1): pyramid one ADD_RISK unit each time
        price advances another STEP_R in our favour, capped at MAX_ADDS, trailing
        the base position's SL up to the prior milestone to lock gains. OFF until
        P7 proves positive expectancy — pyramiding a negative edge is ruin."""
        entry, stop = st["entry"], st["stop"]
        risk_unit = abs(entry - stop)
        if risk_unit <= 0:
            return
        adds = st.get("eclipse_adds", 0)
        if adds >= ECLIPSE_MAX_ADDS:
            return
        advance = (px - entry) if side == "BUY" else (entry - px)
        needed = (adds + 1) * ECLIPSE_STEP_R * risk_unit
        if advance < needed:
            return
        # lock level = the prior milestone (entry after the first add)
        lock = (entry + adds * ECLIPSE_STEP_R * risk_unit) if side == "BUY" \
            else (entry - adds * ECLIPSE_STEP_R * risk_unit)
        res = _place_order(st["symbol"], side, lock, st["tp_final"], ECLIPSE_ADD_RISK)
        if res is None:
            return
        add_ticket, lots, _ = res
        st["eclipse_adds"] = adds + 1
        st.setdefault("eclipse_tickets", []).append(add_ticket)
        _modify_sl(pos.ticket, lock)          # trail the base position too
        actions.append({"symbol": st["symbol"], "action": "ECLIPSE_ADD",
                        "n": adds + 1, "lock": round(lock, 5), "ticket": add_ticket})

    @staticmethod
    def _bars_since(snap: Optional[dict], entry_ts: str) -> int:
        """How many closed setup-TF bars since entry_ts (drag detection)."""
        if not snap:
            return 0
        df = snap.get("tfs", {}).get(SETUP_TF)
        if df is None or "time" not in df.columns:
            return 0
        try:
            t0 = datetime.fromisoformat(entry_ts).timestamp()
        except Exception:
            return 0
        times = pd.to_numeric(df["time"], errors="coerce")
        return int((times >= t0).sum())

    def write_state(self, state: dict):
        try:
            STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            log.warning("failed to write board state")


def _print_state(state: dict):
    log.info("Board: %d pairs | open=%d | dry=%s", state["n_pairs"],
             len(state.get("open", [])), state.get("dry"))
    log.info("Strength: %s", "  ".join(
        f"{r['currency']}{r['scale7']:+.1f}" for r in state["strength"]))
    for g in state["groups"]:
        log.info("  group %s %s leader=%s members=%d rolled_over=%s",
                 g["dominant"], g["side"], g.get("leader") or "—",
                 len(g["members"]), g["rolled_over"])
    for c in state["candidates"]:
        log.info("  CANDIDATE %s %s %s/%s score=%.0f", c["side"], c["symbol"],
                 c["klass"], c["type"], c["score"])
    for e in state.get("executed", []):
        log.info("  EXECUTED %s %s group=%s ticket=%s", e["side"], e["symbol"],
                 e["group"], e["ticket"])
    for m in state.get("managed", []):
        log.info("  MANAGE %s %s %s", m.get("action"), m.get("symbol"),
                 {k: v for k, v in m.items() if k not in ("action", "symbol")})
    if not state["candidates"]:
        log.info("  no board candidates this scan")


def run(*, once: bool, dry: bool):
    if not _connect():
        sys.exit(1)
    import bridge_client as mt5
    if _news_sync:
        try: _news_sync()
        except Exception: pass
    acc = mt5.account_info()
    daily = DailyState.load(acc.balance if acc else 0.0)
    bt = BoardTrader(dry=dry)
    log.info("=== Iconic Board Trader === pairs=%d once=%s dry=%s risk=%.1f%% maxpos=%d",
             len(board_mod.BOARD_PAIRS), once, dry, RISK_PCT, MAX_CONCURRENT)
    last_news = time.time()
    while True:
        try:
            acc = mt5.account_info()
            if acc is None:
                log.warning("account_info None — reconnect"); time.sleep(30); _connect(); continue
            daily.roll(acc.balance)
            if _news_sync and time.time() - last_news >= 3 * 3600:
                try: _news_sync()
                except Exception: pass
                last_news = time.time()
            dd = daily.dd_pct(acc.equity)
            breached, dd_usd = agent_dd_breached(mt5, MAGIC)
            halted = breached and not dry
            if halted:
                log.warning("daily DD $%.2f >= $%.2f — HALT new entries", dd_usd, daily_dd_usd_limit())
                state = bt.scan(); state["halted"] = True
            else:
                state = bt.scan()
            bt.write_state(state)
            _write_agent_state(mode="HALTED" if halted else "SCANNING",
                               equity=acc.equity, dd_pct=dd,
                               n_open=len(state.get("open", [])), dry=dry)
            _print_state(state)
        except Exception:
            log.exception("board loop error")
        if once:
            break
        time.sleep(POLL_INTERVAL_S)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Iconic Board Trader")
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry", action="store_true", help="decide + write state, no orders")
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # --once implies dry (a single safe probe); plain run executes on the demo acct.
    run(once=args.once, dry=args.dry or args.once)


if __name__ == "__main__":
    main()
