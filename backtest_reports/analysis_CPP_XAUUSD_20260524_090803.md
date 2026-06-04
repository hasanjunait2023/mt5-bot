# Backtest Analysis: CPP — XAUUSD — Daily  

## 1. Overall Verdict  
**Unprofitable**  
- Negative return (-10.5%) and profit factor (0.76) indicate consistent losses.  
- High drawdowns (25.6% max, 11.88% single-day) and poor win rate (38.1%).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Occasional large winning trades (e.g., +$112.54 on 2026-02-05).  
- Low median daily trades (1.0), suggesting selective entry.  

**Weaknesses**:  
- **Low win rate** (38.1%) and **negative expectancy** (profit factor <1).  
- **Severe drawdowns**: 1 day with >10% DD, 1 day with 4.75% DD.  
- **Inconsistent performance**: Only 12 winning days vs. 30 losing days.  

## 3. Specific Parameter Recommendations  
- **Restrict to London session (07:00–12:00 UTC)** to focus on high-liquidity gold trading hours.  
- **Tighten stop-loss to 50 pips** to mitigate large losses (e.g., -$101.27 on 2026-02-02).  
- **Increase take-profit ratio** (e.g., 2:1 risk-reward) to capitalize on winning trades.  
- **Filter entries during low volatility** (e.g., avoid Asian session).  

## 4. Risk Assessment  
- **High risk**: Max DD (25.6%) exceeds typical tolerance levels for daily strategies.  
- **Tail risk**: Single-day losses up to 11.88% and 4.75% suggest poor risk management.  
- **Reward-to-risk ratio**: Negative overall, with losses outweighing gains.  

## 5. Recommended Next Action  
**Optimize further** with session filtering, tighter risk management, and improved entry/exit logic. If optimizations fail to yield a profit factor >1.2 and DD <15%, **disable the strategy**.  

SUMMARY: Unprofitable strategy with high drawdowns; optimize session timing, risk parameters, and reward ratios before retesting.