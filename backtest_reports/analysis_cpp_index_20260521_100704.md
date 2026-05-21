# Backtest Analysis Report

## 1. Overall Verdict  
**Unprofitable**  
The portfolio fails to meet its target (0% hit rate) with an overall negative return (-10.5% to -48.6% on XAU/XAG pairs) and excessive drawdowns.

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Strong performance on **EURUSD (+2.6%)**, **GBPUSD (+3.7%)**, and **USDJPY (+13.3%)** with profit factors >1.0.  
- Low daily drawdowns on majors (≤1.82%).  

**Weaknesses**:  
- **XAUUSD (-10.5%)** and **XAGUSD (-48.6%)** are highly unprofitable with profit factors <0.76.  
- Extreme drawdowns on XAG (27.44%) and XAU (11.88%).  
- Zero target hits across all pairs.  

## 3. Specific Parameter Recommendations  
- **Exclude XAUUSD and XAGUSD** from the portfolio due to consistent losses.  
- **Restrict trading to London session (07:00–12:00 UTC)** for EURUSD/GBPUSD to capitalize on volatility.  
- **Adjust risk per trade** for USDJPY to 0.5% max to mitigate its 0.97% daily drawdown.  
- **Tighten stop-loss** on XAU/XAG to 2.0% to reduce catastrophic losses.  

## 4. Risk Assessment  
**High Risk**:  
- Portfolio exhibits severe drawdowns (XAG: 27.44%) and consistent losses on half the pairs.  
- Negative skewness in returns increases capital erosion risk.  

## 5. Recommended Next Action  
**Optimize Further**  
Focus on refining parameters for EURUSD/GBPUSD/USDJPY, while stress-testing XAU/XAG with tighter risk controls before re-inclusion.  

SUMMARY: Unprofitable overall due to XAU/XAG losses; retain EUR/GBP/JPY with session/time restrictions and tighter risk limits.