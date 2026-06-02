"""Signal Engine — fast multi-timeframe EMA scanner.

Three signal types, each routed to its own Telegram topic and broadcast over
the dashboard WebSocket:

  1. alignment  — EMA-200 aligned same direction on M1, M3, M15, H1
                  (price > 200EMA on every TF = bullish align; < = bearish).
  2. cross      — on alignment-qualified symbols, 9 EMA crossing 15 EMA on
                  M1 in the alignment direction (down cross + bear align =
                  SELL; up cross + bull align = BUY).
  3. touch      — on alignment-qualified symbols, M3 price touches/wicks
                  the 200 EMA (potential pullback entry).

Loop cadence: tick-driven, ~1 s pacing (well under 1 m candle close). All
emitting is in-process — Telegram + WS broadcast happen synchronously so the
end-to-end delivery is bound by the network, not by polling.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

try:
    from mt5_bridge import bridge_client as mt5
except Exception:                       # noqa: BLE001
    mt5 = None                          # allows import on machines without MT5

from .. import telegram_hq
from .chart import render_signal_chart

log = logging.getLogger("SignalEngine")


def _should_deliver(category: str) -> bool:
    """Delivery gate wrapper — fail-open if the delivery module is unavailable."""
    try:
        from .delivery import should_deliver
        return should_deliver(category)
    except Exception:
        return True

# ── config ──────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parents[2]
STATE_PATH   = BASE_DIR / "logs" / "signals" / "_signal_state.json"
EVENTS_PATH  = BASE_DIR / "logs" / "signals" / "_signal_events.jsonl"
CHART_DIR    = BASE_DIR / "logs" / "signals" / "charts"
MAX_EVENTS   = 1000

SIGNAL_TYPES = ("alignment", "cross", "touch")
CATEGORY_BY_TYPE = {
    "alignment": "signal_alignment",
    "cross":     "signal_cross",
    "touch":     "signal_touch",
}

# Symbols to scan — kept here so the engine doesn't require mt5_bridge.config.
DEFAULT_SYMBOLS = [
    # 7 majors
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    # EUR crosses
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD",
    # GBP crosses
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD",
    # AUD/NZD/CAD/CHF crosses
    "AUDJPY", "AUDCHF", "AUDNZD", "AUDCAD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF", "CHFJPY",
    # Commodities & crypto
    "XAUUSD", "XAGUSD", "BTCUSD", "USOIL", "XTIUSD",  # broker-name variants
]

TF_BARS = {
    "M1":  260,    # need >= 200 for EMA200
    "M3":  260,
    "M15": 260,
    "H1":  260,
}

_ADX_TREND_MIN = 25.0   # H1 ADX threshold: >= trending, < ranging (cross/touch gate)


# ── helpers ─────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    """Return latest ADX value (0-100). >= 25 = trending, < 25 = ranging."""
    h, l, c = df["high"], df["low"], df["close"]
    tr       = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn   = h.diff(), -l.diff()
    plus_dm  = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    atr14    = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr14.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr14.replace(0, np.nan)
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return float(dx.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])


def _add_emas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema9"]   = _ema(df["close"], 9)
    df["ema15"]  = _ema(df["close"], 15)
    df["ema200"] = _ema(df["close"], 200)
    return df


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ── event model ─────────────────────────────────────────────────────────────

@dataclass
class SignalEvent:
    id: str
    ts: str
    type: str                # alignment | cross | touch
    symbol: str
    side: str                # BUY | SELL
    timeframe: str           # the TF the chart shows
    price: float
    ema9: Optional[float]
    ema15: Optional[float]
    ema200: Optional[float]
    note: str
    chart_path: Optional[str] = None
    detect_ms: float = 0.0   # detection latency
    # decision context (template D-extended)
    verdict: str = "STRONG"            # PRIME / STRONG / OK
    correlation: str = "MED"           # HIGH / MED / LOW
    base_currency: str = ""
    quote_currency: str = ""
    base_score: float = 5.0            # 0-10 currency strength
    quote_score: float = 5.0
    alignment_count: int = 4           # 0..4 TFs aligned
    system: str = "classic"            # classic | improved
    score: float = 0.0                 # 0..100 quality (improved system)

    def to_public(self) -> dict:
        return asdict(self)


# ── engine ──────────────────────────────────────────────────────────────────

class SignalEngine:
    """Single-thread MT5 scanner. Call .run() to block, or .start() in a daemon."""

    def __init__(self,
                 symbols: Optional[Iterable[str]] = None,
                 tick_sec: float = 1.5,
                 broadcaster=None):
        self.symbols = list(symbols or DEFAULT_SYMBOLS)
        self.tick_sec = tick_sec
        self.broadcaster = broadcaster   # callable(dict)  — typically ws_manager.broadcast_sync
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # last-state cache so we only emit on transition / new bar
        self._last_align: dict[str, str] = {}       # symbol -> "bull"/"bear"/"none"
        self._last_cross_bar: dict[str, int] = {}   # symbol -> bar timestamp of last cross emission
        self._last_touch_bar: dict[str, int] = {}
        self._verified_symbols: list[str] = []
        # Improved engine — lazy import so a missing module never blocks classic
        try:
            from .improved import ImprovedDetector
            self.improved = ImprovedDetector()
        except Exception:
            log.exception("ImprovedDetector unavailable")
            self.improved = None
        # Paper-trade tracker (shared singleton across both systems)
        try:
            from .tracker import tracker as _tracker
            self.tracker = _tracker
            self.tracker.start()
        except Exception:
            log.exception("PaperTradeTracker unavailable")
            self.tracker = None
        # Alpha Desk — institutional confluence engine, piggybacks on snapshots
        try:
            from trading_agents.alpha_desk import AlphaDeskEngine
            self.alpha = AlphaDeskEngine(broadcaster=broadcaster, tracker=self.tracker)
        except Exception:
            log.exception("AlphaDeskEngine unavailable")
            self.alpha = None
        # Iconic Trader — Urban Forex Set1/Set2 confluence engine
        try:
            from trading_agents.iconic.runner import IconicRunner
            self.iconic = IconicRunner(broadcaster=broadcaster)
        except Exception:
            log.exception("IconicRunner unavailable")
            self.iconic = None
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHART_DIR.mkdir(parents=True, exist_ok=True)
        self._save_state(running=False)

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, daemon=True,
                                        name="SignalEngine")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run(self):
        if mt5 is None:
            log.error("MetaTrader5 module not available — engine cannot start")
            return

        # Outer reconnect loop — retries forever until _stop is set
        while not self._stop.is_set():
            if not mt5.initialize():
                log.warning("mt5.initialize() failed: %s — retry in 30s", mt5.last_error())
                self._stop.wait(30)
                continue

            self._verified_symbols = self._verify_symbols(self.symbols)
            log.info("SignalEngine connected — %d symbols", len(self._verified_symbols))
            self._save_state(running=True)
            consecutive_empty = 0

            try:
                while not self._stop.is_set():
                    t0 = time.time()
                    try:
                        n_snapshots = self._scan_once()
                        if n_snapshots == 0:
                            consecutive_empty += 1
                            if consecutive_empty >= 5:
                                # 5 empty scans → MT5 probably dropped
                                info = mt5.terminal_info()
                                if info is None or not info.connected:
                                    log.warning("MT5 connection lost — reconnecting")
                                    break  # break inner loop → outer reconnect
                                consecutive_empty = 0
                        else:
                            consecutive_empty = 0
                    except Exception:
                        log.exception("scan_once failed")
                    dt = time.time() - t0
                    self._stop.wait(max(0.0, self.tick_sec - dt))
            except Exception:
                log.exception("SignalEngine inner loop crashed")
            finally:
                try:
                    mt5.shutdown()
                except Exception:
                    pass

            if not self._stop.is_set():
                self._save_state(running=False)
                log.info("SignalEngine disconnected — reconnecting in 15s")
                self._stop.wait(15)

        self._save_state(running=False)
        if self.tracker is not None:
            try: self.tracker.stop()
            except Exception: pass

    # ── symbol verification ──────────────────────────────────────────────
    def _verify_symbols(self, symbols: Iterable[str]) -> list[str]:
        ok: list[str] = []
        for s in symbols:
            info = mt5.symbol_info(s)
            if info is None:
                continue
            if not info.visible:
                mt5.symbol_select(s, True)
            ok.append(s)
        return ok

    # ── data ─────────────────────────────────────────────────────────────
    def _fetch_tf(self, symbol: str, tf_const, bars: int) -> Optional[pd.DataFrame]:
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars)
        if rates is None or len(rates) < 200:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return _add_emas(df)

    def _fetch_all_tfs(self, symbol: str) -> Optional[dict[str, pd.DataFrame]]:
        out: dict[str, pd.DataFrame] = {}
        for label, tf_const, bars in (
            ("M1",  mt5.TIMEFRAME_M1,  TF_BARS["M1"]),
            ("M3",  mt5.TIMEFRAME_M3,  TF_BARS["M3"]),
            ("M15", mt5.TIMEFRAME_M15, TF_BARS["M15"]),
            ("H1",  mt5.TIMEFRAME_H1,  TF_BARS["H1"]),
        ):
            df = self._fetch_tf(symbol, tf_const, bars)
            if df is None:
                return None
            out[label] = df
        return out

    # ── classifiers ──────────────────────────────────────────────────────
    @staticmethod
    def _align(tfs: dict[str, pd.DataFrame]) -> str:
        """Return 'bull' / 'bear' / 'none' based on close vs EMA200 across TFs."""
        bull = bear = True
        for label in ("M1", "M3", "M15", "H1"):
            row = tfs[label].iloc[-1]
            if not (row["close"] > row["ema200"]):
                bull = False
            if not (row["close"] < row["ema200"]):
                bear = False
        if bull:  return "bull"
        if bear:  return "bear"
        return "none"

    @staticmethod
    def _cross_event(df_m1: pd.DataFrame) -> Optional[str]:
        """Return 'up' / 'down' if the *latest closed* M1 candle posted a 9/15
        cross relative to the previous bar, else None.
        """
        if len(df_m1) < 3:
            return None
        a = df_m1.iloc[-2]    # prev
        b = df_m1.iloc[-1]    # current (live)
        # use closed-bar transition: prev relation vs current relation
        prev_up = a["ema9"] > a["ema15"]
        curr_up = b["ema9"] > b["ema15"]
        if prev_up == curr_up:
            return None
        return "up" if curr_up else "down"

    @staticmethod
    def _touch_event(df_m3: pd.DataFrame) -> bool:
        """True if the latest M3 candle's range crosses the 200 EMA."""
        if len(df_m3) < 2:
            return False
        b = df_m3.iloc[-1]
        return b["low"] <= b["ema200"] <= b["high"]

    # ── per-tick scan ────────────────────────────────────────────────────
    def _scan_once(self) -> int:
        """Run one scan cycle. Returns count of valid snapshots (0 = MT5 likely dead)."""
        # Pass 1 — snapshot every symbol (fetch TFs, compute alignment).
        snapshots: dict[str, dict] = {}
        for symbol in self._verified_symbols:
            try:
                t0 = time.time()
                tfs = self._fetch_all_tfs(symbol)
                if not tfs:
                    continue
                snapshots[symbol] = {
                    "tfs": tfs,
                    "align": self._align(tfs),
                    "detect_ms": (time.time() - t0) * 1000.0,
                }
            except Exception:
                log.exception("snapshot failed: %s", symbol)

        # Pass 2 — global currency strength (uses everyone's alignment).
        strength = self._currency_strength(snapshots)

        # Pass 3 — detect + emit, with strength-aware verdict.
        for symbol, snap in snapshots.items():
            try:
                tfs, align, detect_ms = snap["tfs"], snap["align"], snap["detect_ms"]

                # 1) Alignment — emit on transition into bull/bear
                prev_align = self._last_align.get(symbol, "none")
                if align in ("bull", "bear") and prev_align != align:
                    side = "BUY" if align == "bull" else "SELL"
                    self._emit("alignment", symbol, side, "H1", tfs["H1"],
                               note="EMA-200 aligned across M1·M3·M15·H1",
                               detect_ms=detect_ms, strength=strength)
                self._last_align[symbol] = align

                # cross + touch only fire when the symbol is currently aligned
                if align == "none":
                    continue

                # Trend gate (shared) — H1 ADX must confirm trending market
                h1_adx = _adx(tfs["H1"])
                in_trend = h1_adx >= _ADX_TREND_MIN

                # 2) 9/15 cross on M1 in alignment direction
                cross = self._cross_event(tfs["M1"])
                if cross is not None and in_trend:
                    bar_ts = int(tfs["M1"].iloc[-1]["time"].timestamp())
                    if self._last_cross_bar.get(symbol) != bar_ts:
                        want = "up" if align == "bull" else "down"
                        if cross == want:
                            side = "BUY" if cross == "up" else "SELL"
                            self._emit("cross", symbol, side, "M1", tfs["M1"],
                                       note=f"9/15 EMA cross in trend (H1 ADX {h1_adx:.1f})",
                                       detect_ms=detect_ms, strength=strength)
                            self._last_cross_bar[symbol] = bar_ts

                # 3) M3 200EMA touch
                if self._touch_event(tfs["M3"]) and in_trend:
                    bar_ts = int(tfs["M3"].iloc[-1]["time"].timestamp())
                    if self._last_touch_bar.get(symbol) != bar_ts:
                        side = "BUY" if align == "bull" else "SELL"
                        self._emit("touch", symbol, side, "M3", tfs["M3"],
                                   note=f"200 EMA touch in trend (H1 ADX {h1_adx:.1f})",
                                   detect_ms=detect_ms, strength=strength)
                        self._last_touch_bar[symbol] = bar_ts
            except Exception:
                log.exception("symbol emit failed: %s", symbol)

        # Pass 4 — IMPROVED engine evaluates the same snapshots and emits
        # to its own Telegram topic / dashboard channel.
        if self.improved is not None:
            try:
                t0 = time.time()
                improved_evs = self.improved.evaluate(snapshots, strength)
                dt_ms = (time.time() - t0) * 1000.0
                for iev in improved_evs:
                    iev.detect_ms = round(dt_ms, 1)
                    self._emit_improved(iev, strength=strength)
            except Exception:
                log.exception("improved evaluate failed")

        # Pass 5 — ALPHA DESK consumes the same snapshots for institutional
        # confluence detection (zones + liquidity + order-flow + sessions).
        if self.alpha is not None:
            try:
                self.alpha.consume(snapshots, strength)
            except Exception:
                log.exception("alpha consume failed")

        # Pass 6 — ICONIC TRADER (Urban Forex Set1/Set2 + volume + correlation).
        if self.iconic is not None:
            try:
                self.iconic.consume(snapshots, strength)
            except Exception:
                log.exception("iconic consume failed")

        return len(snapshots)

    # ── currency strength ────────────────────────────────────────────────
    @staticmethod
    def _split_currencies(symbol: str) -> tuple[str, str]:
        """Split a 6-char FX symbol into (base, quote). Returns ('','') for non-FX."""
        if len(symbol) == 6 and symbol.isalpha():
            return symbol[:3], symbol[3:]
        # special metal/crypto/oil tickers
        special = {"XAUUSD": ("XAU", "USD"), "XAGUSD": ("XAG", "USD"),
                   "BTCUSD": ("BTC", "USD"), "USOIL":  ("OIL", "USD"),
                   "XTIUSD": ("OIL", "USD")}
        return special.get(symbol, ("", ""))

    @classmethod
    def _currency_strength(cls, snapshots: dict) -> dict[str, float]:
        """0..10 score per currency. 10 = strong everywhere, 0 = weak everywhere.

        Method: for every aligned pair, base gets +1 if bull / -1 if bear,
        quote gets the opposite. Then normalize by the number of pairs each
        currency appears in.
        """
        raw: dict[str, list[int]] = {}
        for sym, snap in snapshots.items():
            base, quote = cls._split_currencies(sym)
            if not base:
                continue
            align = snap["align"]
            if align == "none":
                b = q = 0
            elif align == "bull":
                b, q = +1, -1
            else:    # bear
                b, q = -1, +1
            raw.setdefault(base,  []).append(b)
            raw.setdefault(quote, []).append(q)

        out: dict[str, float] = {}
        for ccy, vals in raw.items():
            if not vals:
                out[ccy] = 5.0
                continue
            # mean in [-1, +1] → 0..10
            mean = sum(vals) / len(vals)
            out[ccy] = round((mean + 1) * 5, 1)
        return out

    @staticmethod
    def _correlation(side: str, base_score: float, quote_score: float) -> str:
        """HIGH / MED / LOW based on per-currency strength agreeing with side."""
        if side == "BUY":
            if base_score >= 6.5 and quote_score <= 3.5: return "HIGH"
            if base_score >= 5.5 and quote_score <= 4.5: return "MED"
            return "LOW"
        else:    # SELL
            if base_score <= 3.5 and quote_score >= 6.5: return "HIGH"
            if base_score <= 4.5 and quote_score >= 5.5: return "MED"
            return "LOW"

    @staticmethod
    def _verdict(kind: str, correlation: str, *, extra: bool = False) -> str:
        """PRIME 🔥 / STRONG 🟢 / OK 🟡 based on signal type + correlation."""
        if kind == "alignment":
            if correlation == "HIGH": return "PRIME 🔥"
            if correlation == "MED":  return "STRONG 🟢"
            return "OK 🟡"
        if kind == "cross":
            if correlation == "HIGH": return "PRIME 🔥"
            if correlation == "MED":  return "STRONG 🟢"
            return "OK 🟡"
        # touch — `extra=True` if clean (tight gap)
        if kind == "touch":
            if correlation == "HIGH" and extra: return "PRIME 🔥"
            if correlation == "HIGH" or extra:  return "STRONG 🟢"
            return "OK 🟡"
        return "OK 🟡"

    # ── emit ─────────────────────────────────────────────────────────────
    def _emit(self, kind: str, symbol: str, side: str,
              chart_tf: str, df: pd.DataFrame,
              *, note: str, detect_ms: float, strength: dict[str, float]):
        last = df.iloc[-1]
        base, quote = self._split_currencies(symbol)
        base_score  = strength.get(base, 5.0)  if base  else 5.0
        quote_score = strength.get(quote, 5.0) if quote else 5.0
        corr = self._correlation(side, base_score, quote_score)

        # touch-specific quality: tight wick = clean pullback
        extra_clean = False
        if kind == "touch":
            ema200_v = float(last.get("ema200", 0.0))
            pip_mult = 100.0 if symbol.endswith("JPY") else 10000.0
            gap_pips = abs(float(last["close"]) - ema200_v) * pip_mult
            extra_clean = gap_pips < 1.0

        verdict = self._verdict(kind, corr, extra=extra_clean)

        ev = SignalEvent(
            id=f"{kind}-{symbol}-{int(time.time()*1000)}",
            ts=_utcnow_iso(),
            type=kind, symbol=symbol, side=side,
            timeframe=chart_tf,
            price=float(last["close"]),
            ema9=float(last.get("ema9", np.nan)),
            ema15=float(last.get("ema15", np.nan)),
            ema200=float(last.get("ema200", np.nan)),
            note=note,
            detect_ms=round(detect_ms, 1),
            verdict=verdict,
            correlation=corr,
            base_currency=base, quote_currency=quote,
            base_score=base_score, quote_score=quote_score,
            alignment_count=4,
        )

        # render chart
        try:
            png = render_signal_chart(df, symbol=symbol,
                                      timeframe_label=chart_tf,
                                      signal_type=kind.upper(),
                                      side=side, bars=120)
            chart_file = CHART_DIR / f"{ev.id}.png"
            chart_file.write_bytes(png)
            ev.chart_path = str(chart_file.relative_to(BASE_DIR)).replace("\\", "/")
        except Exception:
            log.exception("chart render failed for %s/%s", symbol, kind)
            png = None

        # Delivery gate — controls Telegram + WS only. JSONL + tracker always run.
        cat = CATEGORY_BY_TYPE[kind]
        deliver = _should_deliver(cat)

        # Telegram (with chart if we have one)
        if deliver:
            caption = self._format_caption(ev)
            try:
                if png:
                    telegram_hq.send_photo(
                        cat, png, caption,
                        dedupe_key=f"{kind}|{symbol}|{side}",
                        title=None,
                    )
                else:
                    telegram_hq.send(cat, caption, level="INFO")
            except Exception:
                log.exception("telegram send failed")

        # JSONL log (always — keeps full history regardless of delivery prefs)
        self._append_event(ev)

        # WebSocket push (gated — dashboard live feed respects delivery prefs)
        if deliver and self.broadcaster:
            payload: dict = ev.to_public()
            if png and len(png) < 250_000:
                payload["chart_b64"] = base64.b64encode(png).decode("ascii")
            try:
                self.broadcaster({"type": "signal", "data": payload})
            except Exception:
                log.exception("ws broadcast failed")

        # Feed paper-trade tracker (classic system)
        if self.tracker is not None:
            try:
                self.tracker.on_signal(ev.to_public(), system="classic")
            except Exception:
                log.exception("tracker on_signal (classic) failed")

        log.info("SIGNAL  %s  %s  %s  %s  (%.1fms)",
                 kind, symbol, side, ev.timeframe, detect_ms)

    # ── emit (improved system) ──────────────────────────────────────────
    def _emit_improved(self, iev, *, strength: dict[str, float]):
        """Emit an ImprovedSignal to its dedicated topic + WS channel + tracker."""
        symbol = iev.symbol
        base, quote = self._split_currencies(symbol)
        base_score  = strength.get(base, 5.0)  if base  else 5.0
        quote_score = strength.get(quote, 5.0) if quote else 5.0
        corr = self._correlation(iev.side, base_score, quote_score) if iev.side in ("BUY", "SELL") else "MED"

        ev = SignalEvent(
            id=f"imp-{iev.type}-{symbol}-{int(time.time()*1000)}",
            ts=_utcnow_iso(),
            type=iev.type, symbol=symbol, side=iev.side,
            timeframe=iev.timeframe,
            price=iev.price,
            ema9=iev.ema9, ema15=iev.ema15, ema200=iev.ema200,
            note=" · ".join(iev.notes),
            detect_ms=iev.detect_ms,
            verdict=iev.verdict, correlation=corr,
            base_currency=base, quote_currency=quote,
            base_score=base_score, quote_score=quote_score,
            alignment_count=4,
            system="improved", score=iev.score,
        )

        # render chart
        try:
            png = render_signal_chart(iev.df_for_chart, symbol=symbol,
                                      timeframe_label=iev.timeframe,
                                      signal_type=f"IMPROVED · {iev.type.upper()}",
                                      side=iev.side if iev.side in ("BUY","SELL") else None,
                                      bars=120)
            chart_file = CHART_DIR / f"{ev.id}.png"
            chart_file.write_bytes(png)
            ev.chart_path = str(chart_file.relative_to(BASE_DIR)).replace("\\", "/")
        except Exception:
            log.exception("improved chart render failed for %s/%s", symbol, iev.type)
            png = None

        deliver = _should_deliver("signal_improved")

        if deliver:
            caption = self._format_improved_caption(ev, iev)
            try:
                if png:
                    telegram_hq.send_photo(
                        "signal_improved", png, caption,
                        dedupe_key=f"imp|{iev.type}|{symbol}|{iev.side}",
                        title=None,
                    )
                else:
                    telegram_hq.send("signal_improved", caption, level="INFO")
            except Exception:
                log.exception("improved telegram send failed")

        self._append_event(ev)

        if deliver and self.broadcaster:
            payload: dict = ev.to_public()
            if png and len(png) < 250_000:
                payload["chart_b64"] = base64.b64encode(png).decode("ascii")
            try:
                self.broadcaster({"type": "signal", "data": payload})
            except Exception:
                log.exception("ws broadcast (improved) failed")

        # Feed paper-trade tracker (improved system)
        if self.tracker is not None:
            try:
                self.tracker.on_signal(ev.to_public(), system="improved")
            except Exception:
                log.exception("tracker on_signal (improved) failed")

        log.info("IMPROVED  %s  %s  %s  %s  score=%.0f  (%.1fms)",
                 iev.type, symbol, iev.side, iev.timeframe, iev.score, iev.detect_ms)

    # ── caption ──────────────────────────────────────────────────────────
    @staticmethod
    def _fmt_symbol(symbol: str) -> str:
        special = {"USOIL": "US/OIL", "XTIUSD": "XTI/USD"}
        if symbol in special:
            return special[symbol]
        if len(symbol) == 6 and symbol.isalpha():
            return f"{symbol[:3]}/{symbol[3:]}"
        return symbol

    @staticmethod
    def _fmt_ts_bd(iso_ts: str) -> str:
        """Render 'HH:MM UTC · HH:MM BD' from an ISO-format UTC timestamp."""
        try:
            from datetime import datetime, timedelta
            # ISO already has +00:00; strip suffix for parsing
            base = iso_ts.split("+")[0].split("Z")[0]
            if "." in base:
                base = base.split(".")[0]
            dt = datetime.fromisoformat(base)
            bd = dt + timedelta(hours=6)
            return f"{dt.strftime('%H:%M')} UTC · {bd.strftime('%H:%M')} BD"
        except Exception:
            return iso_ts.split("T")[1][:5] + " UTC"

    @staticmethod
    def _format_caption(ev: SignalEvent) -> str:
        """Pro-trader template with checklist, verdict, correlation, and
        Bangla one-liner.

        Layout (chosen by user 2026-05-20):
          📊 HEADER · SYM/BOL
          Direction / Timeframe / Verdict
          Checklist with [✓] confirmation points
          Price / EMA / time / detect-latency
          🇧🇩 short Bangla action guide
        """
        side_arrow = "🟢" if ev.side == "BUY" else "🔴"
        sym_pretty = SignalEngine._fmt_symbol(ev.symbol)

        # Type-specific header + timeframe row + checklist content
        if ev.type == "alignment":
            head_emoji = "📊"
            head_text  = "4-TF EMA-200 ALIGNMENT"
            tf_row     = "1m · 3m · 15m · 1h"
            checklist = [
                f"[✓] Price {'>' if ev.side == 'BUY' else '<'} EMA200 on 1m",
                f"[✓] Price {'>' if ev.side == 'BUY' else '<'} EMA200 on 3m",
                f"[✓] Price {'>' if ev.side == 'BUY' else '<'} EMA200 on 15m",
                f"[✓] Price {'>' if ev.side == 'BUY' else '<'} EMA200 on 1h",
            ]
            bn = (
                f"বাজার {'উপরে' if ev.side == 'BUY' else 'নিচে'} — শুধু "
                f"{ev.side} setup খোঁজো"
            )
        elif ev.type == "cross":
            head_emoji = "⚡"
            head_text  = "9/15 EMA CROSS"
            tf_row     = "1m"
            arrow_l    = "↑" if ev.side == "BUY" else "↓"
            cmp_l      = ">" if ev.side == "BUY" else "<"
            checklist = [
                f"[✓] {'Bullish' if ev.side == 'BUY' else 'Bearish'} alignment 4/4",
                f"[✓] 9 EMA {arrow_l} through 15 EMA",
                f"[✓] Live bar confirms 9 {cmp_l} 15",
            ]
            bn = f"এন্ট্রি ট্রিগার — SL সেট করে {ev.side} নাও"
        else:  # touch
            head_emoji = "🎯"
            head_text  = "200 EMA TOUCH"
            tf_row     = "3m"
            pip_mult   = 100.0 if ev.symbol.endswith("JPY") else 10000.0
            gap_pips   = abs(ev.price - ev.ema200) * pip_mult
            checklist = [
                f"[✓] {'Bullish' if ev.side == 'BUY' else 'Bearish'} alignment 4/4",
                f"[✓] Price wick touched 200 EMA",
                f"[✓] Pullback gap: {gap_pips:.1f} pips",
            ]
            bn = "প্রাইস 200 EMA তে — confirmation candle wait"

        # Correlation row — show only if we have FX currency split
        if ev.base_currency and ev.quote_currency:
            checklist.append(
                f"[✓] Correlation {ev.correlation} "
                f"({ev.base_currency} {ev.base_score:.1f} / "
                f"{ev.quote_currency} {ev.quote_score:.1f})"
            )

        # Pretty-print time + price digits (JPY/oil keep 3 dp)
        price_dp = 3 if (ev.symbol.endswith("JPY") or "OIL" in ev.symbol) else 5
        ts_short = SignalEngine._fmt_ts_bd(ev.ts)

        lines = [
            f"{head_emoji} *{head_text}* · `{sym_pretty}`",
            "",
            f"Direction : {side_arrow} *{ev.side}*",
            f"Timeframe : {tf_row}",
            f"Verdict   : *{ev.verdict}*",
            "",
            "*Checklist:*",
            *checklist,
            "",
            f"💰 Price : `{ev.price:.{price_dp}f}`",
            f"🎯 EMA200: `{ev.ema200:.{price_dp}f}`",
            f"⏰ {ts_short} · `{ev.detect_ms:.0f} ms`",
            "",
            f"🇧🇩 _{bn}_",
        ]
        return "\n".join(lines)

    # ── caption (improved system) ───────────────────────────────────────
    @staticmethod
    def _score_bar(score: float, width: int = 10) -> str:
        filled = int(round(score / 100 * width))
        return "█" * filled + "░" * (width - filled)

    @staticmethod
    def _format_improved_caption(ev: SignalEvent, iev) -> str:
        """Caption for the IMPROVED system. Includes the quality-score visual
        bar, full passed-gate checklist, and per-type Bangla action line.

        Special types: `stacked` and `cross_failed` get distinct headers.
        """
        sym_pretty = SignalEngine._fmt_symbol(ev.symbol)
        if ev.side == "BUY":
            side_arrow = "🟢"
        elif ev.side == "SELL":
            side_arrow = "🔴"
        else:
            side_arrow = "⚠️"

        if iev.type == "stacked":
            head_emoji, head_text, tf_row = "💎", "STACKED SETUP", "M1 · M3 · H1 (all 3 signals)"
            bn = f"তিনটি signal একসাথে — সর্বোচ্চ conviction · {ev.side}"
        elif iev.type == "cross_failed":
            head_emoji, head_text, tf_row = "⚠️", "CROSS FAILED · EXIT", "M1"
            bn = "Cross reversed — যদি ট্রেডে থাকো, exit করো"
        elif iev.type == "alignment":
            head_emoji, head_text, tf_row = "📊", "ALIGNMENT (improved)", "1m · 3m · 15m · 1h"
            bn = f"Real trend — শুধু {ev.side} setup খোঁজো (slope confirmed)"
        elif iev.type == "cross":
            head_emoji, head_text, tf_row = "⚡", "9/15 CROSS (improved)", "M1"
            bn = f"Quality entry — SL সেট করে {ev.side} নাও"
        elif iev.type == "touch":
            head_emoji, head_text, tf_row = "🎯", "200 EMA TOUCH (improved)", "M3"
            bn = f"Rejection confirmed — {ev.side} entry valid"
        else:
            head_emoji, head_text, tf_row = "💎", iev.type.upper(), ev.timeframe
            bn = ""

        price_dp = 3 if (ev.symbol.endswith("JPY") or "OIL" in ev.symbol) else 5
        ts_short = SignalEngine._fmt_ts_bd(ev.ts)

        # Show the strength score visually
        score_bar = SignalEngine._score_bar(iev.score)

        lines = [
            f"{head_emoji} *{head_text}* · `{sym_pretty}`",
            "",
            f"Direction : {side_arrow} *{ev.side}*",
            f"Timeframe : {tf_row}",
            f"Verdict   : *{ev.verdict}*",
            f"Score     : `{score_bar}` *{iev.score:.0f}/100*",
            "",
            "*Gates passed:*",
            *iev.notes,
        ]
        if ev.base_currency and ev.quote_currency and ev.side in ("BUY", "SELL"):
            lines.append(
                f"[~] Correlation {ev.correlation} "
                f"({ev.base_currency} {ev.base_score:.1f} / "
                f"{ev.quote_currency} {ev.quote_score:.1f})"
            )
        lines += [
            "",
            f"💰 Price : `{ev.price:.{price_dp}f}`",
            f"🎯 EMA200: `{ev.ema200:.{price_dp}f}`",
            f"⏰ {ts_short} · `{ev.detect_ms:.0f} ms`",
        ]
        if bn:
            lines += ["", f"🇧🇩 _{bn}_"]
        return "\n".join(lines)

    # ── persistence ──────────────────────────────────────────────────────
    def _append_event(self, ev: SignalEvent):
        try:
            EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with EVENTS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev.to_public(), ensure_ascii=False) + "\n")
            # truncate periodically
            if EVENTS_PATH.stat().st_size > 2_000_000:
                lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
                EVENTS_PATH.write_text("\n".join(lines[-MAX_EVENTS:]) + "\n",
                                       encoding="utf-8")
        except Exception:
            log.exception("append_event failed")

    def _save_state(self, *, running: bool):
        try:
            STATE_PATH.write_text(json.dumps({
                "running": running,
                "tick_sec": self.tick_sec,
                "symbols": self._verified_symbols or self.symbols,
                "updated_at": _utcnow_iso(),
            }, indent=2), encoding="utf-8")
        except Exception:
            log.debug("save_state failed", exc_info=True)


# ── runtime entrypoint ──────────────────────────────────────────────────────

def _default_broadcaster():
    """Try to wire to the dashboard ws_manager if it's importable."""
    try:
        # only works when run from the project root with dashboard backend on path
        import sys
        backend = str(BASE_DIR / "dashboard" / "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        from core.ws_manager import manager        # type: ignore
        return manager.broadcast_sync
    except Exception:
        return None


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    )
    engine = SignalEngine(broadcaster=_default_broadcaster())
    try:
        engine.run()
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
