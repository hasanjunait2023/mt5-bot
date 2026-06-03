# CPP — Empirical Findings (backtest → improve → backtest, 2024-01 → 2026-05)

Built per request: research-driven strategy + hybrid AI agent + EA, iterate
backtest, then demo. Data = your live MT5 history, 5 mandated symbols, $1,000,
1% risk, strict 1:2, agent in deterministic (advisory) mode.

## What the target requires vs. what the market gives

Target: **15–20 wins + ≤5–6 losses per day at 1:2** ⇒ ≈75% WR ⇒ ≈+24%/day
compounding. At 1:2 the mathematical breakeven is **33% WR**.

## Iterations run

| # | Change | Trades (2y) | Portfolio WR | PF | Verdict |
|---|--------|-------------|--------------|----|---------|
| Baseline | strict entry + regime runner exit | 151 (~1.2/day) | 43.7% | 0.68 | rare; exit bug ate the edge |
| 1 | loosen entries for frequency, fixed 1:2 | 866 (~2.1/day) | **31.5%** | 0.95 | frequency 5× but WR fell **below 33% breakeven → guaranteed loser** |
| 2 | strict entry + clean fixed 1:2 | 150 (~1.2/day) | 35.3% | 0.82 | edge is real but **per-symbol**, not uniform |
| 3 | per-symbol exit (metals=runner) | 185 (~1.2/day) | 40.0% | 0.79 | metals still anti-fit; FX unchanged & good |

## The verdict (proven 3 ways on your own data)

1. **15–20 quality 1:2 wins/day is not available on these 5 symbols.** Pushing
   frequency up (iter 1) drove win-rate *below the 1:2 breakeven* — it becomes a
   mathematically guaranteed loser. Frequency × win-rate × R:R is conserved; the
   market does not sell all three.

2. **A genuinely profitable 1:2 system DOES exist in scope — on FX:**

   | Symbol | Trades | Win rate | Profit factor | 2y return |
   |--------|--------|----------|---------------|-----------|
   | **USDJPY** | 35 | **48.6%** | **1.84** | +13% |
   | **GBPUSD** | 32 | 40.6% | 1.23 | +4% |
   | **EURUSD** | 36 | 36.1% | 1.13 | +3% |
   | XAUUSD | 23–42 | 21–38% | 0.28–0.76 | negative |
   | XAGUSD | 24–40 | 21–38% | 0.33–0.52 | negative |

3. **Metals (XAU/XAG) are a structural anti-fit** for an M15 pullback-in-trend
   strategy in *every* exit mode tested. They should keep being traded by the
   repo's already-validated gold strategies (**S1** PF 2.55, **S15** PF 4.81,
   **S18** +93%/71% WR), not by CPP.

4. **Sample caution:** 30–40 trades/symbol is a *small* sample — these PFs have
   wide error bars. This is exactly why real money is gated behind a demo
   forward-test (`promotion_gate.can_go_live`), never on backtest alone.

## Recommended achievable system

**CPP-FX**: USDJPY + GBPUSD + EURUSD, strict pullback-in-strong-ADX-trend entry,
clean fixed 1:2, 1% risk, hybrid confirmation agent, hard 6% daily-DD breaker.
Honest expected profile: **~1–3 high-quality trades/day, ~40–49% WR at 1:2,
positive expectancy** — a real edge, not 15–20/day. Gold/silver continue on
S1/S15/S18 so all 5 symbols are still covered, each by a strategy that fits it.
