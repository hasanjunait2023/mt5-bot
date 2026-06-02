"""Paper Trade Tracker — opens a simulated 1% risk + 1:2 RR scalping trade
for every emitted signal (both classic and improved engines), then watches
MT5 live prices to determine WIN / LOSS / TIMEOUT outcomes.

Outcomes are stored in JSONL so the dashboard can compute, side-by-side:
    system × signal_type → trade count / win rate / total pips / R-multiple

SL/TP sizing:
    SL  = 1.5 × ATR(M5, 14)          ← scalping-friendly stop
    TP  = SL × 2.0                    ← fixed 1:2 reward:risk
    Lot = 1% account risk / SL (pips × pip_value)   (recorded but not enforced)

Timeouts (so stale signals don't sit forever):
    alignment → 24h
    cross     → 4h
    touch     → 8h
    stacked   → 6h
    cross_failed / exit signals are NOT tracked (they're exits, not entries).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from mt5_bridge import bridge_client as mt5
except Exception:                       # noqa: BLE001
    mt5 = None

import pandas as pd

log = logging.getLogger("PaperTracker")

BASE_DIR     = Path(__file__).resolve().parents[2]
TRADES_PATH  = BASE_DIR / "logs" / "signals" / "_paper_trades.jsonl"
OPEN_PATH    = BASE_DIR / "logs" / "signals" / "_paper_open.json"
PERF_PATH    = BASE_DIR / "logs" / "signals" / "_paper_perf.json"

CHECK_INTERVAL_S = 5.0
ACCOUNT_BALANCE  = 10_000.0    # paper account size (USD)
RISK_PCT         = 1.0
RR_RATIO         = 2.0
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 1.5         # SL = ATR * this

TIMEOUT_BY_TYPE = {
    "alignment": 24 * 3600,
    "cross":      4 * 3600,
    "touch":      8 * 3600,
    "stacked":    6 * 3600,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _pip_mult(symbol: str) -> float:
    if symbol.endswith("JPY"):    return 100.0
    if symbol in ("XAUUSD",):     return 10.0
    if symbol in ("XAGUSD",):     return 100.0
    if symbol in ("BTCUSD",):     return 1.0
    if symbol in ("USOIL", "XTIUSD"): return 100.0
    return 10000.0


def _fetch_atr(symbol: str, period: int = ATR_PERIOD) -> Optional[float]:
    if mt5 is None:
        return None
    try:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, period * 4)
        if rates is None or len(rates) < period + 1:
            return None
        df = pd.DataFrame(rates)
        h = df["high"]; l = df["low"]; c = df["close"]
        tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return float(tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1])
    except Exception:
        return None


@dataclass
class PaperTrade:
    trade_id: str
    signal_id: str
    system: str           # "classic" | "improved"
    signal_type: str
    symbol: str
    side: str             # BUY | SELL
    entry_price: float
    sl: float
    tp: float
    risk_pct: float
    rr: float
    sl_pips: float
    tp_pips: float
    timeout_s: float
    opened_ts: str
    opened_epoch: float
    closed_ts: Optional[str] = None
    closed_epoch: Optional[float] = None
    close_price: Optional[float] = None
    outcome: Optional[str] = None     # WIN | LOSS | TIMEOUT
    pips: Optional[float] = None
    r_multiple: Optional[float] = None
    extra: dict = field(default_factory=dict)


class PaperTradeTracker:
    """One global tracker. Inject into both engines so each emitted signal
    opens a simulated trade."""

    def __init__(self):
        self._open: dict[str, PaperTrade] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._load_open()

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="PaperTracker")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ── trade open ───────────────────────────────────────────────────────
    def on_signal(self, signal: dict, *, system: str):
        """Open a paper trade. `signal` is the SignalEvent dict from emit()."""
        sig_type = signal.get("type")
        # Skip exit-style signals
        if sig_type in ("cross_failed",) or signal.get("side") in ("EXIT",):
            return
        if sig_type not in TIMEOUT_BY_TYPE:
            return
        side = signal["side"]
        if side not in ("BUY", "SELL"):
            return
        symbol = signal["symbol"]

        atr = _fetch_atr(symbol)
        if atr is None or atr <= 0:
            log.debug("no ATR for %s — skip paper trade", symbol)
            return
        sl_dist = atr * ATR_MULTIPLIER
        entry = float(signal["price"])
        if side == "BUY":
            sl = entry - sl_dist
            tp = entry + sl_dist * RR_RATIO
        else:
            sl = entry + sl_dist
            tp = entry - sl_dist * RR_RATIO
        mult = _pip_mult(symbol)
        sl_pips = abs(entry - sl) * mult
        tp_pips = abs(tp - entry) * mult

        trade_id = f"{system}-{sig_type}-{symbol}-{int(time.time()*1000)}"
        now = time.time()
        trade = PaperTrade(
            trade_id=trade_id,
            signal_id=signal.get("id", ""),
            system=system, signal_type=sig_type,
            symbol=symbol, side=side,
            entry_price=entry, sl=sl, tp=tp,
            risk_pct=RISK_PCT, rr=RR_RATIO,
            sl_pips=round(sl_pips, 1), tp_pips=round(tp_pips, 1),
            timeout_s=TIMEOUT_BY_TYPE[sig_type],
            opened_ts=_utcnow(), opened_epoch=now,
            extra={"verdict": signal.get("verdict"), "score": signal.get("score"),
                   "correlation": signal.get("correlation")},
        )
        with self._lock:
            self._open[trade_id] = trade
            self._save_open()
        log.info("PAPER OPEN [%s] %s %s %s @ %.5f  SL %.1f / TP %.1f pips",
                 system, sig_type, symbol, side, entry, sl_pips, tp_pips)

    # ── checker loop ─────────────────────────────────────────────────────
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._check_open()
                self._write_perf()
            except Exception:
                log.exception("tracker loop iteration failed")
            self._stop.wait(CHECK_INTERVAL_S)

    def _check_open(self):
        if mt5 is None or not self._open:
            return
        now = time.time()
        to_close: list[tuple[PaperTrade, str, float]] = []
        for tid, t in list(self._open.items()):
            tick = mt5.symbol_info_tick(t.symbol)
            if tick is None:
                continue
            # Conservative: long uses bid (exit), short uses ask
            price = tick.bid if t.side == "BUY" else tick.ask

            hit_tp = (t.side == "BUY" and price >= t.tp) or (t.side == "SELL" and price <= t.tp)
            hit_sl = (t.side == "BUY" and price <= t.sl) or (t.side == "SELL" and price >= t.sl)

            if hit_tp:
                to_close.append((t, "WIN", price))
            elif hit_sl:
                to_close.append((t, "LOSS", price))
            elif now - t.opened_epoch >= t.timeout_s:
                to_close.append((t, "TIMEOUT", price))

        for t, outcome, price in to_close:
            self._close(t, outcome, price)

    def _close(self, t: PaperTrade, outcome: str, price: float):
        mult = _pip_mult(t.symbol)
        pips = (price - t.entry_price) * mult if t.side == "BUY" else (t.entry_price - price) * mult
        r = pips / t.sl_pips if t.sl_pips else 0.0
        t.closed_ts = _utcnow()
        t.closed_epoch = time.time()
        t.close_price = price
        t.outcome = outcome
        t.pips = round(pips, 1)
        t.r_multiple = round(r, 2)

        with self._lock:
            self._open.pop(t.trade_id, None)
            with TRADES_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(t), ensure_ascii=False) + "\n")
            self._save_open()
        log.info("PAPER CLOSE [%s] %s %s %s → %s %+.1f pips (R=%.2f)",
                 t.system, t.signal_type, t.symbol, t.side, outcome, pips, r)

    # ── persistence ──────────────────────────────────────────────────────
    def _save_open(self):
        try:
            data = [asdict(t) for t in self._open.values()]
            tmp = OPEN_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(OPEN_PATH)
        except Exception:
            log.debug("save_open failed", exc_info=True)

    def _load_open(self):
        if not OPEN_PATH.exists():
            return
        try:
            data = json.loads(OPEN_PATH.read_text(encoding="utf-8"))
            for d in data:
                t = PaperTrade(**d)
                self._open[t.trade_id] = t
            log.info("PaperTracker resumed %d open trades", len(self._open))
        except Exception:
            log.exception("load_open failed")

    # ── performance rollup ───────────────────────────────────────────────
    def _write_perf(self):
        try:
            stats = self.performance()
            tmp = PERF_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(stats, indent=2), encoding="utf-8")
            tmp.replace(PERF_PATH)
        except Exception:
            log.debug("write_perf failed", exc_info=True)

    def performance(self) -> dict:
        """Per-system × per-type rollup of WIN/LOSS/TIMEOUT + win rate + pips."""
        rows: list[dict] = []
        if TRADES_PATH.exists():
            for ln in TRADES_PATH.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue

        def _bucket():
            return {"trades": 0, "wins": 0, "losses": 0, "timeouts": 0,
                    "win_rate": 0.0, "total_pips": 0.0, "avg_r": 0.0, "r_sum": 0.0}

        agg: dict[str, dict[str, dict]] = {}
        for r in rows:
            system = r.get("system", "?")
            t      = r.get("signal_type", "?")
            agg.setdefault(system, {}).setdefault(t, _bucket())
            agg.setdefault(system, {}).setdefault("all", _bucket())
            for key in (t, "all"):
                b = agg[system][key]
                b["trades"] += 1
                if r.get("outcome") == "WIN":     b["wins"]     += 1
                if r.get("outcome") == "LOSS":    b["losses"]   += 1
                if r.get("outcome") == "TIMEOUT": b["timeouts"] += 1
                b["total_pips"] += r.get("pips") or 0.0
                b["r_sum"]      += r.get("r_multiple") or 0.0

        for system, types in agg.items():
            for t, b in types.items():
                decided = b["wins"] + b["losses"]
                b["win_rate"]   = round(b["wins"] / decided * 100, 1) if decided > 0 else 0.0
                b["total_pips"] = round(b["total_pips"], 1)
                b["avg_r"]      = round(b["r_sum"] / b["trades"], 2) if b["trades"] > 0 else 0.0

        return {
            "generated_at": _utcnow(),
            "open_trades":  [asdict(t) for t in self._open.values()],
            "by_system":    agg,
            "total_closed": len(rows),
        }


# module-level singleton
tracker = PaperTradeTracker()
