"""annotate — mark trades on TradingView with the native Long/Short Position tool.

Clean by design: the only marks drawn are one risk/reward Position tool per entry
(green target / red stop, exact levels). No extra lines/zones/text — the position
tool already shows entry, SL, TP and the R:R. Then screenshots the chart.

The Position tool's stop/profit are expressed in TICKS from entry, so we convert
price distances with the symbol's mintick.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .tv_client import TVClient

log = logging.getLogger("tv_desk.annotate")

C_LONG  = "#2962ff"   # blue
C_SHORT = "#ff6d00"   # orange


def _ticks(distance: float, mintick: float) -> int:
    if mintick <= 0:
        mintick = 0.0001
    return max(1, int(round(abs(distance) / mintick)))


def draw_plan(tv: TVClient, facts: dict, plan: dict, *,
              entry_tf_code: str, screenshot_name: str) -> bytes | None:
    """Draw one Long/Short Position tool per entry, screenshot, return PNG bytes."""
    t0 = int(facts["last_bar_ts"])
    tf = int(facts["tf_seconds"])
    mintick = float(facts.get("mintick") or 10 ** -int(facts.get("dp", 5)))

    tv.set_symbol(facts["tv_symbol"])
    tv.set_timeframe(entry_tf_code)
    try:
        tv.clear_drawings()
    except Exception:
        pass

    entries = plan.get("entries", [])
    for k, e in enumerate(entries):
        is_buy = e["side"] == "BUY"
        shape = "long_position" if is_buy else "short_position"
        entry = float(e["entry"])
        stop_ticks = _ticks(entry - e["sl"], mintick)
        # target = TP1 (the 1:2). TP2 stays in the data; chart stays clean.
        profit_ticks = _ticks(e["tp1"] - entry, mintick)

        # stagger boxes left→right in the near-future whitespace
        a = t0 + (1 + k * 5) * tf
        b = a + 4 * tf
        try:
            tv.draw(shape,
                    {"time": a, "price": entry},
                    {"time": b, "price": entry},
                    overrides={
                        "stopLevel": stop_ticks,
                        "profitLevel": profit_ticks,
                        "linecolor": C_LONG if is_buy else C_SHORT,
                        "alwaysShowStats": True,
                        "showPriceLabels": True,
                    })
        except Exception as ex:
            log.debug("position draw failed: %s", ex)

    # frame: show recent action + the staggered boxes
    try:
        tv.set_visible_range(t0 - 70 * tf, t0 + (3 + len(entries) * 5) * tf)
    except Exception:
        pass
    time.sleep(0.4)
    shot = tv.screenshot(screenshot_name, region="chart")
    fp = shot.get("file_path") if isinstance(shot, dict) else None
    if fp and Path(fp).exists():
        try:
            return Path(fp).read_bytes()
        except Exception as e:
            log.warning("read screenshot failed: %s", e)
    return None
