# Backtest Analysis: CPP — XAGUSD — Daily  

## 1. Overall Verdict  
**Unprofitable**  
The strategy generated a **-48.6% return** with a **profit factor of 0.50** and **max drawdown of 56.7%**, failing to meet performance targets (0/39 days hit targets).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Occasional high-win days (e.g., +$30.71, +$24.31).  
- Low average trades/day (1.0), suggesting selective entry.  

**Weaknesses**:  
- **Low win rate (37.5%)** and **negative expectancy**.  
- **Severe drawdowns**: 6 days with >6% daily DD, including a **27.44% single-day loss**.  
- **Profit factor <1** indicates losing strategy overall.  
- **Median wins/day = 0**, showing inconsistency.  

## 3. Specific Parameter Recommendations  
- **Restrict trading to Asian session (22:00–04:00 UTC)** to avoid volatile London/NY overlaps.  
- **Cap maximum position size** to reduce single-trade risk (e.g., limit risk per trade to 2% of equity).  
- **Tighten stop-loss** to prevent large losses (e.g., max 3% DD per trade).  
- **Filter trades** using volatility filters (e.g., avoid entries during high ATR periods).  

## 4. Risk Assessment  
- **Extreme risk**: Max DD (56.7%) and p90 daily DD (8.5%) exceed acceptable thresholds.  
- **Liquidity risk**: Large losses (e.g., -$267.24 on 2026-02-02) suggest potential slippage or poor execution.  
- **Compounding risk**: Negative return and high DD make capital preservation challenging.  

## 5. Recommended Next Action  
**Optimize further** with focus on:  
1. Reducing drawdowns via tighter risk management.  
2. Improving win rate with enhanced entry/exit logic.  
3. Validating robustness across multiple market conditions.  

**SUMMARY:** Unprofitable strategy with extreme DD; optimize risk parameters and entry filters before retesting.