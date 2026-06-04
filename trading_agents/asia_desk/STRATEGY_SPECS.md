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

---

# Deep-research additions (2026-06-04, batch 2 — BTC/gold/pairs/high-WR tactics)

## S6 — Fake-Breakout / Stop-Hunt Reversal (Liquidity Sweep) ⭐ highest claimed WR
- **Claim:** 80% WR **when aligned with 4H/1H trend** (else much lower).
- **Range:** 00:00–06:00 UTC box, OR Donchian(20) on M15 (dynamic).
- **False break:** price breaks Asian high/low (grabs stops), fails, rejection wick.
- **Entry:** confirmation candle CLOSES back inside range opposite the sweep (+ M5 volume spike). Market entry on that close.
- **HTF align:** only long-reclaim-of-low in uptrend; only short-reclaim-of-high in downtrend.
- **SL:** beyond the sweep wick extreme. **TP:** 1:2 (partial + trail), or 60–75% range width.
- **Filters:** RSI(14) 30–70 (skip if trending out = true breakout); BB(20,2) M15 — false break pierces band then rejects.
- **Pairs:** JPY crosses + gold + BTC.

## S7 — Time-based reversals
- **Tokyo lunch 03:00–03:30 UTC:** fade the 00:00–03:00 trend. Target 5–15 pips, tight SL.
- **Tokyo close ~06:00 UTC:** fade earlier session move if at structure (Donchian/PDH-PDL). Exit before 07:00.

## Gold (XAUUSD) — best hours + bias
- **Best 01:30–08:00 UTC** (SGE opens 01:30, MCX 03:30 = institutional volume). Worst 22:00–01:30.
- Gold **favors BREAKOUT** in Asia (volume injections disrupt ranges). Goldmine v2: box 00–02, exec 02–04,
  4H/D bias align, **pullback-to-boundary entry**, SL 1.5×ATR(14), TP 1:2–1:3, exit pre-London.
- Also: Fibonacci continuation — 78.6% fib limit on M15 impulse after a 4H key-level close; TP 15m structure → 4H level.

## BTC (BTC/USD)
- **AMD:** accumulation box 00:00–06:00 UTC → manipulation sweep 06:00–08:00 (London) at 3–4 SD → MSS/FVG reversal → target opposite boundary. (= S2/S6 family on BTC.)
- **Range-London breakout:** range 00:00–07:00 UTC, buy-stop +5p above / sell-stop −5p below at 07:00, SL mid/opposite, TP 1.0–1.5× range width.

## Best Asian-session pairs (source consensus)
- **Best = single-driver Yen crosses: USDJPY, GBPJPY, EURJPY** (clean Yen volume) → matches our validated S1.
- AUD/JPY, NZD/JPY = "battle" crosses (mixed). AUDUSD/NZDUSD volatile. EURUSD/GBPUSD/EURGBP quiet→range.
- Session strongly favors **range/mean-reversion over breakout** (except gold + Tokyo-open momentum 00:00–01:00).

## Risk params (institutional guide)
- 0.25–0.5% risk/trade. Daily stop at 1.5–2% loss OR 3 consecutive losses. RR 1:1.5–1:2 (sweeps up to 1:2).
- Silver (XAGUSD): NOT covered in sources — test empirically only.

## Claimed win-rates (UNVALIDATED — backtest decides)
80% sweep+HTF · 75–85% range night-scalp S/R · 70–80% VWAP/MA reversion · 60–70% manual range · 48% retail baseline.
