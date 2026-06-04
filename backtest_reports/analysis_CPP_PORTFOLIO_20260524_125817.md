# Backtest Analysis: CPP PORTFOLIO (5 Symbols) — Daily  

## 1. Overall Verdict  
**Unprofitable**  
The strategy generated a **-39.6% return** with a **max drawdown of 65.3%**, a **profit factor of 0.79**, and only **40% win rate**, failing to meet basic profitability thresholds.  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- Occasional high-profit days (e.g., +$269.33 on 2026-02-05).  
- Some winning days cluster in specific periods (e.g., Nov–Dec 2025).  

**Weaknesses**:  
- **Severe drawdowns**: 5 days with >6% daily DD, including a **34.03% single-day loss** (2026-02-02).  
- **Consistent losses**: 0/148 days hit the performance target; **median wins/day = 0**.  
- **Negative expectancy**: Profit factor <1 and return deeply negative.  
- **Inconsistent activity**: Only 1.2 trades/day on average.  

---

## 3. Specific Parameter Recommendations  
- **Restrict trading hours**: Focus on sessions with higher win rates (e.g., **London session 07:00–12:00 UTC** if historical data shows better performance).  
- **Cap position size**: Reduce risk per trade to limit daily DD (e.g., **max 2% capital per trade**).  
- **Filter trade signals**: Add volatility filters (e.g., avoid trading during low-liquidity periods or extreme news events).  
- **Adjust stop-loss/take-profit**: Tighten risk parameters to prevent catastrophic losses (e.g., **max 3% DD per trade**).  

---

## 4. Risk Assessment  
- **Extreme drawdown risk**: Max DD (65.3%) and frequent large losses (>10% daily DD on multiple occasions) make this strategy highly risky.  
- **Low reliability**: Failure to hit performance targets on any day suggests systemic flaws in the strategy logic.  
- **Liquidity risk**: Large losses on low-volume days (e.g., 2026-02-02) indicate potential execution issues.  

---

## 5. Recommended Next Action  
**Disable for live trading; optimize further in simulation**  
Prioritize:  
1. Root-cause analysis of high-loss days (e.g., market context, trade execution).  
2. Re-optimize entry/exit rules to improve win rate and reduce drawdowns.  
3. Stress-test with tighter risk parameters before re-evaluating deployment.  

---

**SUMMARY:** Unprofitable strategy with extreme drawdowns and consistent losses; disable live use and re-optimize with tighter risk controls and session restrictions.