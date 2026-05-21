# MT5 Expert Advisors — Index

All MQL5 EAs live here, one parent folder, organized by **status** (the deploy pipeline).
Last updated: 2026-05-19.

## Folder structure

```
mql5_experts/
├── README.md          ← this file (the index)
├── ready_ea/          ← VALIDATED — mirrors a passing backtest, demo/live-ready
├── inspection_ea/     ← BUILT — compiles clean, NOT yet Strategy-Tester validated
├── scalpmaster/       ← older, separate ScalpMaster strategy family
└── docs/
    └── BACKTEST_GUIDE.md   ← how to run MT5 Strategy Tester
```

## The pipeline (how an EA graduates)

```
inspection_ea/   →   ready_ea/   →   30-day demo   →   live ($100–200)
   (built)         (backtest OK)      (forward test)     (real money)
```

Rule of the project: **live == tested**. An EA only moves to `ready_ea/` after its
logic is validated against a passing backtest. Don't add "improvements" to a
`ready_ea/` EA without re-running its backtest.

---

## ✅ ready_ea/ — validated, deploy-ready (3)

| EA file | Strategy | Asset | TF | Notion rank / backtest |
|---------|----------|-------|----|------------------------|
| `S1_Swing_Scalp.mq5` | S1 Low-Freq Swing Scalp | XAUUSD | H4 bias → M15 entry | 🥉 #3 · PF 4.31 · mirrors `backtest_s1_v2` |
| `S5_News_Spike_Reversal.mq5` | S5 News Spike Reversal | XAUUSD | M1 | target WR 72–78% |
| `S6_Asian_Range_Breakout.mq5` | S6 Asian Range Breakout (OCO) | XAUUSD | M15 | PF 1.43 · mirrors `backtest_s6_v2` |

## 🛠️ inspection_ea/ — built, needs Strategy Tester (7)

| EA file | Strategy | Asset | TF | Notion rank / note |
|---------|----------|-------|----|--------------------|
| `S13_5Way_Confluence.mq5` | S13 5-Way Confluence | BTCUSD | H1 | 🥇 #1 (100% WR, only 3 trades — A+-only) |
| `S18_HeikinAshi_TrendRider.mq5` | S18 Heikin Ashi Trend Rider | XAUUSD | D1 | 🥈 #2 · +93.55% · PF 4.96 |
| `S14_StochDeepCross_GBP.mq5` | S14 Stoch Deep Cross + Trend | GBPUSD | H1 | #4 · PF 5.26 · ⚠️ `MinATRpct` needs calibration |
| `S15_StochADX_Gold.mq5` | S15+ADX Stoch Cross + ADX | XAUUSD | H1 | #5 · PF 4.81 (ADX gate = the edge) |
| `S2_M5_Scalp.mq5` | S2 M5 Medium-Freq Scalp | XAUUSD | M5 | core scalper |
| `S3_M1_HFT_Sniper.mq5` | S3 M1 HFT Sniper | XAUUSD | M1 | high-frequency |
| `S4_MultiPair_Engine.mq5` | S4 Multi-Pair Engine | XAU/XAG/GBP/EUR/JPY | M1 | run per-pair |

## 🧪 scalpmaster/ — older separate family (5)

Not part of the S-series Notion strategies. Surfaced in the dashboard via
`dashboard/backend/api/eas.py` (`EA_DIR` points here).

| EA file | Strategy | Asset | TF |
|---------|----------|-------|----|
| `MTF_EMA_Scalper_M1.mq5` | Multi-TF EMA 200/9/15 crossover | 28 FX + XAUUSD + BTCUSD | M1 (+M3+M15) |
| `ScalpMaster_HFT.mq5` | Score-based momentum (EMA+RSI+ATR+BB+MACD) | EURUSD, XAUUSD, BTCUSD | M1 |
| `ScalpMaster_HFT_Aggressive.mq5` | Aggressive ScalpMaster variant | EURUSD, XAUUSD, BTCUSD | M1 |
| `XAUUSD_ScalpMaster_Gold_M1.mq5` | Gold-tuned M1 scalper (WR 58–61%, PF 2.2–2.7) | XAUUSD | M1 |
| `BTCUSD_ScalpMaster_M1.mq5` | BTC M1 scalper | BTCUSD | M1 |

---

## Notes

- Full strategy specs (entry/exit, backtest stats) live in Notion → **"XAUUSD Gold
  Trading Bot System — Master Hub"**. Each strategy page has a `🛠️ EA BUILD STATUS`
  block kept in sync with this folder.
- `.ex5` (compiled binaries) are git-ignored; only `.mq5` source is tracked.
- Compile: `& "C:\Program Files\MetaTrader 5\metaeditor64.exe" /compile:"<file>" /log`
- Backtest steps: see `docs/BACKTEST_GUIDE.md`.
