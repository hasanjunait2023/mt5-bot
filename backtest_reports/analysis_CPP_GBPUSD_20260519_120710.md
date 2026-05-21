# Backtest Analysis: CPP Strategy on GBPUSD  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a small positive return (+3.7%) and acceptable drawdowns (Max DD 5.7%, p90 Daily DD 0.95%), but fails to meet performance targets (0/29 days) and exhibits inconsistent profitability.  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Profit factor of 1.23 indicates winning trades outperform losses.  
- Drawdowns remain within acceptable limits (<6% daily DD).  
- Occasional high-profit days (e.g., $+37.75 on 2025-01-24).  

**Weaknesses**:  
- Extremely low win rate (40.6%) and median wins/day of 0.  
- Frequent losing streaks (e.g., 5 consecutive losses in May 2026).  
- Zero days hit the performance target (>=15W / <=6L / <=6.0%DD).  
- Low trade frequency (1.1 trades/day) and inconsistent profitability.  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Focus on high-liquidity sessions (e.g., **London 07:00-12:00 UTC** or **New York overlap 12:00-16:00 UTC**) to improve trade quality.  
- **Entry Filters**: Add volatility filters (e.g., avoid trading during low ATR periods) or trend confirmation (e.g., require alignment with 20-period EMA).  
- **Risk Management**: Reduce position size by 30-50% to mitigate impact of losing streaks.  
- **Exit Rules**: Tighten take-profit levels (e.g., 1:1 R/R) to lock in profits during sparse winning trades.  

## 4. Risk Assessment  
- **Low Win Rate Risk**: Strategy relies heavily on large wins to offset frequent losses, increasing sensitivity to market regime changes.  
- **Inconsistency Risk**: Lack of target hits and median wins/day = 0 suggests poor adaptability to varying market conditions.  
- **Drawdown Risk**: While current DD is acceptable, a 1.82% max daily DD could escalate with higher leverage or adverse volatility.  

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize improving win rate and consistency via session filtering, entry/exit rule refinements, and risk adjustments. Avoid deployment until performance targets are met in backtests.  

SUMMARY: Marginal strategy with +3.7% return but 0/29 days hitting targets; optimize session timing, entry filters, and risk parameters before deployment.