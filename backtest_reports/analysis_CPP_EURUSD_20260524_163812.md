# Backtest Analysis: CPP — EURUSD — Daily  

## 1. Overall Verdict  
**Marginal** — The strategy shows slight profitability (+2.6% return, profit factor 1.13) but fails to meet performance targets (0/34 days hitting goals) and has a low win rate (36.1%).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Controlled risk: Max drawdown 6.2% (within 6% limit), daily DDs <1%.  
- Positive profit factor (1.13) indicates winning trades outsize losses.  

**Weaknesses**:  
- Extremely low win rate (36.1%) and median wins/day = 0.  
- Fails to meet performance targets (0 days with >=15W / <=6L).  
- Inconsistent performance: 14 losing days vs. 13 winning days.  

## 3. Specific Parameter Recommendations  
- **Restrict trading to London session (07:00–12:00 UTC)** to capitalize on higher EURUSD volatility.  
- **Adjust entry filters** to improve win rate (e.g., tighter risk-reward ratios or stronger signal confirmation).  
- **Increase trade frequency** cautiously by expanding session hours or refining filters.  

## 4. Risk Assessment  
- **Low per-trade risk**: Daily DDs rarely exceed 1%, aligning with conservative risk management.  
- **Drawdown risk**: Max DD (6.2%) approaches the 6% threshold, leaving minimal buffer.  
- **Survivability risk**: Low win rate and sparse winning days could lead to prolonged drawdowns.  

## 5. Recommended Next Action  
**Optimize further** — Focus on improving win rate and consistency before deployment. Test session restrictions and entry/exit rule tweaks.  

SUMMARY: Marginal profitability with controlled risk but poor win rate and target adherence; optimize entry rules and session timing before deployment.