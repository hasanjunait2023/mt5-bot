"""Volume reading — Urban Forex method, mechanised on MT5 tick volume.

Course rule (default TradingView Volume + 20-period MA, same setting on both
analysis TFs):
  - High Volume Pop  : collective rise vs the prior range, bars noticeably
                       ABOVE the 20-MA, but NOT the single biggest "spike in
                       the sky" (a climax spike = Big Boys cashing out → reversal).
  - Low Volume Pullback : pullback bars must NOT match / challenge / exceed the
                       pop volume (and ideally sit below the 20-MA).
  - Dead volume @ Test 2 : the final stop-hunt push happens on volume lower
                       than Test 1 / below the MA → no counter-strength left.

CAVEAT (see plan Part B): spot FX has no central tape, so `tick_volume` is a
broker-specific proxy for real institutional volume. These primitives are
exactly what the course describes; whether they carry edge in FX is the key
question Phase 3 backtesting must answer. Keep thresholds in one place so they
can be tuned/ablated.
"""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

VOL_MA_PERIOD    = 20      # course-specified moving-average length (confirmed by Navin)
POP_FACTOR       = 1.30   # pop window mean >= this * MA ("clearly above MA")
CLIMAX_FACTOR    = 3.00   # max bar > this * MA → climax spike (Big Boys cashing out → reversal)
CHALLENGE_FACTOR = 0.60   # pullback "challenges" if its max >= this * pop_max
                          # Navin says ~"half" the pop; 0.60 gives a small buffer
DEAD_FACTOR      = 1.00   # dead volume = bar BELOW the 20-MA (Navin: "falls below the MA
                          # and looks visually unimportant"). NOT a strict 0.7x haircut.
VOL_COL          = "tick_volume"


@dataclass
class VolumeState:
    has_pop: bool
    is_climax: bool
    pop_mean_ratio: float    # recent window mean / MA
    pop_max_ratio: float     # recent window max  / MA
    last_ratio: float        # latest bar / MA
    is_low: bool             # latest bar below MA (digestion)
    is_dead: bool            # latest bar <= DEAD_FACTOR * MA


def _vol(df: pd.DataFrame) -> pd.Series:
    if VOL_COL not in df.columns:
        raise KeyError(f"dataframe missing '{VOL_COL}' column")
    return df[VOL_COL].astype(float)


def vol_ma(df: pd.DataFrame, period: int = VOL_MA_PERIOD) -> pd.Series:
    return _vol(df).rolling(period).mean()


POP_LOOKBACK = 60    # scan this many recent bars for the breakout pop
# Money spot can be up to SPOT_MAX_LOOKBACK=40 bars back; impulse precedes
# the spot, so pop detection must reach back at least 50-60 bars.


def recent_pop(df: pd.DataFrame, *, window: int = 3, lookback: int = POP_LOOKBACK,
               period: int = VOL_MA_PERIOD) -> tuple[bool, bool, float, float]:
    """Is there a high-volume pop anywhere in the recent `lookback` bars?

    The breakout pop happens when price leaves the prior range; by the time
    price is in the money spot / at Test 2 the volume is dead, so we must scan
    back, not only the final bar. Returns (is_pop, is_climax, mean_ratio,
    max_ratio) for the strongest qualifying block (a collective rise above the
    MA that is not a single climax spike).
    """
    v = _vol(df)
    ma = vol_ma(df, period)
    n = len(v)
    if n < period + window or pd.isna(ma.iloc[-1]) or ma.iloc[-1] <= 0:
        return (False, False, 0.0, 0.0)
    lo = max(period, n - lookback)
    best = (False, False, 0.0, 0.0)
    for end_i in range(lo + window, n + 1):
        ref_ma = ma.iloc[end_i - 1]
        if pd.isna(ref_ma) or ref_ma <= 0:
            continue
        ref_ma = float(ref_ma)
        seg = v.iloc[end_i - window:end_i]
        mean_ratio = float(seg.mean()) / ref_ma
        max_ratio = float(seg.max()) / ref_ma
        is_climax = max_ratio > CLIMAX_FACTOR
        is_pop = (mean_ratio >= POP_FACTOR) and not is_climax
        if is_pop and mean_ratio > best[2]:
            best = (True, is_climax, round(mean_ratio, 3), round(max_ratio, 3))
    if best[0]:
        return best
    # no pop found — report the latest window's ratios for context
    ref_ma = float(ma.iloc[-1])
    seg = v.iloc[-window:]
    max_ratio = float(seg.max()) / ref_ma
    return (False, max_ratio > CLIMAX_FACTOR,
            round(float(seg.mean()) / ref_ma, 3), round(max_ratio, 3))


def low_pullback(df_pullback: pd.DataFrame, pop_max_vol: float) -> bool:
    """True if pullback volume stays below the pop (does not challenge it)."""
    v = _vol(df_pullback)
    if len(v) == 0 or pop_max_vol <= 0:
        return False
    return float(v.max()) < pop_max_vol * CHALLENGE_FACTOR


def is_dead(df: pd.DataFrame, *, period: int = VOL_MA_PERIOD) -> bool:
    """Latest bar dead/low — the Test-2 confirmation primitive."""
    v = _vol(df)
    ma = vol_ma(df, period)
    if pd.isna(ma.iloc[-1]) or ma.iloc[-1] <= 0:
        return False
    return float(v.iloc[-1]) <= DEAD_FACTOR * float(ma.iloc[-1])


def read(df: pd.DataFrame, *, window: int = 3,
         period: int = VOL_MA_PERIOD) -> VolumeState:
    """Full volume snapshot for one TF, used by the confluence scorer."""
    v = _vol(df)
    ma = vol_ma(df, period)
    ref_ma = float(ma.iloc[-1]) if (len(ma) and not pd.isna(ma.iloc[-1]) and ma.iloc[-1] > 0) else 0.0
    is_pop, is_climax, mean_ratio, max_ratio = recent_pop(df, window=window, period=period)
    last_ratio = (float(v.iloc[-1]) / ref_ma) if ref_ma > 0 else 0.0
    return VolumeState(
        has_pop=is_pop,
        is_climax=is_climax,
        pop_mean_ratio=mean_ratio,
        pop_max_ratio=max_ratio,
        last_ratio=round(last_ratio, 3),
        is_low=ref_ma > 0 and last_ratio < 1.0,
        is_dead=ref_ma > 0 and last_ratio <= DEAD_FACTOR,
    )
