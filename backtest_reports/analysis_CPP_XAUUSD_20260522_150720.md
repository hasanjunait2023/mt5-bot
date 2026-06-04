# Backtest Analysis: CPP — XAUUSD — Daily  

## 1. Overall Verdict  
**Unprofitable**  
Negative return (-10.5%), profit factor <1 (0.76), and max drawdown (25.6%) exceed acceptable risk thresholds.  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Occasional large winning trades (e.g., +$112.54 on 2026-02-05, +$84.11 on 2026-03-26).  
- Low median daily trades (1.0), suggesting selective entry criteria.  

**Weaknesses**:  
- **Low win rate (38.1%)** and **profit factor <1**, indicating consistent losing streaks.  
- **High drawdown** (25.6% max, 11.88% single-day DD on 2026-02-02).  
- **Zero days hit performance targets** (0/42), signaling systemic issues.  
- Frequent large losses (e.g., -$101.27 on 2026-02-02, -$45.22 on 2025-10-22).  

## 3. Specific Parameter Recommendations  
- **Restrict trading to London session (07:00–12:00 UTC)** to focus on high-liquidity periods for XAUUSD.  
- **Tighten stop-loss** to limit single-trade losses (e.g., cap at 3% of equity per trade).  
- **Adjust entry filters** to improve win rate (e.g., require stronger momentum confirmation).  
- **Reduce position size** during low-liquidity periods (e.g., outside major sessions).  

## 4. Risk Assessment  
- **High risk**: Max DD (25.6%) and single-day DD (11.88%) far exceed the 6% target.  
- **Liquidity risk**: Large losses (e.g., -$101.27) suggest potential slippage or illiquid market conditions.  
- **Strategy instability**: p90 daily DD (2.98%) indicates frequent moderate drawdowns.  

## 5. Recommended Next Action  
**Optimize further** with focus on:  
1. Improving risk management (smaller position sizes, tighter stops).  
2. Enhancing entry criteria to boost win rate.  
3. Testing session-specific constraints.  
**Disable** if optimization fails to improve risk-return profile.  

SUMMARY: Unprofitable strategy with high drawdowns and low win rate; optimize risk management and entry filters before redeploying.