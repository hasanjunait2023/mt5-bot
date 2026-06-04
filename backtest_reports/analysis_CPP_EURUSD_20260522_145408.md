# Backtest Analysis: CPP — EURUSD — Daily  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a slight positive return (+2.6%) and meets the max drawdown target (6.2% < 6.0%), but its low win rate (36.1%) and weak profit factor (1.13) indicate marginal profitability.  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Low daily drawdowns (p90: 0.99%, max: 1.0%).  
- Max drawdown within target (6.2%).  
- Consistent small wins when trades succeed.  

**Weaknesses**:  
- Very low win rate (36.1%) and median wins/day = 0.  
- High frequency of losing days (22/34 days with losses).  
- Profit factor barely above 1 (1.13), indicating minimal edge.  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Focus on London session (07:00–12:00 UTC) to capitalize on EURUSD volatility.  
- **Entry Filter**: Require additional confirmation (e.g., RSI divergence or volume spikes) to reduce false signals.  
- **Risk Management**: Reduce position size by 30% to mitigate impact of losing streaks.  
- **Stop-Loss Adjustment**: Tighten stops to 0.8% from current average (~1.0%) to limit daily DD.  

## 4. Risk Assessment  
- **Drawdown Risk**: Acceptable (max DD 6.2%), but prolonged losing streaks (e.g., 2 consecutive losses on 2025-02-06) could strain capital.  
- **Consistency Risk**: Only 13/34 days profitable; strategy lacks reliability.  
- **Market Risk**: Performance may degrade in low-volatility or trending markets.  

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize entry/exit rule refinement and session filtering before retesting. Avoid deployment until win rate and profit factor improve.  

SUMMARY: Marginal strategy with low win rate (36.1%) and weak edge (PF 1.13); optimize entry rules and session timing before redeploying.