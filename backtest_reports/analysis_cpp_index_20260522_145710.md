# Backtest Analysis Report

## 1. Overall Verdict  
**Unprofitable**  
The portfolio shows significant losses in major components (XAUUSD: -10.5%, XAGUSD: -48.6%) with a profit factor (PF) of 0.76 (<1.0), indicating systematic losing tendencies. Only USDJPY shows strong performance (+13.3%, PF 1.84), but cannot offset overall losses.

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- **USDJPY**: High win rate (48.6%), strong PF (1.84), and +13.3% return with minimal max daily drawdown (0.97%).  
- **EURUSD/GBPUSD**: Small positive returns (+2.6%/+3.7%) with low risk (max DD <2%).  

**Weaknesses**:  
- **XAGUSD**: Catastrophic loss (-48.6%) with poor win rate (37.5%) and high volatility (27.44% max DD).  
- **XAUUSD**: Consistent losses (-10.5%) despite moderate trading frequency.  
- **Portfolio Hit Rate**: 0% (no days met profit targets), suggesting flawed target-setting or execution.  

---

## 3. Specific Parameter Recommendations  
- **Exclude XAUUSD and XAGUSD** from the portfolio immediately due to unsustainable losses.  
- **Restrict trading to USDJPY and GBPUSD/EURUSD** (best risk-return profiles).  
- **Adjust session timing**: Focus on Tokyo/London overlap (22:00-07:00 UTC) for USDJPY, where volatility and momentum are strongest.  
- **Reduce position sizing** for XAGUSD if retained (max 0.5% risk per trade vs. current 27.44% DD).  

---

## 4. Risk Assessment  
- **High Portfolio Risk**: Driven by XAGUSD/XAUUSD losses and 0% hit rate.  
- **Liquidity Risk**: Poor performance in gold pairs suggests potential slippage or market impact issues.  
- **Model Risk**: Targets (>=15W / <=6L / <=6.0%DD) are unmet, indicating flawed strategy logic or parameters.  

---

## 5. Recommended Next Action  
**Optimize Further**  
- Run sensitivity analysis on USDJPY/GBPUSD/EURUSD with tighter stop-losses (e.g., 1.5x ATR) and session filters.  
- Re-evaluate XAUUSD/XAGUSD entry/exit rules or abandon them entirely.  
- Recalibrate profit targets to align with historical volatility (e.g., 1.5x average daily range).  

---

SUMMARY: Unprofitable portfolio due to catastrophic losses in XAGUSD/XAUUSD; retain USDJPY/GBPUSD/EURUSD with session filters and tighter risk parameters for further optimization.