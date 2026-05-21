# MT5 Strategy Tester — Backtest Guide
## 6 Strategies | XAUUSD | Last 2 Years

---

## Step 1 — Copy EA Files to MT5

1. Open MetaTrader 5
2. Click **File → Open Data Folder**
3. Go to `MQL5 → Experts`
4. Copy all 6 `.mq5` files from this folder into that `Experts` folder:
   - S1_Swing_Scalp.mq5
   - S2_M5_Scalp.mq5
   - S3_M1_HFT_Sniper.mq5
   - S4_MultiPair_Engine.mq5
   - S5_News_Spike_Reversal.mq5
   - S6_Asian_Range_Breakout.mq5

---

## Step 2 — Compile All EAs

1. In MT5, open **MetaEditor** (F4 or Tools → MetaEditor)
2. Open each `.mq5` file
3. Press **F7** to compile — no errors should appear
4. Go back to MT5

---

## Step 3 — Download Historical Data

For accurate backtesting, download the full tick data first:

1. **Tools → Options → Charts** → Set "Max bars in chart" to **9999999**
2. Open **Tools → History Center**
3. Select **XAUUSD → M1** → Click **Download**
4. Wait until download completes (may take 10–20 minutes for 2 years)
5. For S4 multi-pair, also download: XAGUSD M1, USDJPY M1, GBPUSD M1, EURUSD M1

---

## Step 4 — Run Strategy Tester

Go to **View → Strategy Tester** (Ctrl+R)

### Settings for each backtest:

| Setting | Value |
|---------|-------|
| Mode | **Every tick based on real ticks** (most accurate) |
| Date | From: **2024-01-01** To: **2026-05-17** (2 years) |
| Deposit | **1000 USD** |
| Leverage | **1:1000** |
| Optimization | No |

---

## Strategy-Specific Settings

### S1 — Swing Scalp
- **EA**: S1_Swing_Scalp
- **Symbol**: XAUUSD
- **Timeframe**: M15
- **Initial Deposit**: $1,000
- **Risk**: 1.0% (default)

### S2 — M5 Scalp
- **EA**: S2_M5_Scalp
- **Symbol**: XAUUSD
- **Timeframe**: M5
- **Risk**: 0.5% (default)

### S3 — M1 HFT Sniper
- **EA**: S3_M1_HFT_Sniper
- **Symbol**: XAUUSD
- **Timeframe**: M1
- **Risk**: 0.3% (default)

### S4 — Multi-Pair (run separately per pair)
- **EA**: S4_MultiPair_Engine
- **Symbol**: XAUUSD / XAGUSD / USDJPY / GBPUSD / EURUSD
- **Timeframe**: M1
- **Risk**: 0.3% (default)
- Run 5 separate backtests, one per pair

### S5 — News Spike Reversal
- **EA**: S5_News_Spike_Reversal
- **Symbol**: XAUUSD
- **Timeframe**: M1
- **Note**: Real news calendar not available in backtester.
  EA detects large M1 spikes (>80 pips) as news proxy automatically.

### S6 — Asian Range Breakout
- **EA**: S6_Asian_Range_Breakout
- **Symbol**: XAUUSD
- **Timeframe**: M15
- **Risk**: 0.5% (default)

---

## Step 5 — Read the Report

After backtest completes, click the **Report** tab. Key metrics to check:

| Metric | Target |
|--------|--------|
| Profit Factor | > 1.5 |
| Win Rate | > 60% |
| Max Drawdown | < 20% |
| Net Profit | > 0% |
| Expected Payoff | > 0 |

Click **Save as Report (HTML)** to save a full report with charts.

---

## Broker GMT Offset

If your broker is UTC+3 (most common — Exness, Tickmill):
- All EA inputs with `BrokerGMT` = **3** (default)
- Sessions are already in UTC internally — no change needed

---

## Notes

- S3 and S4 (M1 HFT) will generate the most trades — expect 30-50/day
- S1 (Swing) will have the fewest trades — 2-5/day
- S5 (News) may have very few trades in backtester since it relies on real spikes
- S6 (Asian Range) = 1 trade per day maximum
- Use "Every tick based on real ticks" mode for M1 strategies
- Use "1 minute OHLC" is OK for S1 (M15/H1 based) to run faster
