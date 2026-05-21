"""Pairs Trading via Distance Method — Gatev, Goetzmann, Rouwenhorst 2006.

Sum of squared deviations of normalized prices. Trade when spread > 2σ_formation,
exit when spread crosses zero. 3 parameters.

Reference: Gatev, E., Goetzmann, W.N., Rouwenhorst, K.G. (2006). "Pairs Trading:
Performance of a Relative-Value Arbitrage Rule". Review of Financial Studies, 19(3).
"""

from __future__ import annotations

import math
from typing import Any

# Paper-validated parameters
FORMATION_BARS_DEFAULT = 252     # 12 months of D1 (or 48 weeks of H4)
ENTRY_SIGMA_THRESHOLD = 2.0      # |spread z-score| > 2σ → enter
EXIT_SIGMA_THRESHOLD = 0.0       # cross zero → exit (paper exact)


def _normalize(prices: list[float]) -> list[float]:
    """Normalize cumulative returns starting from 1.0 (paper eq.)"""
    if not prices or prices[0] <= 0:
        return []
    return [p / prices[0] for p in prices]


def compute_pair(
    closes_a: list[float],
    closes_b: list[float],
    formation_bars: int = FORMATION_BARS_DEFAULT,
    entry_z: float = ENTRY_SIGMA_THRESHOLD,
    exit_z: float = EXIT_SIGMA_THRESHOLD,
) -> dict[str, Any]:
    """Compute pairs-trading signal for a single asset pair (A, B).

    Returns:
      {
        "spread": float,             # P̃_a - P̃_b at last bar
        "zscore": float,             # spread / formation_sigma
        "formation_sigma": float,    # std of spread during formation
        "ssd": float,                # sum squared deviations (lower = better pair)
        "signal": "LONG_A_SHORT_B" | "SHORT_A_LONG_B" | "EXIT" | "NONE",
        "entry_threshold": float,
        "exit_threshold": float,
      }
    """
    if len(closes_a) < 30 or len(closes_b) < 30:
        return _empty()

    n = min(len(closes_a), len(closes_b), formation_bars)
    a_win = closes_a[-n:]
    b_win = closes_b[-n:]

    # Normalize both series to start at 1.0
    p_a = _normalize(a_win)
    p_b = _normalize(b_win)
    if not p_a or not p_b:
        return _empty()

    # Spread = normalized A minus normalized B
    spreads = [pa - pb for pa, pb in zip(p_a, p_b)]
    if not spreads:
        return _empty()

    mean_spread = sum(spreads) / len(spreads)
    variance = sum((s - mean_spread) ** 2 for s in spreads) / len(spreads)
    formation_sigma = math.sqrt(variance)
    ssd = sum(s ** 2 for s in spreads)

    last_spread = spreads[-1]
    zscore = (last_spread - mean_spread) / formation_sigma if formation_sigma > 0 else 0.0

    # Signal logic (paper exact)
    if zscore > entry_z:
        signal = "SHORT_A_LONG_B"   # A overpriced relative to B → short A, long B
    elif zscore < -entry_z:
        signal = "LONG_A_SHORT_B"   # A underpriced → long A, short B
    elif abs(zscore) < abs(exit_z) + 0.1:
        signal = "EXIT"             # mean-reverted (within exit band)
    else:
        signal = "NONE"

    return {
        "spread": round(last_spread, 6),
        "zscore": round(zscore, 3),
        "formation_sigma": round(formation_sigma, 6),
        "ssd": round(ssd, 4),
        "signal": signal,
        "entry_threshold": entry_z,
        "exit_threshold": exit_z,
        "long_a": signal == "LONG_A_SHORT_B",
        "short_a": signal == "SHORT_A_LONG_B",
        "exit_now": signal == "EXIT",
        "bars_used": n,
    }


def _empty() -> dict[str, Any]:
    return {"spread": 0.0, "zscore": 0.0, "formation_sigma": 0.0, "ssd": 0.0,
            "signal": "NONE", "entry_threshold": ENTRY_SIGMA_THRESHOLD,
            "exit_threshold": EXIT_SIGMA_THRESHOLD,
            "long_a": False, "short_a": False, "exit_now": False, "bars_used": 0}
