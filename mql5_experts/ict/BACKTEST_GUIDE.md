# ICT 2022 EA — Backtest & Optimization Guide

## File
`ICT_2022_EA.mq5` — ICT 2022 Mentorship Model on M5

## Strategy Pipeline
```
D1/H4 Bias Score (≥+3 bull / ≤-3 bear)
  → Kill Zone (London 07–10 UTC / NY 12–15 UTC)
    → Liquidity Sweep (SSL for longs, BSL for shorts)
      → MSS on M5 (displacement candle + FVG + structure break)
        → FVG or OB in OTE zone (0.618–0.786 fib)
          → Market entry · SL beyond swept extreme
            → TP1 at 1:1.5R (50% close + BE) · TP2 at 1:3R
```

## Bias Scoring (max ±8 pts)
| Condition | Bull | Bear |
|---|---|---|
| D1 close above 5-day range EQ | +2 | -2 |
| D1 HH+HL (trending up) | +2 | -2 |
| Recent D1 liquidity sweep | +1 | -1 |
| H4 discount/premium zone | +1 | -1 |
| **Threshold** | **≥+3** | **≤-3** |

## Kill Zones (UTC)
| Zone | UTC | Bangladesh (UTC+6) |
|---|---|---|
| Asian KZ | 01:00–05:00 | 07:00–11:00 |
| London KZ | 07:00–10:00 | **13:00–16:00** |
| NY Open KZ | 12:00–15:00 | **18:00–21:00** |
| SB NY AM | 15:00–16:00 | **21:00–22:00** ← highest prob |

## Backtest Setup (MT5 Strategy Tester)

### Step 1: Copy EA to MetaTrader
Copy `ICT_2022_EA.mq5` to:
```
C:\Users\[user]\AppData\Roaming\MetaQuotes\Terminal\[ID]\MQL5\Experts\
```
Compile in MetaEditor (F5).

### Step 2: Tester Settings
```
Expert:     ICT_2022_EA
Symbol:     EURUSD (start here, then GBPUSD, XAUUSD)
Timeframe:  M5
From:       2022.01.01
To:         2025.12.31
Modeling:   Every tick based on real ticks
            (or "OHLC on M1" for faster preliminary tests)
Deposit:    10000 USD
Leverage:   1:100 (use 1:1000 for Exness)
```

### Step 3: Load .set file
In Parameters tab → Load → `ICT_2022_EA.set`

### Step 4: Run & evaluate
Required thresholds (from phase404 reference benchmarks):
- Profit Factor ≥ 1.3
- Max Drawdown ≤ 12%
- Win Rate ≥ 40%
- Avg RR ≥ 1:2
- Minimum trades ≥ 150 per symbol per year

### Step 5: Walk-forward validation
- Optimize on 2022–2023 data
- Validate on 2024–2025 (untouched)
- If live PF < 80% of backtest PF → do not deploy

## Optimization Ranges

| Parameter | Min | Step | Max | Notes |
|---|---|---|---|---|
| InpSwingLen | 3 | 1 | 10 | Swing detection sensitivity |
| InpBiasDays | 3 | 1 | 7 | EQ lookback |
| InpOTE_High | 0.500 | 0.059 | 0.618 | OTE upper bound |
| InpOTE_Low | 0.705 | 0.040 | 0.786 | OTE lower bound |
| InpMinFVGPips | 2.0 | 1.0 | 8.0 | Noise filter |
| InpSLBufferPips | 2.0 | 1.0 | 5.0 | SL beyond swept extreme |
| InpTP2_RR | 2.0 | 0.5 | 4.0 | Final target |

**Optimize for: highest Profit Factor, NOT highest returns**

## Symbol-Specific Settings

| Symbol | InpBrokerGMT | InpMinFVGPips | InpSLBufferPips | Notes |
|---|---|---|---|---|
| EURUSD | 2 | 3 | 3 | Cleanest ICT pair |
| GBPUSD | 2 | 3 | 3 | Wider range, London primary |
| XAUUSD | 2 | 8 | 8 | High velocity, min 30-pip SL typical |
| XAGUSD | 2 | 10 | 10 | Wider spreads, skip if spread > 4× normal |
| USDJPY | 2 | 3 | 3 | NY primary, DXY-sensitive |
| BTCUSD | 2 | 50 | 50 | 24/7, adjust pip to 1.0 |

## Stage Deployment (from research doc)
1. **Stage 1 (wk 1–2)**: EURUSD + GBPUSD + XAUUSD, London+NY only
2. **Stage 2 (wk 3–6)**: Backtest validation, walk-forward
3. **Stage 3 (wk 7–18)**: $100 demo 30 days → $1000 live at 0.25% risk
4. **Stage 4 (mo 5+)**: Add XAGUSD, USDJPY, BTCUSD one at a time

## Live Go/No-Go Checklist
- [ ] Backtest PF ≥ 1.3 on each symbol
- [ ] Walk-forward PF ≥ 80% of in-sample PF
- [ ] Max DD ≤ 12% in backtest
- [ ] ≥ 150 trades per symbol per 3-year backtest
- [ ] 60 live forward-test trades at 0.25% risk
- [ ] Live PF ≥ 80% of backtest PF
- [ ] Live DD ≤ 1.5× backtest DD

## Expected Realistic Performance
Per the research doc (ICT methodology analysis):
- Win rate: **40–55%** (not 70%+)
- Profit factor: **1.2–2.0** in good conditions
- Trades/day: **2–5 combined** across all symbols (NOT 10–15)
- Live degradation vs backtest: **20–40%** is normal

**Stop trading if:**
- Live win rate < 35% over 60 trades
- Live DD > 8% on any single day  
- Live PF < 1.1 over 100 trades
