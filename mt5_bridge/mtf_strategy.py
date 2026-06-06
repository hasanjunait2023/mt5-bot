# encoding: utf-8
"""
mtf_strategy.py — Multi-Timeframe EMA Alignment Scalper signal generator.

Strategy:
  - 3 timeframes: M15 (macro trend) + M3 (momentum) + M1 (entry)
  - EMA 200 trend filter on all 3 TFs
  - EMA 9/15 crossover on M1 as entry trigger
  - EMA 9 > 15 on M3 and M15 confirms direction
  - SL: swing high/low of last N bars + ATR buffer
  - TP: SL distance × RR (default 2.0)
  - Optional filters: RSI, ATR volatility, session, candle quality,
                      EMA separation expansion, currency strength, news
"""
import numpy as np
import pandas as pd
import bridge_client as mt5   # HTTP-bridge shim (sibling import; only TIMEFRAME_* used here). Real MetaTrader5 is Windows-only.
from typing import Dict, Tuple, Optional, List
from datetime import timezone

from mt5_bridge import fetch_ohlcv, get_pip_size
from config import MTF_DEFAULT_PARAMS, MTF_SYMBOL_CONFIG, MAJOR_CURRENCIES


# ── Indicator helpers (self-contained, no circular import with backtest.py) ───

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-smoothed ADX. Returns ADX series (0-100; >20 = trending)."""
    hi, lo, cl = df["High"], df["Low"], df["Close"].shift()
    tr = pd.concat([(hi - lo).abs(), (hi - cl).abs(), (lo - cl).abs()], axis=1).max(axis=1)
    pdm = (hi - hi.shift()).clip(lower=0).where((hi - hi.shift()) > (lo.shift() - lo), 0.0)
    ndm = (lo.shift() - lo).clip(lower=0).where((lo.shift() - lo) > (hi - hi.shift()), 0.0)
    atr_s = tr.ewm(alpha=1 / period, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / period, adjust=False).mean() / atr_s.replace(0, np.nan)
    ndi = 100 * ndm.ewm(alpha=1 / period, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx  = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


# ── Single-TF indicator builder ───────────────────────────────────────────────

def add_mtf_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """
    Add EMA200, EMA9, EMA15, RSI14, ATR14 to a single-TF DataFrame.
    Returns df with new columns: ema200, ema9, ema15, rsi14, atr14.
    """
    df = df.copy()
    df["ema200"] = _ema(df["Close"], p["EMA_Trend"])
    df["ema9"]   = _ema(df["Close"], p["EMA_Fast"])
    df["ema15"]  = _ema(df["Close"], p["EMA_Slow"])
    df["rsi14"]  = _rsi(df["Close"], p["RSI_Period"])
    df["atr14"]  = _atr(df,          p["ATR_Period"])
    df["adx14"]  = _adx(df,          p.get("ADX_Period", 14))
    return df


# ── Multi-TF data fetch ───────────────────────────────────────────────────────

def fetch_mtf_data(
    symbol: str,
    bars_m1:  int = 6000,
    bars_m3:  int = 2500,
    bars_m15: int = 600,
    p: dict   = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Fetch M1, M3, M15 OHLCV data and add indicators to each.
    Returns (df_m1, df_m3, df_m15) — NOT yet aligned.
    Returns (empty, empty, empty) if any fetch fails.
    """
    if p is None:
        p = MTF_DEFAULT_PARAMS

    df_m1  = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1,  bars_m1)
    df_m3  = fetch_ohlcv(symbol, mt5.TIMEFRAME_M3,  bars_m3)
    df_m15 = fetch_ohlcv(symbol, mt5.TIMEFRAME_M15, bars_m15)

    empty = pd.DataFrame()
    if df_m1.empty or df_m3.empty or df_m15.empty:
        return empty, empty, empty

    df_m1  = add_mtf_indicators(df_m1,  p)
    df_m3  = add_mtf_indicators(df_m3,  p)
    df_m15 = add_mtf_indicators(df_m15, p)
    return df_m1, df_m3, df_m15


# ── M3/M15 → M1 alignment ────────────────────────────────────────────────────

def align_mtf_to_m1(
    df_m1:  pd.DataFrame,
    df_m3:  pd.DataFrame,
    df_m15: pd.DataFrame,
) -> pd.DataFrame:
    """
    Project M3 and M15 indicator columns onto the M1 index via forward-fill.
    Each M1 bar gets the value of the most recently closed M3/M15 bar.

    M3  columns added: ema200_m3, ema9_m3, ema15_m3, close_m3
    M15 columns added: ema200_m15, ema9_m15, ema15_m15, close_m15

    Returns a unified DataFrame at M1 resolution.
    """
    # M3 columns to project
    m3_cols = {
        "ema200": "ema200_m3",
        "ema9":   "ema9_m3",
        "ema15":  "ema15_m3",
        "Close":  "close_m3",
    }
    m15_cols = {
        "ema200": "ema200_m15",
        "ema9":   "ema9_m15",
        "ema15":  "ema15_m15",
        "Close":  "close_m15",
        "adx14":  "adx14_m15",
    }

    df_out = df_m1.copy()

    for src, dst in m3_cols.items():
        if src in df_m3.columns:
            projected = df_m3[src].reindex(df_m1.index, method="ffill")
            df_out[dst] = projected

    for src, dst in m15_cols.items():
        if src in df_m15.columns:
            projected = df_m15[src].reindex(df_m1.index, method="ffill")
            df_out[dst] = projected

    return df_out


# ── Filter helpers (vectorized) ───────────────────────────────────────────────

def _atr_above_median(atr_series: pd.Series, window: int = 20) -> pd.Series:
    """True where ATR14 > its rolling median over `window` bars."""
    return atr_series > atr_series.rolling(window, min_periods=1).median()


def _ema_sep_expanding(ema9_m3: pd.Series, ema15_m3: pd.Series) -> pd.Series:
    """True where abs(EMA9-EMA15) on M3 is larger than the previous M1 bar."""
    sep = (ema9_m3 - ema15_m3).abs()
    return sep > sep.shift(1)


def _candle_body_ok(df: pd.DataFrame, min_ratio: float = 0.35) -> pd.Series:
    """True where the bar's body/range >= min_ratio."""
    body  = (df["Close"] - df["Open"]).abs()
    rng   = df["High"] - df["Low"]
    valid = rng > 0
    ratio = pd.Series(np.where(valid, body / rng, 0.0), index=df.index)
    return ratio >= min_ratio


def _in_session(index: pd.DatetimeIndex, p: dict) -> pd.Series:
    """True where bar UTC hour is in London (8-12) or NY (13-17)."""
    hours = index.hour
    london = (hours >= p["London_Start"]) & (hours < p["London_End"])
    ny     = (hours >= p["NY_Start"])     & (hours < p["NY_End"])
    return pd.Series(london | ny, index=index)


def _detect_cross(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """
    +1 where fast crosses above slow.
    -1 where fast crosses below slow.
     0 otherwise.
    """
    above     = fast > slow
    above_prev = above.shift(1).fillna(False)
    cross_up   = above & ~above_prev
    cross_down = ~above & above_prev
    sig = pd.Series(0, index=fast.index, dtype=np.int8)
    sig[cross_up]   =  1
    sig[cross_down] = -1
    return sig


# ── Swing high/low for SL ─────────────────────────────────────────────────────

def _swing_low_series(lows: pd.Series, lookback: int = 5) -> pd.Series:
    """Rolling minimum Low over the past `lookback` bars (used for BUY SL)."""
    return lows.rolling(lookback, min_periods=1).min()


def _swing_high_series(highs: pd.Series, lookback: int = 5) -> pd.Series:
    """Rolling maximum High over the past `lookback` bars (used for SELL SL)."""
    return highs.rolling(lookback, min_periods=1).max()


# ── Currency strength ─────────────────────────────────────────────────────────

def compute_currency_strength(
    symbol_data: Dict[str, pd.DataFrame],
    return_window: int = 14,
    norm_window: int = 100,
) -> Dict[str, pd.Series]:
    """
    Build a strength time-series (0-100) for each major currency.

    Algorithm:
      1. For each of 28 pairs: rolling `return_window`-bar % return
      2. For each currency C at time t:
           strength[C][t] = mean(+return for pairs where C is base,
                                 -return for pairs where C is quote)
      3. Normalize each currency's raw strength to 0-100 using rolling min-max

    Returns: {"USD": pd.Series(...), "EUR": pd.Series(...), ...}
    """
    # Build a unified M1 time index from EURUSD (most liquid, reference clock)
    ref_sym = "EURUSD" if "EURUSD" in symbol_data else list(symbol_data.keys())[0]
    ref_idx = symbol_data[ref_sym].index

    raw = {c: pd.Series(0.0, index=ref_idx) for c in MAJOR_CURRENCIES}
    cnt = {c: 0 for c in MAJOR_CURRENCIES}

    for sym, df in symbol_data.items():
        if len(sym) < 6:
            continue
        base  = sym[:3].upper()
        quote = sym[3:6].upper()
        if base  not in MAJOR_CURRENCIES: continue
        if quote not in MAJOR_CURRENCIES: continue

        ret = df["Close"].pct_change(return_window).reindex(ref_idx, method="ffill")

        raw[base]  = raw[base]  + ret
        raw[quote] = raw[quote] - ret
        cnt[base]  += 1
        cnt[quote] += 1

    strength = {}
    for c in MAJOR_CURRENCIES:
        if cnt[c] == 0:
            strength[c] = pd.Series(50.0, index=ref_idx)
            continue
        avg = raw[c] / cnt[c]
        # rolling min-max normalization to 0-100
        roll_min = avg.rolling(norm_window, min_periods=1).min()
        roll_max = avg.rolling(norm_window, min_periods=1).max()
        denom    = (roll_max - roll_min).replace(0, np.nan)
        norm     = (avg - roll_min) / denom * 100
        strength[c] = norm.fillna(50.0)

    return strength


def get_pair_strength_at(
    symbol: str,
    strength_ts: Dict[str, pd.Series],
    bar_time: pd.Timestamp,
) -> Tuple[float, float]:
    """Return (base_strength, quote_strength) for symbol at bar_time."""
    base  = symbol[:3].upper()
    quote = symbol[3:6].upper()
    b = float(strength_ts.get(base,  pd.Series([50.0])).asof(bar_time) or 50.0)
    q = float(strength_ts.get(quote, pd.Series([50.0])).asof(bar_time) or 50.0)
    return b, q


# ── Master signal generator ───────────────────────────────────────────────────

def compute_mtf_signals(
    df: pd.DataFrame,
    p: dict,
    pip_size: float,
    symbol: str = None,
    strength_ts: Optional[Dict[str, pd.Series]] = None,
    news_events: Optional[list] = None,
    enable: Optional[Dict[str, bool]] = None,
) -> pd.Series:
    """
    Compute MTF EMA Alignment signals.

    Parameters
    ----------
    df          : aligned DataFrame (output of align_mtf_to_m1)
    p           : MTF_DEFAULT_PARAMS dict
    pip_size    : from get_pip_size()
    symbol      : e.g. "EURUSD" — needed for spread + strength + news filters
    strength_ts : output of compute_currency_strength() — needed for CS filter
    news_events : pre-fetched FF calendar events list — needed for news filter
    enable      : dict of filter flags (defaults to MTF_DEFAULT_FILTERS if None)

    Returns
    -------
    pd.Series of int8: 1=BUY, -1=SELL, 0=no trade
    """
    from config import MTF_DEFAULT_FILTERS
    if enable is None:
        enable = MTF_DEFAULT_FILTERS.copy()

    n   = len(df)
    sig = np.zeros(n, dtype=np.int8)

    # Required columns check
    required = ["Close", "High", "Low", "Open",
                "ema200", "ema9", "ema15", "rsi14", "atr14",
                "ema200_m3", "ema9_m3", "ema15_m3",
                "ema200_m15", "ema9_m15", "ema15_m15"]
    for col in required:
        if col not in df.columns:
            print(f"[mtf_strategy] Missing column: {col}")
            return pd.Series(sig, index=df.index)

    close  = df["Close"].values
    ema200 = df["ema200"].values
    ema9   = df["ema9"].values
    ema15  = df["ema15"].values

    ema200_m3  = df["ema200_m3"].values
    ema9_m3    = df["ema9_m3"].values
    ema15_m3   = df["ema15_m3"].values

    ema200_m15 = df["ema200_m15"].values
    ema9_m15   = df["ema9_m15"].values
    ema15_m15  = df["ema15_m15"].values

    # ── Step 1: 3-TF alignment ──────────────────────────────────────────────
    bull_m1  = close > ema200
    bull_m3  = close > ema200_m3
    bull_m15 = close > ema200_m15
    trend_m3_bull  = ema9_m3  > ema15_m3
    trend_m15_bull = ema9_m15 > ema15_m15

    bull_align = bull_m1 & bull_m3 & bull_m15 & trend_m3_bull  & trend_m15_bull
    bear_align = ~bull_m1 & ~bull_m3 & ~bull_m15 & ~trend_m3_bull & ~trend_m15_bull

    # ── Step 2: M1 EMA crossover ────────────────────────────────────────────
    cross = _detect_cross(df["ema9"], df["ema15"]).values

    raw_buy  = (cross ==  1) & bull_align
    raw_sell = (cross == -1) & bear_align

    # ── Step 3: Optional filters ────────────────────────────────────────────
    mask = np.ones(n, dtype=bool)

    if enable.get("rsi"):
        rsi = df["rsi14"].values
        rsi_buy_ok  = (rsi >= p["RSI_Buy_Lo"])  & (rsi <= p["RSI_Buy_Hi"])
        rsi_sell_ok = (rsi >= p["RSI_Sell_Lo"]) & (rsi <= p["RSI_Sell_Hi"])
        rsi_mask    = np.where(raw_buy, rsi_buy_ok, np.where(raw_sell, rsi_sell_ok, True))
        mask &= rsi_mask

    if enable.get("atr_vol"):
        atr_ok = _atr_above_median(df["atr14"], p["ATR_Med_Window"]).values
        mask  &= atr_ok

    if enable.get("session"):
        sess_ok = _in_session(df.index, p).values
        mask   &= sess_ok

    if enable.get("candle_quality"):
        body_ok = _candle_body_ok(df, p["MinBodyRatio"]).values
        mask   &= body_ok

    if enable.get("ema_separation"):
        sep_ok = _ema_sep_expanding(df["ema9_m3"], df["ema15_m3"]).values
        mask  &= sep_ok

    if enable.get("adx_chop") and "adx14_m15" in df.columns:
        adx_min = p.get("ADX_Min", 20)
        adx_ok  = df["adx14_m15"].fillna(0).values >= adx_min
        mask   &= adx_ok

    if enable.get("currency_strength") and strength_ts and symbol and len(symbol) >= 6:
        base  = symbol[:3].upper()
        quote = symbol[3:6].upper()
        b_ts  = strength_ts.get(base,  pd.Series(50.0, index=df.index))
        q_ts  = strength_ts.get(quote, pd.Series(50.0, index=df.index))
        b_arr = b_ts.reindex(df.index, method="ffill").fillna(50.0).values
        q_arr = q_ts.reindex(df.index, method="ffill").fillna(50.0).values

        cs_buy_ok  = (b_arr >= p["CS_Strong_Min"]) & (q_arr <= p["CS_Weak_Max"])
        cs_sell_ok = (q_arr >= p["CS_Strong_Min"]) & (b_arr <= p["CS_Weak_Max"])
        cs_mask    = np.where(raw_buy, cs_buy_ok, np.where(raw_sell, cs_sell_ok, True))
        mask      &= cs_mask

    if enable.get("news") and news_events is not None and symbol:
        from news_filter import is_news_blackout, get_pair_currencies
        currs      = get_pair_currencies(symbol)
        signal_idx = np.where(raw_buy | raw_sell)[0]
        for idx in signal_idx:
            ts = df.index[idx]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                from datetime import timezone
                ts = ts.replace(tzinfo=timezone.utc)
            if is_news_blackout(ts, currs, buffer_minutes=30, events=news_events):
                mask[idx] = False

    # ── Step 4: Apply mask and build signal ─────────────────────────────────
    sig = np.where(raw_buy  & mask,  np.int8(1),  sig)
    sig = np.where(raw_sell & mask,  np.int8(-1), sig)

    return pd.Series(sig, index=df.index, dtype=np.int8)


# ── SL/TP series (used by backtest) ──────────────────────────────────────────

def compute_sl_tp_arrays(
    df: pd.DataFrame,
    signals: pd.Series,
    p: dict,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    For each signal bar, compute (entry, sl, tp).

    entry = next bar Open (caller must handle indexing)
    sl    = swing_low/high ± ATR buffer
    tp    = entry ± (entry - sl) × RR

    Returns three arrays aligned to df.index (NaN where no signal).
    """
    lk   = p["SL_Lookback"]
    buf  = p["SL_Buffer_ATR"]
    rr   = p["RR_Ratio"]

    sw_lo  = _swing_low_series(df["Low"],   lk).values
    sw_hi  = _swing_high_series(df["High"], lk).values
    atr    = df["atr14"].values
    sig    = signals.values
    closes = df["Close"].values

    n   = len(df)
    sl_arr = np.full(n, np.nan)
    tp_arr = np.full(n, np.nan)

    for i in range(n):
        if sig[i] == 1:
            sl  = sw_lo[i] - atr[i] * buf
            sl_dist = closes[i] - sl
            if sl_dist <= 0:
                continue
            tp  = closes[i] + sl_dist * rr
            sl_arr[i] = sl
            tp_arr[i] = tp
        elif sig[i] == -1:
            sl  = sw_hi[i] + atr[i] * buf
            sl_dist = sl - closes[i]
            if sl_dist <= 0:
                continue
            tp  = closes[i] - sl_dist * rr
            sl_arr[i] = sl
            tp_arr[i] = tp

    return sig, sl_arr, tp_arr
