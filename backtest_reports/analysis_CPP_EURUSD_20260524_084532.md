# Backtest Analysis: CPP — EURUSD — Daily  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a small positive return (+2.6%) with controlled drawdowns (max DD 6.2%) but fails to meet performance targets (0/34 days) and has a low win rate (36.1%).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Profit factor >1 (1.13) indicates winning trades outperform losses.  
- Low daily drawdowns (max 1.0%, p90 0.99%).  
- No days exceed 6% DD threshold.  

**Weaknesses**:  
- Extremely low win rate (36.1%) and median wins/day = 0.  
- Fails to hit daily performance targets (0/34 days).  
- Inconsistent profitability (e.g., 13 losing days vs. 10 winning days).  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trades to **London session (07:00–12:00 UTC)** where EURUSD volatility is highest.  
- **Risk Management**: Reduce position size by 30–50% to account for low win rate.  
- **Filtering**: Exclude trades during low-liquidity periods (e.g., weekends, holidays) and major news events.  
- **Take Profit/Stop Loss**: Adjust TP/SL ratios to prioritize larger wins (e.g., 2:1 reward-to-risk).  

## 4. Risk Assessment  
- **Drawdown Risk**: Moderate (max DD 6.2% is acceptable but could worsen with higher leverage).  
- **Consistency Risk**: High (median wins/day = 0, frequent losing streaks).  
- **Sample Size Risk**: Only 36 trades over 2+ years; insufficient for robust validation.  

## 5. Recommended Next Action  
**Optimize Further**  
Focus on improving win rate (e.g., entry signal refinement) and validating strategy on extended/out-of-sample data before deployment.  

SUMMARY: Marginal profitability with low win rate and missed targets; optimize session timing, risk parameters, and filters before deployment.