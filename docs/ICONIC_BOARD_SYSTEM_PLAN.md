# Iconic Board Trader — Whole-Board Autonomous System (Build Plan)

Date: 2026-06-04. Supersedes the single-pair `iconic/agent.py` (USDCAD-only) with
the board-level system Navin actually teaches: **see the whole board → currency
strength → leader + group roll-over → book the leader → monitor/manage → close**,
plus **Eclipse** (A+news home-run, scale-IN).

Locked decisions (user, 2026-06-04):
- **Board universe:** 28 G7 FX pairs (USD EUR GBP JPY AUD NZD CHF CAD).
- **Trade target:** group LEADER, gated HARD on group roll-over (≥1 sister A/B same side).
- **Management:** scale-out 10/20/30 · stop-to-zero on drag · group-congestion exit · Eclipse scale-IN.

---

## What already exists (the brain — keep, don't rebuild)
- `iconic/confluence.py` — `classify_group`: whole-board A/B/C + leader per currency group.
- `iconic/correlation.py` — ±7 strength model, `pick_leader`, `correlation_tier`.
- `iconic/pattern.py` — Set1/Set2 money-spot + Test1/Test2 + Type1/2/3.
- `iconic/volume.py` — pop / climax / dead-Test2.
- `iconic/engine.py` — `evaluate(snapshots, strength)`: group map + group-roll-over (SOFT today) → `IconicTradeSignal` (carries tp_scale).
- `iconic/runner.py` — feeds the live scoreboard from SignalEngine's 32-symbol snapshots (now live on VPS).

## The gap (what we build)
The execution + management layers are single-pair and lack the board/system behaviors.

---

## Architecture — `iconic/board_trader.py` (new orchestrator)

```
                ┌──────────── BOARD LOOP (H1 bar close; manage every M3) ───────────┐
 28 pairs  ─►   1. fetch bars (H1 setup, M15 pullback, M3 cheese)  via bridge_client
                2. BOARD STRENGTH  → 8-currency meter (0..10) from EMA-dist/ATR + align
                3. engine.evaluate(snapshots, strength)   [HARD group roll-over gate]
                4. SELECT  leaders with sister confirmation + valid pattern + dead Test2
                5. RISK/EXPOSURE gate  → correlation-aware concurrent cap
                6. BOOK    position(s) on the leader(s)
                7. MANAGE  open book: scale-out 10/20/30 · stop-to-zero · group-exit · align-flip
                8. ECLIPSE if A+news+60m/3m align → scale-IN on pullbacks
                9. WRITE   board state (strength matrix, groups, leaders, book, actions) → dashboard
                └────────────────────────────────────────────────────────────────────┘
```

### Phases (each independently verifiable)
- **P1 — Board strength + decision wiring** *(safe; read-only, enriches live scoreboard)*
  - 28-pair fetch; real 8-currency strength meter; feed `classify_group`.
  - Verify: scoreboard shows sensible strength, groups, leaders across the board.
- **P2 — Hard group roll-over gate** in `engine.evaluate` (config flag; default hard for board).
  - Verify: leaders without a confirming sister are dropped, not just flagged.
- **P3 — Board execution + exposure control**
  - Book the leader; correlation-aware concurrent cap (don't stack N same-currency bets); 1% risk; daily DD.
  - Verify: paper/demo books only leaders, exposure respected.
- **P4 — Position management system**
  - Scale-out 10/20/30 (A=hold-to-extreme, B=meat); stop-to-zero on momentum drag; group-congestion exit; align-flip (exists).
  - Verify: trades show partials + BE moves + group exits in journal.
- **P5 — Eclipse scale-IN** (A + news + 60m/3m align → add on pullbacks, capped).
  - Verify: only fires under full confluence; adds respect total-risk cap.
- **P6 — Dashboard board view** (strength matrix, group/leader board, open book, actions). *(dashboard mandate)*
- **P7 — Board-level backtest** (walk-forward, real costs) BEFORE any unsupervised live; go/no-go per the project PF≥1.3 standard.

### Risk / safety
- Stays on the demo account; live execution behind the existing gate until P7 passes.
- Correlation-aware exposure cap is new + important: leader+sisters are the SAME directional bet — size the basket as one risk unit, not N.
- Eclipse scale-IN must respect a hard total-risk ceiling (compounding adds, not martingale).

### Migration
- New `board_trader.py` runs alongside; once P3–P4 verified on demo, cut `services.yaml` `iconic` cmd over from `iconic.agent` to `iconic.board_trader`. Keep `agent.py` until then.
