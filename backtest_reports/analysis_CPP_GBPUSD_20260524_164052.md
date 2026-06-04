# Backtest Analysis: CPP Strategy on GBPUSD  

## 1. Overall Verdict  
**Marginal**  
The strategy shows slight profitability (3.7% return, profit factor 1.23) but fails to meet its performance targets (0/29 days hitting goals) and has a low win rate (40.6%).  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- Controlled daily drawdown (p90: 0.95%, max: 1.82%).  
- Profit factor above 1 (1.23) indicates positive expectancy per trade.  
- Occasional high-profit days (e.g., +$37.75 on 2025-01-24).  

**Weaknesses**:  
- Extremely low win rate (40.6%) and median wins/day of 0.  
- No days met the performance target (>=15W / <=6L / <=6.0%DD).  
- Clustering of losing trades (e.g., 5 consecutive losses in May 2026).  
- Low return relative to max DD (3.7% vs. 5.7%).  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trading to **London session (07:00–12:00 UTC)** to focus on high-liquidity periods for GBPUSD.  
- **Entry Filter**: Add a **trend filter** (e.g., 200-period EMA) to avoid counter-trend trades.  
- **Risk Management**: Reduce position size by **20–30%** during low-liquidity hours (e.g., Asian session).  
- **Exit Rules**: Tighten stop-loss to **1.5x average true range** to reduce loss magnitude.  

## 4. Risk Assessment  
- **Max DD (5.7%)**: Moderate but acceptable for FX trading.  
- **Daily DD**: Well-controlled (90% of days <1%), but tail risk exists (1.82% peak).  
- **Liquidity Risk**: Potential issues during low-volume periods (e.g., weekends, holidays).  
- **Compounding Risk**: Low win rate and sporadic profits may lead to underperformance over time.  

## 5. Recommended Next Action  
**Optimize Further**  
Prioritize session-based filtering and exit rule adjustments. Re-backtest with revised parameters before considering deployment.  

SUMMARY: Marginal strategy with controlled risk but poor target achievement; optimize session timing and exit rules before deployment.