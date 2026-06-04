# Backtest Analysis: CPP PORTFOLIO (5 symbols) — Daily  

## 1. Overall Verdict  
**Unprofitable**  
The strategy generated a **-39.6% return** with a **profit factor of 0.79** and **65.3% max drawdown**, indicating consistent losses and extreme risk exposure.  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- Occasional high-profit days (e.g., **+$269.33** on 2026-02-05).  
- Some days with 100% win rate (e.g., 2025-11-21, 2026-03-17).  

**Weaknesses**:  
- **40% win rate** with **median wins/day = 0**, showing frequent losing streaks.  
- **Severe drawdowns**: 5 days with >6% daily DD, including a **34.03% single-day loss** (2026-02-02).  
- **Zero days** hit the performance target (>=15W / <=6L / <=6.0%DD).  

---

## 3. Specific Parameter Recommendations  
- **Restrict trading to London session (07:00–12:00 UTC)** to focus on high-liquidity periods.  
- **Reduce position size by 50%** during low-liquidity hours (e.g., Asian session).  
- **Filter out underperforming symbols**: Analyze per-symbol performance to remove losers.  
- **Tighten stop-loss levels** to limit single-trade risk (e.g., cap losses at 2% per trade).  

---

## 4. Risk Assessment  
- **Extreme drawdown risk**: Max DD (65.3%) and tail-risk days (e.g., **-34.03%**, **-15.16%**) suggest poor risk management.  
- **Unsustainable loss clusters**: Multiple days with 2–3 consecutive losses (e.g., 2026-02-02, 2026-03-19).  
- **Leverage risk**: Large losses imply potential over-leveraging or poor execution.  

---

## 5. Recommended Next Action  
**Optimize further** with focus on:  
1. Adjusting risk parameters (position sizing, stop-loss).  
2. Symbol filtering and session restrictions.  
3. Re-testing with improved rules before considering deployment.  

**SUMMARY:** Unprofitable strategy with extreme drawdowns; optimize risk parameters and filter symbols before re-testing.