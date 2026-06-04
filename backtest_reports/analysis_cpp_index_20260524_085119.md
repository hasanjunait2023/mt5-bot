# Backtest Analysis Report

## 1. Overall Verdict  
**Unprofitable**  
The portfolio fails to meet its target return (>=15W) with 0% hit rate, and three out of five pairs show negative returns. Only USDJPY and GBPUSD are marginally profitable.

---

## 2. Key Strengths and Weaknesses  

**Strengths:**  
- **USDJPY**: Highest win rate (48.6%), strong profit factor (1.84), and +13.3% return.  
- **GBPUSD**: Positive return (+3.7%) with low max day drawdown (1.82%).  
- **EURUSD**: Slight profit (+2.6%) despite low win rate.  

**Weaknesses:**  
- **XAGUSD**: Severe loss (-48.6%) with extreme max drawdown (27.44%).  
- **XAUUSD**: Consistent underperformance (-10.5%) across both runs.  
- **Portfolio Hit Rate**: 0% in both runs, indicating systemic failure to meet targets.  
- **Risk Violations**: XAGUSD exceeds max drawdown limit (6.0% target vs. 27.44% actual).  

---

## 3. Specific Parameter Recommendations  
- **Exclude XAGUSD and XAUUSD** from the portfolio due to consistent losses and excessive risk.  
- **Restrict trading to London session (07:00–12:00 UTC)** for EURUSD and GBPUSD to align with higher liquidity.  
- **Cap position size** for USDJPY at 1.5x standard lots to mitigate volatility.  
- **Adjust stop-loss** for all pairs to 2.0% of account per trade to enforce risk discipline.  

---

## 4. Risk Assessment  
**High Risk**:  
- XAGUSD and XAUUSD exhibit catastrophic drawdowns, violating the 6.0% max DD target.  
- Portfolio hit rate of 0% suggests structural flaws in strategy logic or market adaptation.  
- Surviving pairs (GBPUSD, USDJPY) show low but acceptable risk profiles.  

---

## 5. Recommended Next Action  
**Optimize Further**  
- Run sensitivity analysis on entry/exit logic for XAGUSD/XAUUSD to identify failure points.  
- Test filtered portfolio (only EUR/GBP/JPY pairs) with adjusted risk parameters.  
- Validate session-based restrictions (e.g., London-only) for remaining pairs.  

---

SUMMARY: Unprofitable overall due to XAG/XAU losses; retain USDJPY/GBPUSD, optimize parameters, and retest filtered portfolio.