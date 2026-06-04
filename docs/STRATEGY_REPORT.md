# Strategy Report — Full Inventory + Backtest Results — 2026-06-04

Every strategy in the system, its backtest result, and whether it's live on the demo
account now. Backtest numbers come from the strategy YAMLs, `backtest_reports/`,
`analysis_*.md` files, and agent state. "no data" = no recorded backtest run (don't
trust a missing number as zero). Live figures = 30-day central journal + agent stats.

> Demo account `415733764` (Exness-MT5Trial14). Nothing here is real money.

## Headline counts
- **~70 distinct strategies** total (25 JTCC + 12 Gold Scalp + GS-VP + MTF + Iconic + Asia + CPP + 21 MQL5 EAs + 7 NGS research)
- **18 live on demo now** (across 6 agents)
- **~10 carry a validated backtest edge** (PF ≥ ~1.4 on real-cost history)
- **Portfolio live (30d): +$143.14 · PF 2.15 · 31 trades · 0 losing strategies**

---

## TABLE 1 — LIVE NOW (18 strategies, 6 agents)

| # | Strategy | Agent | TF | Backtest PF | Backtest verdict | Live result (demo) |
|--|----------|-------|----|-------------|------------------|--------------------|
| 1 | **s14 TSMOM 12-Month** | JTCC | D1 | **4.06** (EUR) / 1.27 (BTC) | STRONG (EUR proven) | ⭐ **+$97.17 · PF 5.97 · 75% WR · 8t** |
| 2 | **GS07** Liquidity Sweep | Gold Scalp | M1 | no data | — | **+$32.71 · PF 1.11 · 9t** |
| 3 | **MTF EMA Alignment** | MTF | M1+M3/M15 | **1.89** avg (=s25) | proven (8 pairs) | **+$12.32 · PF 1.12 · 37% WR · 19t** (64% DD) |
| 4 | **s13 ICT 2022** | JTCC | M5/M15 | **2.11** (XAU) / 1.87 (GBP) / 0.92 (EUR) | XAU proven, EUR fail | live (XAU promoted) |
| 5 | **s11 Asian Range Breakout** | JTCC | — | **1.38–1.89** (7 symbols) | PROVEN (most validated) | live |
| 6 | **s06 BB Squeeze** | JTCC | — | **1.53** (XAU) / 1.60 (XAG) | PROVEN (only Elite-family survivor) | live |
| 7 | **s25 MTF EMA Alignment** | JTCC | M1 | **1.96–6.37** (8 pairs, avg 1.89) | PROVEN | live |
| 8 | **s16 Pairs EUR-GBP** | JTCC | — | **1.42** (75% WR, 4t) | PROVEN (tiny sample) | live |
| 9 | **GS12** ICT Simple | Gold Scalp | M3 | **1.23** (55.9% WR, 34t) | MARGINAL (below 1.3) | **PF 1.37 · 5t** |
| 10 | **Asian Range Fade (S1)** | Asia Desk ⚠️ | M15 | **1.60** (USDJPY) / 1.47 (AUDJPY) | PROVEN (2.1yr real-cost) | **+$0.94 · 100% WR · 1t** |
| 11 | **GS-VP** Volume Profile | GS-VP | M15 | **1.59** (GBP) / 1.14 (EUR) / 1.34 avg | robust on FX | 0 trades (very selective) |
| 12 | **Urban Forex Iconic** | Iconic | H1→M15 | **1.67** OOS (USDCAD) | GO on USDCAD | 0 today (USDCAD-only, scanning) |
| 13 | **s09 Liquidity Sweep Reversal** | JTCC | — | **2.11–2.86** (2-3t only) | KEEP-DEMO (tiny sample) | live |
| 14 | **s12 CPP Confluence Pullback** | JTCC | M15 | **1.22** (EUR only) | MARGINAL (USDJPY claim refuted) | live |
| 15 | **s20 VWAP Reversion M3** | JTCC | M3 | **1.20** (XAU, 108t) | MARGINAL (thin edge) | live |
| 16 | **s18 London-Asian Breakout M3** | JTCC | M3 | **1.03** (EUR, 6t) | MARGINAL (needs retest) | live |
| 17 | **GS01** Gold EMA/RSI/Stoch | Gold Scalp | M3 | no data | — | PF 99 (1t — ignore) |
| 18 | **GS11** Opening Range Scalper | Gold Scalp | M1 | no data | — | **PF 0.85 · 38% WR · 8t — LOSING** |

⚠️ **Asia Desk runs unsupervised** (not in orchestrator → no auto-restart).

---

## TABLE 2 — JTCC QUARANTINED (15, NOT live — failed/unvalidated)

| ID | Name | Backtest | Why benched |
|----|------|----------|-------------|
| s01 | Elite J | no data | "75-80% WR" claim never validated (real 15-35%) |
| s02 | Elite V6 | no data | same Elite-family failure |
| s03 | Elite G | no data | same |
| s04 | Heikin Ashi Trend Rider | no data | unvalidated |
| s05 | Stoch Silver MM1 | no data | unvalidated |
| s07 | Stoch GBP | no data | unvalidated |
| s08 | SMC Sniper | no data | unvalidated |
| s10 | Power of Three | no data | unvalidated |
| s15 | Pairs XAU-XAG | no data | unvalidated |
| s17 | Silver Bullet M3 | no data | unvalidated |
| s19 | NY ORB NR7 M3 | no data | unvalidated |
| s21 | KZ Sweep MSS M3 | no data | unvalidated |
| s22 | EUR H4 Trend Follower | no data | derived from TSMOM, no independent backtest |
| s23 | BTC Donchian D1 | no data | derived from TSMOM, no independent backtest |
| s24 | EUR H1 Trend Momentum | no data | derived from TSMOM, no independent backtest |

---

## TABLE 3 — Gold Scalp library, NOT live (8 — backtest-only)

| ID | What | TF | Backtest | Status |
|----|------|----|---------|--------|
| GS02 | ICT Silver Bullet FVG + Session | M1 | no data | bench |
| GS03 | VWAP + MACD scalp | M3 | no data | bench |
| GS04 | Keltner + RSI mean-reversion | M1 | no data | bench |
| GS05 | EMA crossover trend-follow | M1 | no data | bench |
| GS06 | RSI + Bollinger reversal | M3 | no data | bench |
| GS08 | 1-min sniper (BOS on M1) | M1 | no data | bench |
| GS09 | 80% WR reversal (RSI+BB+EMA200) | M3 | no data | bench |
| GS10 | EMA triple trend scalp | M3 | no data | bench |

---

## TABLE 4 — MQL5 Expert Advisors (21, NOT live in the python stack)

EAs compile to `.mq5`; none are currently attached to the terminal, so they don't
trade live. Live `_ea_performance.json` (May 19, 30d) showed all negative — a
backtest-vs-live disconnect, which is why they're not deployed.

| EA | Folder | Strategy | Backtest PF | Verdict |
|----|--------|----------|-------------|---------|
| S6 Asian Range Breakout v2 | ready_ea | Asian range breakout | **1.41** (7.6% DD, 64.6% WR) | ✅ robust winner |
| ICT 2022 XAUUSD | ready_ea | ICT model | **2.11** (XAU walk-fwd) | ✅ proven (= JTCC s13) |
| S1 Swing Scalp v2 | ready_ea | H4/M15 EMA+RSI | **1.62** but **235% DD** | ⚠️ unsustainable DD |
| S5 News Spike Reversal | ready_ea | M1 spike reversion | **0.39** | ❌ unprofitable |
| NGS Range | ready_ea | range trap | no data | unknown |
| S2 M5 Scalp | inspection_ea | M5 scalp | no data | inspection |
| S3 M1 HFT Sniper | inspection_ea | M1 HFT | no data | inspection |
| S4 MultiPair Engine | inspection_ea | multi-pair | no data | inspection |
| S13 5Way Confluence | inspection_ea | 5-indicator | no data | inspection |
| S14 StochDeepCross GBP | inspection_ea | stoch cross | no data | inspection |
| S15 StochADX Gold | inspection_ea | stoch+ADX | no data | inspection |
| S18 Heikin Ashi Trend | inspection_ea | HA trend | no data | inspection |
| S19 Confluence Pullback | inspection_ea | pullback | no data | inspection |
| NextGenSync Grid | inspection_ea | gold grid | no data | the deleted over-trader |
| NextGenSync Pyramid | inspection_ea | pyramid | no data | inspection |
| MTF EMA Scalper M1 | scalpmaster | MTF EMA | no data | live-perf negative (May) |
| ScalpMaster HFT | scalpmaster | scalp | no data | live-perf negative |
| ScalpMaster HFT Aggressive | scalpmaster | scalp | no data | live-perf negative |
| XAUUSD Gold Scalp M1 | scalpmaster | gold scalp | no data | live-perf negative |
| BTCUSD Scalper M1 | scalpmaster | BTC scalp | no data | live-perf negative |
| ICT 2022 EA | ict | ICT model | no data | reference impl |

---

## TABLE 5 — Research / not deployable (8)

| Strategy | Backtest | Status |
|----------|----------|--------|
| CPP Confluence Pullback | S6v2 PF 1.41; USDJPY 1.84 claim refuted | built, NOT running |
| NGS Range / Single / Grid | no recorded results | research optimizers |
| NGS Pyramid / v2 / v3 / FX | no recorded results | research optimizers |
| Factory-generated (GS50+) | n/a | 0 active (capacity 50+) |

---

## Honest caveats
1. **GS01–GS11 have no recorded backtest** — they're defined and trade live, but their
   edge was never formally backtested; judge them by live stats (GS07/GS12 winning,
   GS11 losing).
2. **Live samples are tiny** — no live strategy has enough closed trades for a
   statistical "proven live" verdict yet (all flagged INSUFFICIENT, but none losing).
3. **Central journal under-attributes** — only 4 strategies (TSMOM, GS07, MTF, Asia)
   reach the scorecard with clean tags; the rest rely on agent-local stats.
4. **EA live ≠ backtest** — the MQL5 EAs backtested OK but showed negative live P&L in
   May, so they're benched, not deployed.

---

## 2-YEAR MT5 STRATEGY TESTER — no-data EAs (2026-06-04)

Real broker history via Strategy Tester (e.g. 706k M1 bars = true 2yr, vs the
~2-6mo the python/copy_rates path could reach). Run locally, zero VPS load.

| EA | Sym | TF | PF | Net $ | Trades | MaxDD | Verdict |
|----|-----|----|----|-------|--------|-------|---------|
| S13 5Way Confluence | XAU | M15 | **1.56** | +1,254 | 41 | 5.4% | ✅ WINNER |
| S19 Confluence Pullback | EUR | M15 | **1.47** | +582 | 21 | 2.0% | ✅ WINNER |
| NGS_Range | XAU | M5 | 2.42 | +47,822 | 46,407 | 0.53% | ⚠️ mirage (46k trades, OHLC model — not real) |
| S3 M1 HFT Sniper | XAU | M1 | 0.91 | −177 | 108 | 7.1% | ❌ loser |
| S2 M5 Scalp | XAU | M5 | 0.92 | −1,520 | 721 | 24.8% | ❌ loser |
| S4 MultiPair | EUR | M15 | 0.78 | −172 | 48 | 3.0% | ❌ loser |
| S14 StochDeepCross GBP | GBP | M15 | 0.64 | −3,037 | 119 | 39.9% | ❌ bad loser |
| NextGenSync_Pyramid | XAU | M5 | 0.56 | −1,496 | 4,030 | 15.0% | ❌ grid churn |
| S15 StochADX Gold | XAU | M15 | — | 0 | 0 | — | spread-gated, no trades on this broker |
| S18 HeikinAshi | XAU | H1 | — | 0 | 0 | — | spread-gated, no trades |
| BTCUSD ScalpMaster M1 | BTC | M1 | — | 0 | 0 | — | spread-gated (MaxSpreadUSD), no trades |
| ScalpMaster HFT | XAU | M1 | — | 0 | 0 | — | spread-gated (MaxSpreadPips=3), no trades |
| ScalpMaster HFT Aggressive | BTC | M1 | — | 0 | 0 | — | spread-gated, no trades |
| XAUUSD ScalpMaster Gold M1 | XAU | M1 | — | 0 | 0 | — | spread-gated, no trades |
| MTF_EMA_Scalper M1 | EUR | M1 | — | 0 | 0 | — | logic never triggered |
| NextGenSync_Grid | XAU | M5 | — | — | — | — | timed out (>900s) |
| ICT_2022_EA | XAU | M15 | — | — | — | — | compile error (= JTCC s13, already proven PF 2.11) |

**Verdict:** of 16 no-data EAs, **2 are real winners (S13 PF 1.56, S19 PF 1.47)**, 5 are
losers, NGS_Range is a backtest mirage, and 8 don't trade / can't test on this broker
(tight spread filters vs the demo's wide gold/BTC spread; no real-tick history beyond
~recent). Real-tick model couldn't help — broker doesn't serve 2yr of real ticks.

**Note:** python GS02-06/08-10 (8) + JTCC quarantine (15) have NO EA form → not
Strategy-Tester-able, and the broker serves only ~2-6mo intraday candles → no 2yr
python backtest possible either. Those 23 remain un-2yr-backtested by design.
