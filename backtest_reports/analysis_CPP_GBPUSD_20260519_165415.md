```markdown
# Backtest Analysis: CPP — GBPUSD — Daily

## 1. Overall Verdict  
**Marginal**  
Positive return (+3.7%) and profit factor (1.23) but low win rate (40.6%) and high max DD (5.7%) relative to gains.

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Controlled daily drawdowns (max 1.82%, p90 0.95%).  
- No days exceeded 6% DD threshold.  
- Profit factor >1 indicates winning trades outsize losses.  

**Weaknesses**:  
- Extremely low win rate (40.6%) and median wins/day = 0.  
- Inconsistent performance (0/29 days hit targets).  
- High max DD (5.7%) vs. total return (+3.7%).  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trades to London session (07:00–12:00 UTC) to focus on high-liquidity GBPUSD moves.  
- **Entry Filter**: Add volatility filter (e.g., avoid trades if ATR < 0.5% daily range).  
- **Position Sizing**: Reduce lot size by 30% to lower daily DD impact.  
- **Stop-Loss Adjustment**: Tighten SL to 1.5x average daily range to reduce loss magnitude.  

## 4. Risk Assessment  
- **Moderate Risk**: Daily DDs are controlled, but overall max DD (5.7%) exceeds returns, creating negative risk-reward ratio.  
- **Liquidity Risk**: Low trade frequency (1.1/day) may indicate poor entry signal reliability.  
- **Psychological Risk**: Low win rate could erode trader confidence during live deployment.  

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize improving win rate via entry/exit rule refinements or market context filters (e.g., trend alignment). Re-test with adjusted parameters before deployment.

SUMMARY: Marginal strategy with controlled DD but low win rate and high relative drawdown; optimize entry rules and session timing before deployment.
```