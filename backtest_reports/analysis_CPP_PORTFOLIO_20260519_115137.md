# Backtest Analysis Report: CPP PORTFOLIO  

## 1. Overall Verdict  
**Unprofitable**  
The strategy generated a **-39.6% return** with a **profit factor of 0.79** and **max drawdown of 65.3%**, indicating consistent losses and poor risk-adjusted performance.  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- Occasional high-win days (e.g., +269.33 on 2026-02-05).  
- Some days with 100% win rate (e.g., 2025-11-21, 2026-03-17).  

**Weaknesses**:  
- **Low win rate (40%)** with **median wins/day = 0**, suggesting frequent losing streaks.  
- **Severe drawdowns**: 5 days with >6% daily DD, including a **34.03% single-day loss** (2026-02-02).  
- **No days hit performance target** (0/148 days), indicating systemic issues.  
- **Lopsided losses**: Avg. losses/day (0.8) > wins/day (0.5), with many large individual losses (e.g., -$45.22, -$50.20).  

---

## 3. Specific Parameter Recommendations  
- **Restrict trading hours**: Focus on **London session (07:00-12:00 UTC)** to avoid volatile/non-liquid periods.  
- **Reduce position size**: Cap risk per trade to **1-2% of equity** to mitigate large DD events.  
- **Tighten stop-loss**: Enforce **max daily DD limit of 3%** to prevent catastrophic losses.  
- **Filter signals**: Exclude trades during low-liquidity periods (e.g., holidays, thin markets).  

---

## 4. Risk Assessment  
**High Risk**  
- **Drawdown severity**: Max DD (65.3%) and frequent large losses exceed acceptable thresholds for most portfolios.  
- **Liquidity risk**: Large losses on specific dates (e.g., 2026-02-02: -$368.51) suggest potential slippage or illiquid symbols.  
- **Consistency**: 0 days meeting performance targets and negative skew in returns indicate unreliable performance.  

---

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize:  
1. Backtest with adjusted risk parameters (position sizing, stop-loss).  
2. Analyze symbol-specific performance to identify underperforming assets.  
3. Test session/time-based filters to isolate profitable periods.  

---

SUMMARY: Unprofitable strategy with severe drawdowns and consistent losses; optimize risk parameters and session timing before reconsidering deployment.