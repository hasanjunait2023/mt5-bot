```markdown
# Backtest Analysis: CPP — XAUUSD — Daily

## 1. Overall Verdict  
**Unprofitable**  
Negative return (-10.5%), profit factor <1 (0.76), and high drawdown (25.6%) indicate systematic losses.

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Occasional large winning trades (e.g., +112.54 on 2026-02-05).  
- No correlation between trade frequency and losses (1 trade/day on average).  

**Weaknesses**:  
- Extremely low win rate (38.1%) and median wins/day = 0.  
- Severe drawdowns (11.88% single-day loss, 25.6% max DD).  
- Profit factor <1 and negative return confirm losing strategy.  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Restrict to London session (07:00–12:00 UTC) to focus on high-liquidity gold trading hours.  
- **Loss Limits**: Cap daily losses at 3% to avoid catastrophic draws (e.g., 11.88% loss on 2026-02-02).  
- **Volatility Filter**: Exclude days with scheduled major macroeconomic news (e.g., FOMC meetings, CPI data).  
- **Position Sizing**: Reduce lot size by 50% on days following a 5%+ drawdown.  

## 4. Risk Assessment  
- **High Risk**: Max DD (25.6%) exceeds typical risk thresholds for daily strategies.  
- **Tail Risk**: 1 day with >10% loss (2026-02-02) and 4 days with >4% DD.  
- **Liquidity Risk**: Large losses on low-volume dates (e.g., 2026-02-02, 2025-10-22).  

## 5. Recommended Next Action  
**Optimize Further**  
Focus on:  
1. Improving win rate via tighter entry filters (e.g., momentum confirmation).  
2. Reducing stop-loss sizes to limit single-trade losses.  
3. Backtesting session/time restrictions and volatility filters.  

If optimization fails to yield a profit factor >1.2 and DD <15%, **disable** the strategy.

SUMMARY: Unprofitable strategy with high drawdowns; optimize session timing, loss limits, and filters before redeploying.
```