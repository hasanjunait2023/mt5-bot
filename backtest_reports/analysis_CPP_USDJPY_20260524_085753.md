# Backtest Analysis: CPP Strategy on USDJPY  

## 1. Overall Verdict  
**Marginal**  
While the strategy shows a positive return (+13.3%) and controlled drawdowns (max DD 4.2%), it fails to meet performance targets (0/34 days) and has a near-breakeven win rate (48.6%).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- **Profit Factor**: 1.84 indicates efficient capital utilization.  
- **Drawdown Control**: No days exceed 6% DD; p90 daily DD is 0.96%.  
- **Win Size**: Winning trades average ~$18–22 vs. losses of ~$5–11.  

**Weaknesses**:  
- **Low Win Rate**: 48.6% (barely above breakeven).  
- **Inconsistent Performance**: Median wins/day = 0; 0 days hit targets.  
- **Infrequent Trades**: Only 1 trade/day on average.  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Focus on **London session (07:00–12:00 UTC)** where USDJPY volatility peaks.  
- **Entry Filter**: Add a **volatility filter** (e.g., ATR > 0.5%) to avoid low-momentum trades.  
- **Position Sizing**: Reduce risk per trade to **1.5% of capital** (current losses often exceed $10).  
- **Exit Rules**: Tighten take-profit to **1.5x average win size** (~$30) to lock in profits.  

## 4. Risk Assessment  
- **Low Per-Trade Risk**: Max daily DD <1%, but frequent small losses erode returns.  
- **Liquidity Risk**: USDJPY is highly liquid, minimizing slippage concerns.  
- **Survivability**: Max DD (4.2%) is acceptable for a daily strategy, but requires improved win consistency.  

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize session filtering and volatility adjustments before retesting. Avoid deployment until targets are met.  

SUMMARY: Marginal strategy with controlled risk but poor target achievement; optimize session timing and volatility filters before redeploying.