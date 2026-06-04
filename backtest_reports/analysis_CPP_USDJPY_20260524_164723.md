# Backtest Analysis: CPP Strategy on USDJPY  

## 1. Overall Verdict  
**Marginal**  
While the strategy shows a positive return (+13.3%) and controlled drawdowns (max DD 4.2%), it fails to meet the performance target (0/34 days) and exhibits low trade frequency (1 trade/day) and a sub-50% win rate.  

## 2. Key Strengths and Weaknesses  
**Strengths**:  
- **Profit Factor**: 1.84 (indicating strong risk/reward ratio).  
- **Low Drawdowns**: Max daily DD (0.97%) and overall DD (4.2%) are well within acceptable limits.  
- **Consistent Win Size**: Winning trades show relatively stable gains (e.g., $18–$22 range).  

**Weaknesses**:  
- **Low Win Rate**: 48.6% win rate with median daily wins = 0.  
- **Inconsistent Performance**: 0 days met the target (>=15W / <=6L / <=6.0%DD).  
- **Low Trade Frequency**: Only 35 trades over the period (~1 trade/day).  

## 3. Specific Parameter Recommendations  
- **Session Restriction**: Focus on **London session (07:00–12:00 UTC)** to capitalize on higher USDJPY volatility.  
- **Entry Filters**: Adjust entry criteria to prioritize trends during **Tokyo-London overlap (03:00–07:00 UTC)**.  
- **Stop-Loss/Take-Profit**: Increase take-profit to **25–30 pips** to capture larger moves (current wins average ~20 pips).  
- **Trade Frequency**: Relax filters to allow **2–3 trades/day** while maintaining risk constraints.  

## 4. Risk Assessment  
- **Per-Trade Risk**: Low (avg loss ~$9–$11, aligned with DD metrics).  
- **Drawdown Risk**: Minimal (max DD 4.2%, p90 daily DD 0.96%).  
- **Liquidity Risk**: USDJPY is a major pair; execution should not be an issue.  
- **Overfitting Risk**: Low trade count (35 trades) raises concerns about statistical significance.  

## 5. Recommended Next Action  
**Optimize Further**  
Refine entry/exit rules to increase trade frequency and win rate while preserving risk metrics. Test adjustments in walk-forward analysis before deployment.  

SUMMARY: Marginal strategy with strong risk/reward but low frequency and inconsistent performance; optimize entry rules and session focus before deployment.