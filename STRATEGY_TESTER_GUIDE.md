# MT5 Strategy Tester — Complete Backtesting Guide

## 4 EAs Available for Backtesting

| EA File | Strategy | Best Pairs | TF |
|---|---|---|---|
| `MTF_HighAccuracy_Scalper.mq5` | 3-TF EMA alignment + RSI + ATR filter | XAUUSD, EURUSD, GBPUSD | M1/M5/M15 |
| `London_Breakout.mq5` | Asian range → London open breakout | EURUSD, GBPUSD, USDJPY, GBPJPY | M5 |
| `PriceAction_SR.mq5` | Pin bar + engulfing at S/R levels | EURUSD, GBPUSD, XAUUSD, USDJPY | M15 |
| `Trend_Momentum.mq5` | H1 trend + M15 MACD + M5 RSI pullback | EURUSD, GBPUSD, USDJPY, XAUUSD, EURJPY | M5 |

---

## Step 0: Download Maximum History (Do This First — ONE TIME ONLY)

1. Open MT5 → any chart
2. Navigator panel (Ctrl+N) → **Scripts** → double-click `DownloadMaxHistory`
3. Click OK — wait 5–15 minutes while it downloads all history
4. Watch Experts tab (Ctrl+T) — you'll see "=== DownloadMaxHistory complete ===" when done

> Without this step, Strategy Tester may only show limited bars. With it, you get the full broker history (often 5–15+ years).

---

## Step 1: Open Strategy Tester

Press **Ctrl+R** or go to **View → Strategy Tester**

---

## Step 2: Configure the Test

In the Strategy Tester panel at the bottom:

### Settings Tab
| Field | Value |
|---|---|
| **Expert** | Click dropdown → `TradingBot\MTF_HighAccuracy_Scalper` (or whichever EA) |
| **Symbol** | Select your pair (e.g., EURUSD) |
| **Period** | M1 for scalper, M5 for breakout/momentum, M15 for price action |
| **Model** | **Every tick based on real ticks** (most accurate) |
| **Date** | Uncheck "Use date" to test ALL available history |
| **Deposit** | 95 (your current balance) |
| **Currency** | USD |
| **Leverage** | 1:2000 (Exness default) |

### Inputs Tab
- Click **Inputs** tab
- Review/change EA parameters (all have good defaults)
- For optimization runs, you can set ranges here

---

## Step 3: Single Backtest

1. Click **Start** button
2. Watch the **Results** tab as trades appear
3. When complete, check:
   - **Graph** tab: equity curve should slope upward
   - **Results** tab: individual trades
   - **Report** tab: overall statistics

### Key Metrics to Look For
| Metric | Target |
|---|---|
| Profit Factor | > 1.5 |
| Win Rate | > 65% (70%+ is excellent) |
| Max Drawdown | < 20% |
| Sharpe Ratio | > 1.0 |
| Total Net Profit | Positive growth over time |

---

## Step 4: Optimization (Find Best Parameters)

1. Check **Optimization** checkbox in Settings tab
2. Go to **Inputs** tab → check the parameters you want to optimize
3. Set ranges: e.g., `EMA_Fast` from 5 to 15, step 2
4. Set **Optimization criterion**: Balance max or Custom (Profit Factor)
5. Click **Start** — this runs hundreds of combinations automatically
6. When done → **Optimization Results** tab → sort by **Profit Factor** descending
7. Double-click the best result to see its full backtest report

### Recommended Parameters to Optimize per EA

**MTF_HighAccuracy_Scalper:**
- EMA_Fast: 7–13, step 2
- EMA_Slow: 18–26, step 2
- RSI_BuyLo: 40–50, step 5
- RSI_BuyHi: 60–70, step 5
- Min_Body_Ratio: 0.30–0.50, step 0.05

**London_Breakout:**
- Asian_End_H: 6–8
- Min_Range_ATR: 0.2–0.5, step 0.1
- Max_Range_ATR: 1.5–3.0, step 0.5
- Breakout_Buffer: 0.0–0.2, step 0.05

**PriceAction_SR:**
- SR_Lookback: 30–80, step 10
- SR_Strength: 2–5
- PinBar_Wick_Ratio: 1.5–3.0, step 0.5
- EMA_Fast: 40–60, step 10

**Trend_Momentum:**
- EMA_H1_Fast: 40–60, step 5
- MACD_Fast: 8–16, step 2
- RSI_BullMin: 45–55, step 5
- EMA_Entry: 15–25, step 5

---

## Step 5: Compare Results Across Pairs

Run the same EA on multiple symbols and note results:

| EA | Symbol | Period | Win% | PF | MaxDD | Net Profit |
|---|---|---|---|---|---|---|
| MTF_Scalper | XAUUSD | M1 | ? | ? | ? | ? |
| MTF_Scalper | EURUSD | M1 | ? | ? | ? | ? |
| London_Breakout | GBPUSD | M5 | ? | ? | ? | ? |
| PriceAction_SR | XAUUSD | M15 | ? | ? | ? | ? |
| Trend_Momentum | EURUSD | M5 | ? | ? | ? | ? |

Fill in results as you run each test. Pick the **top 2 EAs** based on Profit Factor × Win Rate.

---

## Step 6: Read the Report

After any test, right-click in the Report tab → **Save as Report (HTML)** to save a full HTML report.

Key sections in the report:
- **Total net profit**: overall P&L
- **Profit factor**: gross profit / gross loss (>1.5 = good, >2.0 = excellent)
- **Expected payoff**: average profit per trade
- **Maximum drawdown**: worst peak-to-trough (keep under 20%)
- **Total trades**: more trades = more statistically reliable result

---

## Tips for 90%+ Accuracy Target

1. **Combine filters** — the more conditions that must align, the fewer but higher-quality trades
2. **Use optimization carefully** — if Win% is 90% on 10 trades, it's not meaningful. Aim for 100+ trades minimum
3. **Walk-forward test** — optimize on 2020–2023, then test on 2024 without re-optimizing. If results hold, the strategy is robust
4. **Avoid over-optimization** — if parameters only work on one specific year, that's curve-fitting, not a real edge
5. **Check multiple symbols** — a real strategy works across multiple pairs, not just one

---

## Where EA Files Are Located

```
C:\Users\Junait\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\
└── MQL5\
    ├── Experts\
    │   └── TradingBot\
    │       ├── MTF_HighAccuracy_Scalper.mq5  ← EA 1
    │       ├── London_Breakout.mq5            ← EA 2
    │       ├── PriceAction_SR.mq5             ← EA 3
    │       └── Trend_Momentum.mq5             ← EA 4
    └── Scripts\
        └── DownloadMaxHistory.mq5             ← Run first!
```

When you open Strategy Tester, these will appear under **Expert → TradingBot\\** in the dropdown.

> **Note:** MT5 compiles `.mq5` files automatically when you first run them in Strategy Tester. If you see a compile error, open the file in MetaEditor (F4) and press Compile (F7) to see the error details.
