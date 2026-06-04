## CPP â€” XAGUSD Daily Backtest Analysis

---

### 1. Overall Verdict: ðŸ”´ UNPROFITABLE

No ambiguity. PF 0.50, -48.6% return, 56.7% max DD, 0/39 days hit target. This strategy destroys capital on XAGUSD.

> **Note:** Current run = Previous run, byte-for-byte identical. No parameter change was applied between submissions.

---

### 2. Key Strengths

- **None material.** 1.0 trade/day means clean signal generation, but that's a neutral trait when every metric is red.

---

### 3. Key Weaknesses

| Issue | Detail |
|---|---|
| Win rate 37.5% | Needs ~45%+ at 1:2 RR to break even â€” not close |
| PF 0.50 | Returns $0.50 per $1 risked |
| Catastrophic tail events | 4 days in 2026 alone: -27%, -15%, -17%, -20% single-day DD |
| Equity-based lot sizing backfires | Early losses ~$5â€“15; 2026 losses $120â€“267 â€” compounding amplifies ruin |
| 0/39 days hit target | Target (â‰¥15W/â‰¤6L/â‰¤6%DD) never reached once |
| p90 daily DD = 8.5% | 90th percentile *already* exceeds the 6% hard limit |

**Root cause:** CPP's pullback logic has no edge on XAGUSD. Silver's volatility regime (especially Febâ€“Apr 2026 macro moves) produces outsized stop-outs that equity-based sizing then compounds into account-destroying events.

---

### 4. Specific Parameter Recommendations

These are optimization directions only â€” **do not deploy**:

- **Hard cap daily DD at 3%** (not 6%) for metals; silver vol is ~2Ã— USDJPY
- **Fixed lot sizing only** â€” equity-based compounding turns a losing strategy into a ruin strategy
- **Add HTF bias filter (D1 EMA-200):** only trade in trend direction; 37.5% WR suggests CPP is counter-trend on silver
- **Restrict to H4 or H1 timeframe** â€” daily bars give 1 trade/day with no intraday context; lower TF adds confluence
- **Regime filter:** exclude periods where ATR(14) > 1.5Ã— its 3-month average (the 2026 blow-ups all occurred during high-vol macro events)

---

### 5. Risk Assessment

| Metric | Value | Threshold | Status |
|---|---|---|---|
| Max DD | 56.7% | 20% | ðŸ”´ 3Ã— limit |
| Days > 6% DD | 6/39 | 0 ideally | ðŸ”´ |
| PF | 0.50 | â‰¥1.3 | ðŸ”´ |
| Win Rate | 37.5% | â‰¥45% | ðŸ”´ |
| Target hit rate | 0% | >50% | ðŸ”´ |

**Capital risk: EXTREME.** If live, this configuration would have erased >50% of account. The 2026-02-02 single-day -27.44% event alone is disqualifying.

---

### 6. Recommended Next Action: ðŸš« DISABLE

CPP on XAGUSD at Daily TF has no edge. Per existing portfolio verdict (memory), metals route to S1/S15/S18 â€” that decision is confirmed by these numbers. Do not optimize further; redirect effort to those strategies.

---

SUMMARY: CPP XAGUSD Daily â€” PF 0.50, -48.6% return, 56.7% max DD, 0/39 target days â€” deeply unprofitable, disable immediately, route silver to S1/S15/S18.