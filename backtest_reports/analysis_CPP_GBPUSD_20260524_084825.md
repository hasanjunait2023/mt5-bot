```markdown
# Backtest Analysis: CPP — GBPUSD — Daily

## 1. Overall Verdict  
**Marginal**  
Positive return (+3.7%) and profit factor (1.23) but fails to meet performance targets (0/29 days) and exhibits low trade frequency.

## 2. Key Strengths and Weaknesses  
**Strengths:**  
- Max DD (5.7%) stays under 6% threshold.  
- Profit factor >1 indicates edge in trade exits.  
- Low daily DD (p90: 0.95%) suggests controlled risk per trade.  

**Weaknesses:**  
- Extremely low win rate (40.6%) and median wins/day = 0.  
- Only 32 trades over 29 days (avg 1.1/day) — insufficient activity.  
- Frequent losing days (15/29 days with losses) and large single-day losses (e.g., -$20.03 on 2025-12-17).  

## 3. Specific Parameter Recommendations  
- **Session Filter:** Restrict to London session (07:00–12:00 UTC) to target higher GBPUSD volatility.  
- **Trade Frequency:** Adjust entry criteria to increase trades/day (e.g., reduce filter strictness).  
- **Loss Mitigation:** Cap daily losses at 0.8% DD by reducing position size or adding stop-loss rules.  
- **Trend Filter:** Add a 20-period EMA filter to avoid counter-trend trades.  

## 4. Risk Assessment  
- **Acceptable Risk of Ruin:** Max DD (5.7%) is within limits but could escalate with higher leverage.  
- **Liquidity Risk:** Low trade frequency may lead to slippage in less volatile periods.  
- **Overfitting Risk:** Strategy may not generalize to live markets due to sparse trade data.  

## 5. Recommended Next Action  
**Optimize Further**  
Focus on improving win rate and trade frequency via session/time filters and entry rule tweaks. Re-test before deployment.

SUMMARY: Marginal strategy with low trade frequency and win rate; optimize session timing and entry rules before deployment.
```