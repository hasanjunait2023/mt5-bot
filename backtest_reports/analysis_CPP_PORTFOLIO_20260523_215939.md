# Backtest Analysis: CPP_PORTFOLIO (5 Symbols) — Daily  

## 1. Overall Verdict  
**Unprofitable**  
- Return: **-39.6%**  
- Profit Factor: **0.79** (losses > wins)  
- Max Drawdown: **65.3%** (extreme risk)  
- Days hitting target: **0/148 (0.0%)**  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- Occasional high-win days (e.g., +269.33 on 2026-02-05).  
- Some days with 100% win rate (e.g., 2025-11-21, +19.07).  

**Weaknesses**:  
- **Low win rate (40%)** and **negative skew** (avg losses/day > wins/day).  
- **Severe drawdowns**: 5 days with >6% DD, including a **34.03% single-day loss** (2026-02-02).  
- **Profit factor <1** and **median wins/day = 0**, indicating consistent underperformance.  

---

## 3. Specific Parameter Recommendations  
- **Restrict trading session**: Limit to **London session (07:00–12:00 UTC)** to avoid volatile/non-liquid periods.  
- **Reduce position size**: Cap risk per trade to **1–2% of capital** to mitigate large DDs.  
- **Filter symbols**: Remove **underperforming assets** (e.g., those contributing to 2026-02-02 and 2026-03-19 losses).  
- **Tighten stop-loss**: Enforce **max daily DD limit of 3%** to prevent catastrophic losses.  

---

## 4. Risk Assessment  
- **Extreme drawdown risk**: 65.3% Max DD and multiple days with >10% losses.  
- **Liquidity risk**: Large losses on low-volume days (e.g., 2026-02-02: -$368.51).  
- **Strategy instability**: High variance in daily P&L (winning days rarely offset losses).  

---

## 5. Recommended Next Action  
**Disable for live trading / Optimize further**  
- Prioritize fixing risk management (stop-loss, position sizing).  
- Re-test with filtered symbols and restricted sessions.  
- Avoid deployment until win rate >50% and profit factor >1.2.  

---

SUMMARY: Unprofitable strategy with extreme drawdowns (65.3% Max DD) and 0% target achievement; disable live use and optimize risk parameters before retesting.