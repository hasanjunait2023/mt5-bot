# Backtest Analysis: CPP — EURUSD — Daily  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a slight positive return (+2.6%) with controlled drawdowns (max 6.2%) but fails to meet performance targets (0/34 days) and has a low win rate (36.1%).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Profit factor >1 (1.13) indicates winning trades outsize losses.  
- Drawdowns are tightly managed (daily DD <1%, no breaches of 6% threshold).  
- Consistent trade size (1.1 trades/day).  

**Weaknesses**:  
- Extremely low win rate (36.1%) and median wins/day = 0.  
- No days meet the performance target (>=15W / <=6L / <=6%DD).  
- Inconsistent profitability (only 13 winning days vs. 23 losing days).  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Restrict to London session **07:00–12:00 UTC** to focus on high-liquidity hours.  
- **Entry Filter**: Add a volatility filter (e.g., avoid trades if ATR < 0.5% of price).  
- **Risk Management**: Reduce risk per trade to **1% of capital** (current DD suggests higher exposure).  
- **Exit Rules**: Tighten take-profit/stop-loss to **1:1.5 risk-reward ratio** to improve win rate.  

## 4. Risk Assessment  
- **Low**: Drawdowns are within acceptable limits.  
- **Moderate**: Strategy relies heavily on occasional large wins (e.g., $+19–20 trades), which may not be sustainable.  
- **High**: Low win rate and lack of target achievement suggest poor robustness in live markets.  

## 5. Recommended Next Action  
**Optimize Further**  
Focus on improving win rate via entry/exit refinements and volatility filtering before retesting.  

SUMMARY: Marginal strategy with tight risk control but low win rate and no target achievement; optimize entry/exit rules and session timing before redeploying.