```markdown
# Backtest Analysis: CPP Strategy on USDJPY

## 1. Overall Verdict  
**Marginal**  
Positive return (+13.3%) and strong profit factor (1.84) indicate potential, but low win rate (48.6%) and failure to meet daily performance targets (0/34 days) raise concerns about consistency.

---

## 2. Key Strengths and Weaknesses  

**Strengths:**  
- **Profitability:** Positive return and profit factor above 1.8 suggest edge in winning trades.  
- **Risk Control:** Low max drawdown (4.2%) and daily DD (p90: 0.96%) indicate disciplined risk management.  

**Weaknesses:**  
- **Low Win Rate:** 48.6% win rate and median wins/day = 0 signal inconsistency.  
- **Target Failure:** No days met the performance target (>=15W / <=6L / <=6% DD), suggesting unrealistic or misaligned goals.  
- **Inactivity:** Only 1 trade/day on average, limiting potential.  

---

## 3. Specific Parameter Recommendations  
- **Session Restriction:** Test strategy during **Tokyo session (22:00-07:00 UTC)** to exploit USDJPY volatility.  
- **Entry Filters:** Add time-based filters (e.g., avoid low-liquidity hours) or price-action confirmation to improve win rate.  
- **Position Sizing:** Increase lot size by 20% to capitalize on profitable trades while monitoring DD impact.  

---

## 4. Risk Assessment  
- **Low Drawdown Risk:** Max DD (4.2%) and daily DD (0.97%) are well within acceptable limits.  
- **Execution Risk:** Low trade frequency (1/day) may lead to missed opportunities or overfitting.  
- **Market Dependency:** Strategy may underperform during low-volatility periods (e.g., holidays).  

---

## 5. Recommended Next Action  
**Optimize Further**  
Focus on improving win rate via entry/exit refinements and validate robustness across multiple market conditions before deployment.

SUMMARY: Marginal strategy with solid risk control but inconsistent performance; optimize entry filters and test Tokyo session focus before deployment.
```