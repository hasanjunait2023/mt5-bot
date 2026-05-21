# Backtest Analysis: CPP Strategy on GBPUSD  

## 1. Overall Verdict  
**Marginal**  
The strategy shows a small positive return (+3.7%) with acceptable drawdowns (Max DD: 5.7%, p90 Daily DD: 0.95%) but suffers from extreme inconsistency and a low win rate (40.6%).  

---

## 2. Key Strengths and Weaknesses  

**Strengths:**  
- **Profit Factor:** 1.23 indicates positive expectancy per trade.  
- **Risk Control:** No days exceeded the 6% daily DD limit; max daily DD was 1.82%.  
- **Modest Returns:** Achieved +3.7% over the period despite low activity.  

**Weaknesses:**  
- **Low Win Rate:** Only 40.6% of trades were profitable, with a median of 0 wins per day.  
- **Inconsistent Performance:** 0/29 days hit the performance target (>=15W / <=6L / <=6% DD).  
- **Low Trade Frequency:** Average 1.1 trades/day, limiting compounding potential.  
- **Clustering of Losses:** Multiple consecutive losing days (e.g., 2025-12-17: -1.82% DD).  

---

## 3. Specific Parameter Recommendations  
- **Session Restriction:** Restrict trading to the **London session (07:00–12:00 UTC)** to focus on high-liquidity periods for GBPUSD.  
- **Entry Filter:** Add a **volatility filter** (e.g., avoid trading if ATR < X) to reduce low-probability setups.  
- **Position Sizing:** Increase position size by 20% on trades with **higher R/R ratios** (e.g., >1:2) to capitalize on winning trades.  
- **Exit Rules:** Tighten stop-loss to **1.5x average daily range** to reduce daily DD spikes.  

---

## 4. Risk Assessment  
- **Drawdown Risk:** Moderate. Max DD (5.7%) is within acceptable limits, but the strategy lacks resilience during clustered losses.  
- **Survivability Risk:** High due to low win rate and infrequent trades. A few consecutive losses could erode capital quickly.  
- **Market Risk:** GBPUSD is sensitive to macro news; strategy lacks news filters, increasing unexpected DD risk.  

---

## 5. Recommended Next Action  
**Optimize Further**  
Focus on improving win rate and consistency via:  
1. Backtesting with tighter entry/exit rules.  
2. Adding session/time-based filters.  
3. Validating performance on out-of-sample data.  

Avoid deployment until metrics like win rate (>50%) and days hitting targets (>20%) improve.  

---

**SUMMARY:** Marginal strategy with +3.7% return but low win rate (40.6%) and inconsistent performance; optimize session timing and entry rules before deployment.