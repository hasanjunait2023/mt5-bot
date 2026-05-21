# Backtest Analysis Report: CPP Strategy on USDJPY  

## 1. Overall Verdict  
**Marginal**  
Positive return (+13.3%) and controlled drawdown (max DD 4.2%) but extremely low consistency (0/34 days hitting performance target, median wins/day = 0).  

---

## 2. Key Strengths and Weaknesses  

**Strengths:**  
- **Profit Factor:** 1.84 (strong risk/reward ratio).  
- **Drawdown Control:** Max daily DD 0.97%, no days exceeding 6% DD.  
- **Winning Trade Size:** Average win ($18.45) > average loss ($9.39).  

**Weaknesses:**  
- **Low Win Rate:** 48.6% (barely above breakeven).  
- **Inconsistency:** Median wins/day = 0; 51% of days have no winning trades.  
- **Missed Targets:** 0/34 days met the performance target (undefined but critical metric).  

---

## 3. Specific Parameter Recommendations  
- **Session Restriction:** Test strategy during **London session (07:00–12:00 UTC)** to capitalize on higher USDJPY volatility.  
- **Entry Filter:** Add a **trend confirmation indicator** (e.g., 20-period EMA) to improve win rate.  
- **Position Sizing:** Reduce lot size by 30% to mitigate impact of losing streaks.  
- **Timeframe Adjustment:** Re-optimize parameters on **H4 charts** to reduce noise from daily data.  

---

## 4. Risk Assessment  
- **Drawdown Risk:** Low (max DD 4.2%, all daily DD <1%).  
- **Survivability Risk:** Moderate (inconsistent performance may lead to early stoppage).  
- **Market Risk:** USDJPY sensitivity to BoJ/Fed policies could impact future performance.  

---

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize improving win rate and consistency before deployment. Validate session-specific performance and retest with adjusted parameters.  

---

SUMMARY: Marginal strategy with strong risk/reward but poor consistency; optimize entry rules and session timing before deployment.