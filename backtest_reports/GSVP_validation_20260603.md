# GS-VP Adaptive — 2-Year Validation Report (2026-06-03)

Strategy: `_gsvp_adaptive` in [trading_agents/scalp/backtest.py](../trading_agents/scalp/backtest.py)
(regime-adaptive volume profile: VA-reversion + breakout-retest + naked-POC, M15 entries,
tiered volume trust). VP levels from `session_volume_profile()` (prior Daily session).

Data: 60,000 M15 bars/symbol from the live MT5 bridge (Exness), real spread cost charged at
entry **and** exit. Coverage: Gold/Silver ~2.5 yr, EUR/GBP ~2.4 yr, BTC ~1.7 yr.
Cache: `backtest/_cache/*_M15.json`. Diagnostic: `python -m backtest.gsvp_diag --bars 60000 [--half]`.

## Full-sample (real cost)

| Pair | Trades | WR% | PF | A=reversion PF | B=breakout PF |
|---|---|---|---|---|---|
| GBPUSD | 27 | 40.7 | **1.59** | 0.92 (n7) | 1.78 (n20) |
| XAUUSD | 99 | 38.4 | **1.37** | 1.99 (n17) | 1.26 (n82) |
| EURUSD | 22 | 40.9 | **1.14** | – (n3) | 1.41 (n19) |
| BTCUSD | 327 | 36.1 | 1.01 | 0.81 (n45) | 1.05 (n282) |
| XAGUSD | 88 | 36.4 | 0.56 | 0.26 (n13) | 0.59 (n75) |

## In/out-of-sample halves (the robustness test)

| Pair | IS PF | OOS PF | Read |
|---|---|---|---|
| **GBPUSD** | 1.44 | 1.69 | ✅ robust — profitable both halves |
| **EURUSD** | 1.24 | 1.03 | ✅ profitable both halves (thin sample) |
| BTCUSD | 1.01 | 1.02 | ⚪ consistent breakeven — no edge yet |
| XAUUSD | 0.77 | 1.69 | ⚠️ regime-dependent — full-sample 1.37 is OOS-driven, NOT robust |
| XAGUSD | 0.35 | 0.65 | ❌ fails both halves → drop |

## Verdict

- **Ship (robust, PF≥1.3 / profitable both halves): GBPUSD, EURUSD** — breakout-retest (Playbook B)
  is the edge; it survived both halves on FX even on tick volume.
- **Hold / cautious: XAUUSD** — strong full-sample (1.37) but regime-dependent (loses in the IS half).
  Do not treat as proven; trade reduced size or as confluence only until it holds across regimes.
- **No edge yet: BTCUSD** — remarkably consistent ~1.01 both halves (real volume, entry timing sound)
  but 2R targets don't beat 36% WR + cost. Promising base for future work, not live-ready.
- **Drop: XAGUSD** — unprofitable both halves; M15 spread (0.05×2) too large vs the moves.

## Honest caveats (do not overclaim)

- FX trade counts are **small** (10–15/half) — direction is consistent but statistical confidence
  is limited. GS-VP is highly selective (~11 trades/yr/pair): better as **one strategy among many /
  a confluence layer** than a standalone money-maker. Matches prior finding "VP best as confluence".
- Playbook A (reversion) is **noise at this sample size** — its PF flips sign IS↔OOS on every pair
  (e.g. BTC A 0.32→2.22). The durable edge is Playbook B (breakout-retest).
- Tuned filters: M15 EMA50/200 trend-strength gate (≥0.3 ATR), wick-rejection confirmation,
  flat-regime gate for reversion, tier-dependent not-overextended retest, tiered volume trust.
  Further tuning to force BTC/Gold to 1.3 was avoided — the half-split shows it would be overfitting.

## Engine fix shipped alongside

`session_volume_profile()` (indicators.py) had a low-magnitude bug: `int(hi)` cache key aliased
same-magnitude days (FX/silver returned a stale profile) and 2-dp rounding collapsed FX levels
(1.16xxx→1.16). Fixed with a precision-safe cache key + magnitude-aware rounding (`round_dp`),
backward-compatible for gold/crypto. No other code currently calls it.
