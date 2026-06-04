# Backtest Analysis: CPP_PORTFOLIO (5 Symbols) — Daily  

## 1. Overall Verdict  
**Unprofitable**  
- **Return**: -39.6%  
- **Profit Factor**: 0.79 (<1.0 indicates losses)  
- **Max Drawdown**: 65.3% (extremely high)  
- **Win Rate**: 40.0% (poor)  
- **Target Performance**: 0/148 days met targets  

---

## 2. Key Strengths and Weaknesses  

**Strengths**:  
- Occasional high-reward days (e.g., +269.33 on 2026-02-05, +41.86 on 2025-01-24).  
- Some days with 100% win rate (e.g., 2025-11-21, 2026-03-17).  

**Weaknesses**:  
- **Low Win Rate**: 40% with median wins/day = 0 (most days have no winning trades).  
- **Severe Drawdowns**: 5 days with >6% daily DD, including a 34.03% single-day loss.  
- **Profit Factor <1**: Losses outweigh gains (total P&L negative despite sporadic wins).  
- **Inconsistent Performance**: Frequent losing streaks (e.g., 3 consecutive losses on 2026-02-02).  

---

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Limit trading to **London session (07:00-12:00 UTC)** where liquidity/volatility may improve edge.  
- **Entry Filter**: Require **minimum 2:1 risk-reward ratio** for trade entries to avoid low-probability setups.  
- **Position Sizing**: Reduce position size by **50%** during low-liquidity periods (e.g., Asian session).  
- **Stop-Loss Tightening**: Cap stop-loss at **1.5x average true range (ATR)** to limit single-trade losses.  
- **Daily Loss Limit**: Halt trading after **3 consecutive losses** or **5% daily DD** to prevent compounding losses.  

---

## 4. Risk Assessment  
- **Extreme Drawdown Risk**: 65.3% max DD and 34.03% single-day loss suggest poor risk management.  
- **Liquidity Risk**: Large losses on low-volume days (e.g., 2026-02-02: -$368.51).  
- **Survivability Concern**: A 65% drawdown would require a **+65% return** to breakeven, which is unrealistic for this strategy.  

---

## 5. Recommended Next Action  
**Optimize Further**  
- Test session-specific restrictions (e.g., London-only) and tighter risk controls.  
- Re-evaluate entry/exit logic to improve win rate (>50%) and profit factor (>1.2).  
- If optimization fails, **disable** the strategy due to unsustainable risk profile.  

---

SUMMARY: Unprofitable strategy with extreme drawdowns (65.3% max DD) and poor win rate (40%); optimize session timing, risk parameters, and entry filters before reconsidering deployment.