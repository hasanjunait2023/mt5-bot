# Backtest Analysis: CPP PORTFOLIO (5 Symbols) — Daily  

## 1. Overall Verdict  
**Unprofitable**  
- Return: **-39.6%**  
- Profit Factor: **0.79** (losses exceed gains)  
- Max Drawdown: **65.3%** (extreme risk)  
- Win Rate: **40.0%** (below breakeven after transaction costs)  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- Occasional high-profit days (e.g., **+$269.33** on 2026-02-05).  
- Some days with **100% win rate** (e.g., 2025-01-24: +$41.86).  

**Weaknesses**:  
- **Severe drawdowns**: 5 days with >6% daily DD, including **34.03%** on 2026-02-02.  
- **Consistent losses**: 0/148 days hit the performance target (>=15W / <=6L / <=6% DD).  
- **Low median wins/day**: 0 (most days have no winning trades).  
- **Negative skew**: Large losses (e.g., **-$368.51** on 2026-02-02) dominate gains.  

---

## 3. Specific Parameter Recommendations  
- **Restrict trading sessions**: Focus on **London session (07:00-12:00 UTC)** where volatility and liquidity may improve edge.  
- **Tighten stop-loss**: Cap daily loss limits at **3% of equity** to avoid catastrophic draws.  
- **Filter symbols**: Remove underperforming assets (analyze per-symbol performance to identify drags).  
- **Reduce position size**: Lower risk per trade (e.g., 1% of capital max) to mitigate large losses.  
- **Avoid news events**: Exclude major economic releases to reduce gap risk.  

---

## 4. Risk Assessment  
- **Extreme drawdown risk**: 65.3% max DD and multiple days with >10% losses indicate poor risk management.  
- **Liquidity risk**: Large losses (e.g., **-$45.22** on 2025-10-22) suggest potential slippage or illiquid markets.  
- **Model risk**: Strategy fails to adapt to changing market conditions (consistent underperformance across periods).  

---

## 5. Recommended Next Action  
**Optimize further**  
- Prioritize risk management tweaks (stop-loss, position sizing).  
- Test session-specific filters and symbol subsets.  
- Re-evaluate entry/exit logic to improve win rate.  
- **Do not deploy** until drawdowns are controlled and profit factor exceeds 1.2.  

---

SUMMARY: Unprofitable strategy with extreme drawdowns (65.3% max DD) and 40% win rate; optimize risk parameters and session filters before retesting.