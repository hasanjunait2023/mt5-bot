# Strategy Tester Validation Plan — inspection_ea → ready_ea

Goal: forward-validate the 4 built-but-unvalidated winner EAs in the MT5 Strategy
Tester. If a run clears the PASS bar below, move the EA `inspection_ea/ → ready_ea/`,
update `README.md` + the Notion EA Build Tracker, then it's demo-ready.

Rule of the project: **live == tested**. Run each EA with its **default inputs**
(the supplied `.set`) first — that mirrors the Notion backtest. Only S14 needs an
extra calibration pass (its ATR filter is undefined in spec, default OFF).

## Common Tester settings (all 4)

| Setting | Value |
|---|---|
| Model | **Every tick based on real ticks** (fallback: *1 minute OHLC* — these EAs act on CLOSED bars, so OHLC is acceptable) |
| Deposit | **1000 USD** |
| Leverage | **1:1000** |
| Optimization | Off (single backtest) — except S14 calibration pass |
| Inputs | **Load the matching `.set`** (Tester → Inputs tab → Load) |

Presets copied to: `<MT5 data>\MQL5\Presets\` (also in `mql5_experts/inspection_ea/*.set`).

## Per-EA config

| EA | Symbol | TF | Period | `.set` |
|---|---|---|---|---|
| S13 5-Way Confluence | **BTCUSD** | **H1** | last **12 months** | `S13_5Way_Confluence.set` |
| S18 Heikin Ashi Trend Rider | **XAUUSD** | **D1** | last **2 years** | `S18_HeikinAshi_TrendRider.set` |
| S14 Stoch Deep Cross | **GBPUSD** | **H1** | last **12 months** | `S14_StochDeepCross_GBP.set` |
| S15 Stoch + ADX | **XAUUSD** | **H1** | last **12 months** | `S15_StochADX_Gold.set` |

## PASS / FAIL bar (graduate only if ALL met)

Notion backtests used tiny Yahoo samples (3–14 trades); broker tick data will
differ. These gates are deliberately conservative — they confirm the edge is
real and profitable, not that it reproduces Notion exactly.

| Metric | PASS threshold |
|---|---|
| Net profit | **> 0** (positive return) |
| Profit Factor | **≥ 1.5** |
| Max drawdown | **≤ 15%** |
| Win rate | **≥ 50%** |
| Total trades (in window) | **≥ 8** (S18: ≥ 10 over 2y) — not 1–2 lucky trades |
| Journal | **no** "invalid stops" / order-send errors |

Notion reference (what "good" looks like): S13 PF∞/0%DD (tiny), S18 71% WR /
PF 4.96, S14 PF 5.26 / 0.98% DD, S15 50% WR / PF 4.81.

→ **All pass:** move EA + `.set` to `ready_ea/`, update `mql5_experts/README.md`
and the Notion EA Build Tracker (Stage = READY), then 30-day demo.
→ **Any fail:** stays in `inspection_ea/`. Note which metric failed.

## S14 special — ATR filter calibration (extra pass, after baseline)

S14's `MinATRpct` (ATR/Close*100 floor) is **OFF by default** (0.0) because the
Notion spec never defined its scaling. Run the baseline first (filter off). Then
a second **Optimization** pass to calibrate it:

- Tester → Inputs → tick **MinATRpct** for optimization
- Start `0.00`, Step `0.02`, Stop `0.30`
- Optimized criterion: **Balance + max Profit Factor**
- Pick the `MinATRpct` value that maximises PF **while keeping ≥ 8 trades**.
- Put that value in `S14_StochDeepCross_GBP.set` before promoting.

## After validating — keep records synced

For each EA that passes, update **both**:
1. `mql5_experts/README.md` (move row to the ready_ea table)
2. Notion EA Build Tracker (page 363bbf27-1afa-81fc-a45a-f22be57becfa) — Stage → READY

so repo ↔ Notion stays in sync (the project's source-of-truth rule).
