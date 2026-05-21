Quarantined YAMLs (loaded but DISABLED based on empirical evidence).

s15_pairs_xau_xag.yaml — Quarantined 2026-05-20
  Reason: Backtest 2026-05-20 on 3 years D1 data showed PF 0.29 (UNPROFITABLE).
  XAU and XAG decoupled in recent period; spread mean-reversion edge broken.
  Restore: move back to ../ if metals re-couple and re-test passes (PF > 1.3).

s17_silver_bullet_m3.yaml — Quarantined 2026-05-20
  Reason: 0 trades in 10-day M3 backtest (all 4 symbols). D1 trend filter too
  strict in current NEUTRAL market. Re-test on 60+ days needed before promotion.

s19_ny_orb_m3.yaml — Quarantined 2026-05-20
  Reason: 0 trades in 10-day M3 backtest. NR7 filter is statistically rare
  (~1 day in 7-14). 10 days too short. Re-test on 60-90 days needed.

s21_killzone_sweep_mss_m3.yaml — Quarantined 2026-05-20
  Reason: 0 trades in 10-day M3 backtest. Full ICT confluence (D1 bias +
  KZ + sweep + MSS + FVG) too rare in 10 days. Re-test on 60+ days needed.

s22_eur_h4_trend_follower.yaml — Quarantined 2026-05-20 (NEW, never fired)
  Reason: 0 trades in 60-day M3 backtest. D1+H4 trend alignment too strict
  for current market (mostly NEUTRAL). Would need to allow neutral or use
  pure return-sign trigger like TSMOM.

s23_btc_donchian_d1.yaml — Quarantined 2026-05-20 (NEW, never fired)
  Reason: 0 trades in 60-day backtest. BTC backtest only has 80 D1 bars
  (limited by MT5 bridge); plus D1 trend filter blocks Donchian trigger.

s24_eur_h1_trend_momentum.yaml — Quarantined 2026-05-20 (NEW, never fired)
  Reason: 0 trades in 60-day backtest. ADX>25 filter never passes because
  backtest's adx is hardcoded to 20 (limitation of _build_ctx_at). Would
  need real ADX computation in backtest harness OR loosen ADX threshold.

s07_stoch_gbp.yaml — Quarantined 2026-05-21
  Reason: 0 trades on GBPUSD/GBPJPY H1 in backtest_jtcc.py walk-forward.
  Strict stoch+EMA filters never aligned. Original "66.7% WR" claim unsupported.

s08_smc_sniper.yaml — Quarantined 2026-05-21
  Reason: 0 trades on any symbol in backtest. SMC full-confluence filter
  (sweep+OTE+session+trend+news) too strict on M15. Statistically unattainable.

s10_power_of_three.yaml — Quarantined 2026-05-21
  Reason: 3 trades EUR (33% WR, PF 0.88) + 2 trades GBP (0% WR, PF 0.00).
  UNPROFITABLE on tested H1 timeframe. Insufficient trade count, all losing.

s12_cpp_pullback.yaml — Quarantined 2026-05-21
  Reason: 0 trades on EURUSD/GBPUSD/USDJPY H1. Strict pullback+stoch+EMA200
  filters never aligned. Note: the MQL5 CPP EA (different code) was previously
  validated; this YAML's rules don't match.

s07_stoch_gbp.yaml — Quarantined 2026-05-21 (REAL MOMENTUM TEST)
  Reason: 52 trades GBPUSD 25% WR PF 0.51 / 44 trades GBPJPY 27.3% WR PF 0.81.
  Clearly UNPROFITABLE on 96 total trades. Original "66.7% WR" claim disproven.

s10_power_of_three.yaml — Quarantined 2026-05-21 (REAL MOMENTUM TEST)
  Reason: 3 trades EUR (33% WR, PF 0.88), 2 trades GBP (0% WR), 0 XAU.
  Insufficient and unprofitable on tested H1.

=== ROUND 4 (session-fix + REAL momentum, 2026-05-21) ===
s01_elite_j.yaml — UNPROFITABLE. XAU 19tr 15.8%WR PF0.56 / XAG 43tr 18.6%WR PF0.37. "80% WR" claim FALSE.
s02_elite_v6.yaml — UNPROFITABLE. XAU 39tr 28.2%WR PF0.68. "76.9% WR" claim FALSE.
s03_elite_g.yaml — UNPROFITABLE. XAU 17tr 35.3%WR PF0.70 / XAG 41tr 22%WR PF0.27. "75% WR" claim FALSE.
s04_heikin_ashi.yaml — UNPROFITABLE. XAU 20tr 35%WR PF0.83 / XAG 54tr 29.6%WR PF0.55. "71.4% WR" claim FALSE.
s05_stoch_silver.yaml — UNPROFITABLE. XAG 45tr 22.2%WR PF0.74. "80% WR" claim FALSE.
s08_smc_sniper.yaml — 0 trades all 4 symbols. Full SMC confluence statistically unattainable on M15.
