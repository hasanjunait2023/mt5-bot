# Backtest Analysis: CPP — EURUSD — Daily  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a slight positive return (+2.6%) and stays within max drawdown limits (6.2% < 6.0% target), but its win rate (36.1%) and profit factor (1.13) are barely profitable. It fails to hit daily performance targets (0/34 days), indicating inconsistency.  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Low daily drawdowns (max 1.0%, p90 0.99%).  
- Profit factor slightly above 1.0.  
- Some high-impact winning days (e.g., +$20.53 on 2024-10-10).  

**Weaknesses**:  
- Extremely low win rate (36.1%) and median wins/day = 0.  
- Fails to meet daily performance targets entirely.  
- Overly reliant on sporadic wins to offset frequent losses.  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trading to **London session (07:00–12:00 UTC)** or **New York overlap (12:00–16:00 UTC)** to focus on high-liquidity periods.  
- **Risk Management**: Reduce risk per trade to **1.5% of capital** (current max DD is 1.0% daily, but cumulative risk is high).  
- **Entry Filter**: Add a **trend filter** (e.g., 200-period EMA) to avoid counter-trend trades.  
- **Profit Target Adjustment**: Increase profit targets to **1.5x average win size** (current ~$15–$20) to improve reward/risk ratio.  

## 4. Risk Assessment  
- **Drawdown Risk**: Acceptable (max DD 6.2% < 6.0% target), but compounding losses from frequent small losses could erode capital over time.  
- **Survivability Risk**: Low win rate and lack of consistent profitability raise concerns about long-term viability.  
- **Market Sensitivity**: Unproven in volatile or ranging markets (no data on performance during high-impact news).  

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize entry/exit rule refinement and session filtering before retesting. Avoid deployment until win rate and consistency improve.  

SUMMARY: Marginal strategy with low win rate and inconsistent performance; optimize session timing and risk parameters before redeploying.