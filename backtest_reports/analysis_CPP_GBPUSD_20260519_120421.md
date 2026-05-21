# Backtest Analysis: CPP Strategy on GBPUSD  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a small positive return (+3.7%) with a profit factor of 1.23, but its low win rate (40.6%), inconsistent performance (median wins/day = 0), and failure to meet daily performance targets (0/29 days) indicate marginal reliability.  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- **Controlled daily risk**: Max daily drawdown (1.82%) and p90 daily DD (0.95%) are well below the 6% threshold.  
- **Positive edge**: Profit factor >1 suggests a slight edge in winning trades over losses.  

**Weaknesses**:  
- **Low win rate**: 40.6% win rate with a median of 0 winning days indicates inconsistency.  
- **Ineffective target achievement**: 0 days met the performance target (>=15W / <=6L / <=6.0%DD).  
- **Low trade frequency**: Only 1.1 trades/day, reducing statistical significance and compounding potential.  

---

## 3. Specific Parameter Recommendations  
- **Session restriction**: Focus on high-liquidity periods (e.g., **London session 07:00-12:00 UTC**) to improve trade quality.  
- **Entry filter**: Add volatility filters (e.g., avoid trading during low ATR periods) to reduce false signals.  
- **Position sizing**: Reduce lot size by 20-30% to mitigate impact of consecutive losses (e.g., 2025-12-17: -$20.03 loss).  
- **Exit rules**: Tighten take-profit/stop-loss levels to improve win rate (current median win/day = 0 suggests over-holding).  

---

## 4. Risk Assessment  
- **Max DD (5.7%)**: Moderate but concerning given the low absolute return (+3.7%).  
- **Risk-reward ratio**: Poor (return ≈ 3.7% vs. max DD ≈ 5.7%).  
- **Tail risk**: Cluster of losses in May 2026 (-$10.06 to -$10.27) highlights vulnerability to adverse moves.  

---

## 5. Recommended Next Action  
**Optimize further**  
Prioritize parameter tweaks (session filtering, volatility adjustments) and retest. If improvements are not seen in 2-3 iterations, consider disabling.  

---

SUMMARY: Marginal profitability with controlled daily risk but low win rate and inconsistent performance; optimize session timing and exit rules before deployment.