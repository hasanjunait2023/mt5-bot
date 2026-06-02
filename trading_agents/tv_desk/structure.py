"""structure — institutional read of a TradingView symbol.

Pulls multi-timeframe OHLCV from TradingView (via TVClient) and runs the Alpha
Desk detector brain on it (supply/demand zones, liquidity pools, order blocks)
plus dealing-range / premium-discount / FVG / PDH-PDL helpers. Returns a compact
JSON-serializable `facts` dict the LLM synthesizes entries from, and the list of
key levels + zones the annotator draws.

TradingView is the single data source — no MT5.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from ..alpha_desk.zones import ZoneTracker
from ..alpha_desk.liquidity import LiquidityTracker, _swing_highs, _swing_lows
from ..alpha_desk.orderflow import OrderFlowDetector
from . import config
from .tv_client import TVClient

log = logging.getLogger("tv_desk.structure")

_TF_LABEL = {"D": "D1", "240": "H4", "60": "H1", "15": "M15", "5": "M5"}


# ── data ─────────────────────────────────────────────────────────────────────
def fetch_df(tv: TVClient, tv_symbol: str, tf: str) -> Optional[pd.DataFrame]:
    """Set chart to symbol+tf and return a clean OHLCV dataframe."""
    tv.set_symbol(tv_symbol)
    tv.set_timeframe(tf)
    res = tv.get_ohlcv(count=config.BARS.get(tf, 200), summary=False)
    bars = res.get("bars") if isinstance(res, dict) else None
    if not bars:
        return None
    df = pd.DataFrame(bars)
    if "time" not in df or "close" not in df:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
    df["tick_volume"] = df["volume"]
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])


def _fvgs(df: pd.DataFrame, dp: int, max_n: int = 4) -> list[dict]:
    """Recent unfilled fair-value gaps (3-candle imbalance)."""
    out: list[dict] = []
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    last_close = c[-1]
    for i in range(n - 2, 1, -1):
        # bullish gap: low[i] > high[i-2]
        if l[i] > h[i - 2]:
            top, bot = float(l[i]), float(h[i - 2])
            if bot <= last_close <= top or last_close > top:   # unfilled / above
                out.append({"side": "bull", "top": round(top, dp), "bottom": round(bot, dp)})
        elif h[i] < l[i - 2]:
            top, bot = float(l[i - 2]), float(h[i])
            if bot <= last_close <= top or last_close < bot:
                out.append({"side": "bear", "top": round(top, dp), "bottom": round(bot, dp)})
        if len(out) >= max_n:
            break
    return out


def _dealing_range(df: pd.DataFrame, dp: int, lookback: int = 60) -> dict:
    sub = df.tail(lookback)
    hi, lo = float(sub["high"].max()), float(sub["low"].min())
    eq = (hi + lo) / 2
    price = float(df["close"].iloc[-1])
    zone = "discount" if price < eq else "premium"
    return {"high": round(hi, dp), "low": round(lo, dp),
            "equilibrium": round(eq, dp), "zone": zone}


def market_structure(df: pd.DataFrame, dp: int) -> dict:
    """Swing-based trend + last BOS/CHoCH (ICT market structure)."""
    sub = df.tail(120).reset_index(drop=True)
    sh, sl = _swing_highs(sub), _swing_lows(sub)
    if len(sh) < 2 or len(sl) < 2:
        return {"trend": "neutral", "event": None, "level": None}
    hh = sub["high"].iloc[sh[-1]] > sub["high"].iloc[sh[-2]]
    hl = sub["low"].iloc[sl[-1]] > sub["low"].iloc[sl[-2]]
    lh = sub["high"].iloc[sh[-1]] < sub["high"].iloc[sh[-2]]
    ll = sub["low"].iloc[sl[-1]] < sub["low"].iloc[sl[-2]]
    trend = "bullish" if (hh and hl) else ("bearish" if (lh and ll) else "neutral")

    last_close = float(sub["close"].iloc[-1])
    last_sh = float(sub["high"].iloc[sh[-1]])
    last_sl = float(sub["low"].iloc[sl[-1]])
    event, level = None, None
    if last_close > last_sh:
        event = "BOS↑" if trend != "bearish" else "CHoCH↑"
        level = round(last_sh, dp)
    elif last_close < last_sl:
        event = "BOS↓" if trend != "bullish" else "CHoCH↓"
        level = round(last_sl, dp)
    return {"trend": trend, "event": event, "level": level}


def _bias(d1: Optional[pd.DataFrame], h4: Optional[pd.DataFrame], dp: int) -> dict:
    """Bias from D1 + H4 market structure (BOS/CHoCH), D1 weighted 2×."""
    score, notes = 0, []
    for tf_df, w, name in [(d1, 2, "D1"), (h4, 1, "H4")]:
        if tf_df is None or len(tf_df) < 30:
            continue
        ms = market_structure(tf_df, dp)
        if ms["trend"] == "bullish":
            score += w; notes.append(f"{name} bullish")
        elif ms["trend"] == "bearish":
            score -= w; notes.append(f"{name} bearish")
        if ms["event"]:
            notes.append(f"{name} {ms['event']}")
    label = "bullish" if score >= 1 else ("bearish" if score <= -1 else "neutral")
    return {"label": label, "score": score, "notes": notes}


def _htf_levels(d1: Optional[pd.DataFrame], dp: int) -> dict:
    """Prior-week & prior-month high/low (HTF draw-on-liquidity)."""
    if d1 is None or len(d1) < 40:
        return {}
    t = d1["time"]
    iso = t.dt.isocalendar()
    d = d1.assign(_yw=list(zip(iso["year"], iso["week"])),
                  _ym=list(zip(t.dt.year, t.dt.month)))
    out: dict = {}
    yws = list(dict.fromkeys(d["_yw"]))
    if len(yws) >= 2:
        p = d[d["_yw"] == yws[-2]]
        out["pwh"] = round(float(p["high"].max()), dp)
        out["pwl"] = round(float(p["low"].min()), dp)
    yms = list(dict.fromkeys(d["_ym"]))
    if len(yms) >= 2:
        p = d[d["_ym"] == yms[-2]]
        out["pmh"] = round(float(p["high"].max()), dp)
        out["pml"] = round(float(p["low"].min()), dp)
    return out


def _session_ranges(h1: Optional[pd.DataFrame], dp: int) -> dict:
    """Most-recent completed Asia / London / NY session high-low (UTC windows)."""
    if h1 is None or len(h1) < 24:
        return {}
    wins = {"asia": (0, 8), "london": (7, 16), "ny": (12, 21)}
    out: dict = {}
    for name, (a, b) in wins.items():
        seg = h1[(h1["time"].dt.hour >= a) & (h1["time"].dt.hour < b)]
        if len(seg) == 0:
            continue
        last_date = seg["time"].dt.date.max()
        d = seg[seg["time"].dt.date == last_date]
        out[name] = {"high": round(float(d["high"].max()), dp),
                     "low": round(float(d["low"].min()), dp),
                     "date": str(last_date)}
    return out


# ── main ─────────────────────────────────────────────────────────────────────
def analyze(tv: TVClient, sym_cfg: dict, mode: str = "intraday") -> dict:
    """Return facts + key levels + the entry-TF anchor for one symbol.

    mode: "intraday" (D/H4/H1/M15) or "scalp" (H1/M15/M5).
    """
    base = sym_cfg["base"]
    dp = int(sym_cfg.get("dp", 5))

    if mode == "intraday":
        tfs = [config.TF_BIAS] + config.TF_INTRADAY        # D,240,60,15
        entry_tf = "60"
    else:
        tfs = [config.TF_SCALP_CTX] + config.TF_SCALP_ENTRY  # 60,15,5
        entry_tf = "15"

    dfs: dict[str, pd.DataFrame] = {}
    for tf in tfs:
        df = fetch_df(tv, sym_cfg["tv"], tf)
        if df is not None and len(df) >= 30:
            dfs[tf] = df

    if entry_tf not in dfs:
        raise RuntimeError(f"insufficient data for {sym_cfg['tv']} ({mode})")

    d1 = dfs.get("D")
    h4 = dfs.get("240")
    h1 = dfs.get("60")
    entry_df = dfs[entry_tf]
    price = float(entry_df["close"].iloc[-1])

    # detectors
    zones = ZoneTracker()
    liq = LiquidityTracker()
    of = OrderFlowDetector()
    if h1 is not None:
        zones.ingest(base, "H1", h1)
        of.scan_order_blocks(base, "H1", h1)
        liq.ingest(base, h1, h4)
    if h4 is not None:
        zones.ingest(base, "H4", h4)
    if mode == "scalp":
        zones.ingest(base, "M15", dfs.get("15", entry_df))
        of.scan_order_blocks(base, "M15", dfs.get("15", entry_df))

    range_tf = h4 if (mode == "intraday" and h4 is not None) else (h1 if h1 is not None else entry_df)
    dealing = _dealing_range(range_tf, dp)
    bias = _bias(d1, h4, dp)
    fvgs = _fvgs(entry_df, dp)
    atr = _atr(entry_df)

    pools = [p.to_public() for p in liq.pools_for(base)]
    zlist = [z.to_public() for z in zones.zones_for(base)]
    obs = [o.to_public() for o in of.obs_for(base)]

    # market structure (BOS/CHoCH) on the trade-context TF
    mstruct = market_structure(h1 if h1 is not None else entry_df, dp)
    htf = _htf_levels(d1, dp)
    sess_ranges = _session_ranges(h1, dp)
    absorp = of.detect_absorption(base, "entry", entry_df)
    absorption = absorp.to_public() if absorp else None

    pdh = next((p["price"] for p in pools if p["kind"] == "pdh"), None)
    pdl = next((p["price"] for p in pools if p["kind"] == "pdl"), None)
    asian_hi = next((p["price"] for p in pools if p["kind"] == "asian" and p["side"] == "bsl"), None)
    asian_lo = next((p["price"] for p in pools if p["kind"] == "asian" and p["side"] == "ssl"), None)

    facts = {
        "symbol": base,
        "tv_symbol": sym_cfg["tv"],
        "name": sym_cfg.get("name", base),
        "mode": mode,
        "price": round(price, dp),
        "dp": dp,
        "mintick": float(sym_cfg.get("mintick", 10 ** -dp)),
        "entry_tf_code": entry_tf,
        "atr_entry": round(atr, dp),
        "bias": bias,
        "market_structure": mstruct,
        "htf_levels": htf,
        "session_ranges": sess_ranges,
        "absorption": absorption,
        "dealing_range": dealing,
        "pdh": pdh, "pdl": pdl,
        "asian_high": asian_hi, "asian_low": asian_lo,
        "fvgs": fvgs,
        "zones": zlist,
        "pools": pools,
        "order_blocks": obs,
        "entry_tf": _TF_LABEL.get(entry_tf, entry_tf),
        "last_bar_ts": int(entry_df["time"].iloc[-1].timestamp()),
        "tf_seconds": _tf_seconds(entry_tf),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {"facts": facts, "entry_df": entry_df}


def _tf_seconds(tf: str) -> int:
    return {"D": 86400, "240": 14400, "60": 3600, "15": 900, "5": 300}.get(tf, 3600)
