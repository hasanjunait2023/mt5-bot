```markdown
# Backtest Analysis: CPP — GBPUSD — Daily

## 1. Overall Verdict  
**Marginal**  
The strategy shows slight profitability (+3.7%) with a profit factor of 1.23 and max DD of 5.7%, but fails to meet performance targets (0/29 days) and exhibits a low win rate (40.6%).

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Profit factor >1 (1.23) indicates positive expectancy per trade.  
- Max drawdown (5.7%) remains below the 6% threshold.  
- Most daily drawdowns are modest (p90: 0.95%).  

**Weaknesses**:  
- Extremely low win rate (40.6%) and median wins/day of 0, suggesting inconsistent profitability.  
- No days met the performance target (>=15W / <=6L / <=6.0%DD), indicating systemic underperformance.  
- High frequency of losing days (18 losses vs. 14 wins in 32 trades).  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trades to the London session (07:00–12:00 UTC) to capitalize on GBPUSD volatility.  
- **Risk Management**: Reduce position size by 30% to mitigate impact of frequent losses.  
- **Filtering**: Add a trend filter (e.g., 200-period EMA) to avoid counter-trend entries.  
- **Exit Rules**: Extend take-profit targets by 20% to capture larger moves, given the low win rate.  

## 4. Risk Assessment  
- **Moderate Risk**: Drawdowns are controlled (max 5.7%), but the low win rate and lack of target achievement pose operational risks.  
- **Liquidity Risk**: Sparse trade frequency (1.1/day) may lead to execution challenges in live markets.  

## 5. Recommended Next Action  
**Optimize Further**  
Focus on improving win rate via session/timeframe filtering and refining entry/exit logic. Re-test with adjusted parameters before considering deployment.

SUMMARY: Marginal strategy with controlled DD but low win rate and zero target hits; optimize session timing and risk parameters before redeploying.
```