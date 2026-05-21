"""Time Series Momentum (TSMOM) — Moskowitz, Ooi, Pedersen 2012.

Sign of past N-period return predicts next period. Position sized inverse to EWMA vol.
2 parameters: lookback (12 months for FX, ~4 weeks for crypto) and volatility target (40% ann.).

Reference: Moskowitz, T.J., Ooi, Y.H., Pedersen, L.H. (2012). "Time Series Momentum".
Journal of Financial Economics, 104(2), 228-250.
"""

from __future__ import annotations

import math
from typing import Any

# Paper-validated constants — keep these stable
LOOKBACK_BARS_DEFAULT = 252      # ~12 months of D1 bars (252 trading days)
VOL_TARGET_ANN = 0.40            # 40% annualized vol target (paper default)
EWMA_DECAY = 0.94                # RiskMetrics standard
BARS_PER_YEAR = 252              # for annualization


def _ewma_vol(returns: list[float], decay: float = EWMA_DECAY) -> float:
    """EWMA volatility (annualized). Paper eq.1: σ²_t = 261 * Σ (1-δ)δ^i (r - r̄)²"""
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var = 0.0
    weight_sum = 0.0
    weight = 1.0
    # Newest sample gets highest weight
    for r in reversed(returns):
        var += weight * (r - mean_r) ** 2
        weight_sum += weight
        weight *= decay
    if weight_sum == 0:
        return 0.0
    return math.sqrt(var / weight_sum * BARS_PER_YEAR)


def compute(closes: list[float], lookback: int = LOOKBACK_BARS_DEFAULT,
            vol_target: float = VOL_TARGET_ANN) -> dict[str, Any]:
    """Compute TSMOM signal + sizing for a single instrument.

    Returns:
        {
          "signal": -1 | 0 | +1,         # sign of past lookback return
          "lookback_return": float,      # raw past return (informational)
          "vol_annualized": float,       # current EWMA vol
          "position_scalar": float,      # how much to scale base lot (vol_target / vol)
          "lookback_bars_used": int,
        }
    """
    if len(closes) < max(20, lookback // 4):
        return {"signal": 0, "lookback_return": 0.0, "vol_annualized": 0.0,
                "position_scalar": 0.0, "lookback_bars_used": 0}

    # Past N-bar return (use what's available if < lookback)
    effective_lookback = min(lookback, len(closes) - 1)
    past_close = closes[-effective_lookback - 1]
    last_close = closes[-1]
    if past_close <= 0:
        return {"signal": 0, "lookback_return": 0.0, "vol_annualized": 0.0,
                "position_scalar": 0.0, "lookback_bars_used": 0}

    lookback_return = (last_close / past_close) - 1.0

    # Daily log returns for EWMA vol (use last 60 bars for stability)
    vol_window = min(60, len(closes) - 1)
    daily_returns = [math.log(closes[i] / closes[i - 1])
                     for i in range(-vol_window, 0) if closes[i - 1] > 0]
    vol_ann = _ewma_vol(daily_returns)

    # Signal: sign of past return
    signal = 1 if lookback_return > 0 else -1 if lookback_return < 0 else 0

    # Position scalar (paper: 40% / σ). Clamp [0.1, 5.0] for sanity.
    scalar = (vol_target / vol_ann) if vol_ann > 0.01 else 1.0
    scalar = round(max(0.1, min(5.0, scalar)), 3)

    return {
        "signal": signal,
        "lookback_return": round(lookback_return, 4),
        "vol_annualized": round(vol_ann, 4),
        "position_scalar": scalar,
        "lookback_bars_used": effective_lookback,
        "bullish": signal > 0,
        "bearish": signal < 0,
    }


def compute_crypto(closes: list[float], lookback: int = 28) -> dict[str, Any]:
    """Crypto-tuned TSMOM (Liu & Tsyvinski 2021): 1-4 week lookback. Default 28 bars."""
    return compute(closes, lookback=lookback, vol_target=VOL_TARGET_ANN)
