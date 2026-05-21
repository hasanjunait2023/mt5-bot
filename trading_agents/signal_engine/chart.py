"""Chart renderer for signal feeds — white background, 9/15/200 EMAs overlaid
on candlesticks. Pure matplotlib so it works headless on the VPS.

Returns PNG bytes ready to push to Telegram sendPhoto and to the dashboard
(base64-encoded in the WS payload, kept under ~150 KB).
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # headless

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle


# ── styling ──────────────────────────────────────────────────────────────────
_BULL    = "#16a34a"   # green
_BEAR    = "#dc2626"   # red
_EMA9    = "#2563eb"   # blue
_EMA15   = "#f59e0b"   # amber
_EMA200  = "#7c3aed"   # violet
_GRID    = "#e5e7eb"
_FG      = "#111827"


def render_signal_chart(df: pd.DataFrame,
                        *,
                        symbol: str,
                        timeframe_label: str,
                        signal_type: str,
                        side: Optional[str],
                        bars: int = 120) -> bytes:
    """Render the last `bars` candles with EMA 9/15/200 on a white background.

    df must have columns: time (datetime), open, high, low, close,
    ema9, ema15, ema200 (any missing EMA columns are skipped).
    """
    if df is None or df.empty:
        raise ValueError("empty dataframe for chart")

    d = df.tail(bars).copy()
    d["time"] = pd.to_datetime(d["time"])
    t = mdates.date2num(d["time"].dt.to_pydatetime())

    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=140, facecolor="white")
    ax.set_facecolor("white")

    # candle width = ~70% of the median bar spacing
    if len(t) > 1:
        dt = float(np.median(np.diff(t)))
    else:
        dt = 1.0 / (24 * 60)
    body_w = dt * 0.7

    for ts, o, h, l, c in zip(t, d["open"], d["high"], d["low"], d["close"]):
        up = c >= o
        color = _BULL if up else _BEAR
        # wick
        ax.plot([ts, ts], [l, h], color=color, linewidth=1.0, zorder=2)
        # body
        bot = min(o, c)
        height = max(abs(c - o), (h - l) * 0.0005)
        ax.add_patch(Rectangle((ts - body_w / 2, bot), body_w, height,
                               facecolor=color, edgecolor=color,
                               linewidth=0.8, zorder=3))

    # EMAs
    if "ema9" in d:   ax.plot(t, d["ema9"],   color=_EMA9,   linewidth=1.3,
                              label="EMA 9",   zorder=4)
    if "ema15" in d:  ax.plot(t, d["ema15"],  color=_EMA15,  linewidth=1.3,
                              label="EMA 15",  zorder=4)
    if "ema200" in d: ax.plot(t, d["ema200"], color=_EMA200, linewidth=1.8,
                              label="EMA 200", zorder=5)

    # cosmetics
    ax.grid(True, color=_GRID, linewidth=0.6, alpha=0.9, zorder=1)
    ax.tick_params(colors=_FG, labelsize=9)
    for s in ax.spines.values():
        s.set_color(_GRID)

    side_tag = ""
    if side:
        side_tag = f"  ·  {side.upper()}"
    title = f"{symbol}  ·  {timeframe_label}  ·  {signal_type}{side_tag}"
    ax.set_title(title, color=_FG, fontsize=12, fontweight="bold", pad=10)

    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")

    leg = ax.legend(loc="upper left", framealpha=0.9, fontsize=9,
                    facecolor="white", edgecolor=_GRID)
    for txt in leg.get_texts():
        txt.set_color(_FG)

    # footer timestamp
    fig.text(0.99, 0.01,
             datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
             ha="right", va="bottom", color="#6b7280", fontsize=8)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
