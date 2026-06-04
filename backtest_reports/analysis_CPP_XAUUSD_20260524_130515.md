# Backtest Analysis: CPP — XAUUSD — Daily  

## 1. Overall Verdict  
**Unprofitable**  
- Negative return (-10.5%), profit factor <1 (0.76), and max drawdown of 25.6% indicate consistent losses.  
- Zero days met the performance target (0/42), signaling systemic underperformance.  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Occasional large winning trades (e.g., $112.54 gain on 2026-02-05).  
- Low median daily losses (0.76% average loss size).  

**Weaknesses**:  
- Extremely low win rate (38.1%) and profit factor <1.  
- High drawdown frequency (1 day >6% DD, 25.6% max DD).  
- Inconsistent performance with no target hits.  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trades to London session (07:00–12:00 UTC) to focus on high-liquidity periods.  
- **Risk Management**: Reduce position size by 30% to mitigate large losses (e.g., cap daily DD at 3%).  
- **Filter Conditions**: Avoid trading during low volatility (ATR < 1.5) or major news events.  
- **Trade Duration**: Increase minimum trade duration to 2 hours to avoid whipsaws.  

## 4. Risk Assessment  
- **High Risk**: 25.6% max drawdown and frequent large losses (e.g., $101.27 loss on 2026-02-02).  
- **Liquidity Risk**: Large losses on specific dates (e.g., $45.22 loss on 2025-10-22) suggest potential slippage or illiquidity.  
- **Survivability**: 4.75% single-day DD (2025-10-22) exceeds the 6% threshold, posing capital erosion risks.  

## 5. Recommended Next Action  
**Disable**  
- The strategy shows no edge with consistent losses and high risk. Immediate deployment is inadvisable.  
- If further analysis is warranted, focus on optimizing entry/exit logic or abandoning the strategy.  

SUMMARY: Unprofitable strategy with high drawdowns and zero target hits; disable immediately.