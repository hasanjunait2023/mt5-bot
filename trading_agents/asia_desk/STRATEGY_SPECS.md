# Asian-Session Strategy Specs

Extracted 2026-06-04 from NotebookLM notebook `ff4c0929` (23 sources: ICT, PipStorm,
institutional guide, gold/forex Asian-session articles). These are the **claimed**
rules; every one must clear PF ≥ 1.3 on real-cost backtest before demo deploy.
Claimed win-rates are unvalidated — per [[project_jtcc_validation]] textbook WR claims
usually fail real backtests.

Session phases (UTC):
- **Range-hold** 00:00–06:00 — Tokyo, low vol, range usually holds.
- **London-sweep** 06:00–08:00 — Frankfurt/London open breaks/sweeps the Asian range.

---

## S1 — Asian Range Fade (mean-reversion)
- **Pairs:** USDJPY, AUDUSD
- **Range:** high/low of 00:00–02:00 UTC (≥2 touches each side)
- **Entry:** long near support, short near resistance (fade)
- **Filter:** RSI(14) between 30–70 (skip if trending outside → breakout forming)
- **TP:** 60–75% of range width (e.g. 18–22 pips on a 30-pip range)
- **SL:** 10–15 pips beyond support/resistance; RR ≥ 1:1, ideally 1:1.5
- **Exit:** close all before 07:00 UTC (London breaks range)
- **TF:** M15/M30 · **Claimed WR:** 60–70%

## S2 — ICT Asian Range Liquidity Sweep (smart-money reversal)
- **Pairs:** USDJPY, AUDUSD, NZDUSD, AUDJPY, NZDJPY (+ gold, BTC)
- **Range:** Asia high/low ~00:00–05:00 UTC (20:00 ET → 00:00 ET); BTC box 00:00–06:00 UTC
- **Entry trigger:** price breaks Asia high/low during 06:00–08:00 UTC (sweeps retail stops),
  reaching 1–4 SD from midnight-ET open. Then M1/M5 **MSS** opposite + displacement/**FVG**.
  Limit at 78.6% fib of manipulation leg (or blind at SD level).
- **SL:** beyond the sweep wick (or next SD level)
- **TP:** partial at 50% of Asian range; final = opposite Asia boundary; RR ≥ 2.5:1
- **Claimed WR:** none stated; edge = high RR
- *Backtest approximation:* detect sweep of Asia range in 06–08 window, enter reversal on
  M15 close back inside, SL beyond sweep extreme, TP opposite boundary. (No M1 MSS/FVG in v1.)

## S3 — PipStorm Asian Range Breakout (momentum)
- **Pairs:** GBPUSD
- **Range:** absolute high/low 23:00–08:00 UTC
- **Entry:** market order the moment price breaks range high/low (no candle close)
- **Filter:** Daily MACD histogram — long if >0 & rising, short if <0 & falling; conflict = skip
- **SL:** opposite side of the range · **TP:** 1:1 (range height)
- **Claimed WR:** none stated

## S4 — Classic Asian ORB
- **Pairs:** USDJPY, AUDJPY, NZDJPY, AUDUSD, NZDUSD
- **Range:** first 30–60 min after Tokyo open 00:00 UTC
- **Entry:** full candle close outside the opening range
- **SL:** inside opening-range boundary (or ATR) · **TP:** fixed 10–20 pips
- **Claimed WR:** none stated

## S5 — Gold "Goldmine" pullback-breakout
- **Instrument:** XAUUSD
- **Box:** 00:00–02:00 UTC consolidation; **execute** 02:00–04:00 UTC
- **Entry:** candle closes outside box AND aligns with 4H/Daily HTF bias; enter on pullback
  to the broken boundary (limit/market)
- **SL:** 1.5 × ATR(14) beyond the breakout candle's low/high
- **TP:** 1:2 or 1:3 RR; exit all before 07:00 UTC
- **Claimed WR:** none stated; edge = RR + avoiding London liquidity grabs
