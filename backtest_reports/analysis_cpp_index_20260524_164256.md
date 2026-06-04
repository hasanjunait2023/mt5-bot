# Backtest Analysis Report

## 1. Overall Verdict  
**Unprofitable**  
While USDJPY and GBPUSD show positive returns, the portfolio's overall performance is dragged down by significant losses in XAUUSD (-10.5%) and XAGUSD (-48.6%). The 0% target hit rate indicates failure to meet key performance thresholds (>=15W return, <=6L loss, <=6% drawdown).

---

## 2. Key Strengths and Weaknesses  
**Strengths:**  
- **USDJPY**: High win rate (48.6%), strong profit factor (1.84), and +13.3% return.  
- **GBPUSD**: Positive return (+3.7%) with acceptable risk metrics.  
- **EURUSD**: Modest profit (+2.6%) despite low win rate.  

**Weaknesses:**  
- **XAGUSD**: Severe loss (-48.6%) with high max drawdown (27.44%).  
- **XAUUSD**: Consistent underperformance (-10.5%) across both runs.  
- **Portfolio Hit Rate**: 0% in both runs, failing all target metrics.  

---

## 3. Specific Parameter Recommendations  
- **Exclude XAUUSD and XAGUSD** from the portfolio due to consistent losses.  
- **Restrict trading to London session (07:00–12:00 UTC)** for EURUSD/GBPUSD to capitalize on volatility.  
- **Adjust stop-loss/take-profit ratios** for USDJPY (current 0.5/0.5 appears optimal; test tighter levels).  
- **Filter trades during low-liquidity periods** (e.g., post-New York close) to reduce XAGUSD/XAUUSD losses.  

---

## 4. Risk Assessment  
- **High Drawdown Risk**: XAGUSD alone contributes 27.44% max drawdown, exceeding the 6% target.  
- **Concentration Risk**: Overexposure to underperforming precious metals (XAU/XAG).  
- **Liquidity Risk**: Poor performance in XAG/XAU suggests potential slippage or market impact issues.  

---

## 5. Recommended Next Action  
**Optimize Further**  
- Run sensitivity analysis on session timing and asset allocation.  
- Test strategy on EURUSD/GBPUSD/USDJPY only (exclude XAU/XAG).  
- Validate if target metrics (>=15W return) are realistic for the remaining pairs.  

---

SUMMARY: Portfolio unprofitable due to XAU/XAG losses; optimize by excluding weak pairs, restricting sessions, and retesting before deployment.