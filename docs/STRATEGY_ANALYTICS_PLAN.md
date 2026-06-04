<!-- /autoplan restore point: ~/.gstack/projects/hasanjunait2023-mt5-bot/master-autoplan-restore-20260603-161921.md -->
# Strategy Performance & Improvement Intelligence — FINAL PLAN (autoplan-reviewed)

**Goal:** Owner + Maic CEO can answer, on-demand and on schedule:
1. Which strategy is **profitable** vs not (realized P&L, PF, win-rate, expectancy).
2. **Who needs improvement** (ranked, sample-gated).
3. **Where & how** to improve (concrete, per-strategy, **anchored to backtests** until live sample is large).

**North star (owner's call — improve, don't kill):** losing strategies are **not demoted/killed**. They are **continuously improved until profitable** by learning from (a) their **mistakes** (losing trades), (b) their **correct decisions** (winning trades — what actually worked), and (c) **research** (existing researcher/scout/factory + new sources). The system's job is to drive every strategy toward profitability and only stop iterating when it gets there. Visibility (1-3) exists to **feed** that loop, not to justify cutting strategies.

Delivered via: one dashboard page + Telegram report + a data-backed CEO + an improvement loop.

> Reviewed via /autoplan (Claude CEO + Eng + Design lenses; codex unavailable on this box). Key reframes below came out of review — read "Reality check" first.

---

## ⚠️ Reality check (read before building)
The live journal today holds **~25–37 closed trades total, almost all MTF**. With a sane gate (`n≥20`), a pure-live per-strategy scorecard would read **"insufficient" in nearly every cell on day one** — after building everything. Two consequences shape this plan:
- **Fuse backtests with live.** "Which strategy makes money?" is answered for months primarily from the **existing cost-applied backtests** (CPP/S6v2/JTCC-validated verdicts already in the repo), with live data shown as *confirmation/divergence*, not as standalone truth. The scorecard shows **both** backtest-PF and live-PF side by side.
- **Account provenance matters.** Demo/soak and live fills must never be blended in a verdict. Every close is tagged `account_login` + `demo|live`; the scorecard filters to one.

---

## Current capability (verified 2026-06-03) — ~40% there
Engine exists, pipeline broken in 3 places:
- **Profitability:** `trade_journal.get_stats()` computes per-strategy PF/WR/expectancy/net-P&L, but only **MTF** writes complete open→close records. **Scalp, Iconic, JTCC never call the close path** (not "no-op stubs" — the close call is simply absent: open at `scalp/agent.py:582`, `iconic/agent.py:523`, `jtcc/main.py:278`; no matching close). Their trades sit `OPEN`/`pnl=None` → dropped from stats. **Today's dashboard per-strategy P&L is MTF-only and misleading.**
- **Diagnosis:** `loss_analyzer.py` (real per-strategy failure forensics) is NOT scheduled (dashboard-hit only). Coaches run (6h) but "how" is 6 generic templates; nothing auto-applies.
- **CEO:** `maic_ceo_agent.py` has no read-path to stats → answers "which strategy profitable?" from LLM memory, not data. `eod_review.py` is an explicit SCAFFOLD.

---

## Architecture decisions (locked by review)
1. **Close-reconciler lives IN THE BRIDGE** (`api_server.py`), as a background poller — not a standalone service, not in any agent. The bridge is the only process with a native `mt5` handle; a standalone reconciler would just be bridge code in the wrong process calling MT5 over HTTP. (Resolves old Open-Decision #1.)
2. **Journal becomes append-only.** `close_trade`'s full-file `_flush` rewrite + the `_loaded` latch corrupt data across 4 writer processes (one process rewrites the file from its stale in-memory view and erases other agents' records — real data-loss bug, F3/F4). Fix: emit a `{type:"close", position_id, ...}` **appended JSONL line**; `get_stats`/`get_all` fold opens+closes at read time. The **reconciler is the single close-writer**. Drop the `_loaded` latch (re-read on mtime change).
3. **Matching key = `deal.position_id`** (not order ticket). Strategy attribution comes from the **journal's stored `strategies[]`** (set at open), NOT re-derived from magic — Scalp's GS11/GS07/GS01/GS12 all share magic `20260522`; only the open `comment`/journal record distinguishes them.
4. **One canonical magic registry** (`configs/` module) consumed everywhere; delete the 3 divergent maps (`TRACKED_MAGICS` mtf:33, `EA_MAGICS` mtf:439, per-agent constants). Reconciler treats **any magic present in the journal** as in-scope (don't hardcode a set — that's why Scalp 20260522 / Iconic 20260700 were silently dropped).

---

## Plan (phases, dependency-ordered)

### Phase 1 — Data foundation  *(KEYSTONE — every downstream number depends on it)*
- **1a. Bulk-history endpoint (new):** `GET /history/deals?from=&to=` on the bridge → `history_deals_get(from,to)` returning `position_id, magic, comment, entry, reason, profit, swap, commission, time`. (Today the bridge only has per-ticket `/history/deals/{ticket}` — the reconciler/backfill **cannot work without this**; biggest unstated dependency in the old plan.)
- **1b. Bridge close-reconciler (background poller):** every N s, pull recent deals, match each closed deal to its open journal record by `position_id`, append a `close` event with `exit_price, pnl(=profit+swap+commission), outcome(from deal.reason, fallback price-tolerance), close_time, hold_minutes, actual_rr, account_login, demo|live`. **Idempotent** (closing an already-closed record = no-op; running twice never double-counts). Tag each close with the original record's **sub-strategy** + **account**.
- **1c. Journal → append-only** (decision #2). Convert `close_trade` callers? No — agents stop calling close entirely; the reconciler owns closes. Kill JTCC's parallel `performance_tracker.log_trade_close` **only after** confirming no reader (eod_review/coach) depends on `_jtcc_performance.json` (F8).
- **1d. Backfill once** the OPEN-forever Scalp/Iconic/JTCC records from `history_deals(from,to)`.
- **1e. Enrich `get_stats`:** add `by_agent` rollup, **time windows** (7d/30d/inception), per-strategy **isolated drawdown** (running-sum on that strategy's ordered closed-pnl — *explicitly labelled "strategy DD ≠ account DD"*, F6), **avg actual_rr**, and a `sample_ok` flag (`n<20 → insufficient`). Add a **portfolio top-line** (realized P&L + equity curve) — the one number trustworthy at any N.
- **Verify (automated tests, not eyeball):** (i) concurrency no-clobber — ≥3 processes journaling opens + reconciler writing closes, zero lost records; (ii) reconciler idempotency + attribution (run twice = pnl once; two scalp strategies on magic 20260522 keep distinct `strategies[]`; partial/multi-deal position → one summed close; open-with-no-close stays OPEN); (iii) backfill reconciles **to the penny** against independently-summed `history_deals(from,to)`, and out-of-registry magics excluded.

### Phase 2 — Scorecard + scheduled diagnosis
- **2a. `strategy_scorecard.py`** — single source of truth consumed by CEO + dashboard + Telegram. Per (sub)strategy: `{verdict, live_pf, backtest_pf, win_rate, expectancy, net_pnl, isolated_dd, avg_rr, n, sample_ok, trend_7d_vs_30d, account, top_failure_mode, fix_headline(≤90 chars), fix_details[]}`. **Verdict rule (one definition, same in dashboard + Telegram):** `n<20 → INSUFFICIENT (grey)`; else `PF≥1.3 AND net>0 → PROFITABLE (green)`; else `LOSING (red)`.
- **2b. Schedule diagnosis:** new `analytics` service in `configs/services.yaml` runs `loss_analyzer` per strategy on the live journal every N h → writes `logs/_strategy_scorecard.json`.
- **2c. Sharpen "how" — sample-gated + backtest-anchored:** replace the 6 generic `_SUGGESTIONS` templates with an LLM pass (`llm_fallback.chat_resilient`) — **but hard-gate it**: no per-symbol/per-strategy fix is generated below `n≥30` for that bucket; below threshold the only output is "insufficient — keep observing" or "live confirms/contradicts backtest." Every fix references the pre-existing backtest, never invents an edge from live noise.
- **2d. Win analyzer (mirror of loss_analyzer) — learn from CORRECT decisions:** new `win_analyzer.py` that aggregates **winning** trades per strategy: which sessions/symbols/setups/confluence-bands actually produced profit, what the winners had in common (high RR, specific KZ, htf-bias alignment). Output `win_patterns` per strategy. This is half the improvement signal the owner asked for — the loop must reinforce what works, not only patch what fails. Feeds the scorecard (`strength_headline`) and the Phase 5 loop.

### Phase 3 — CEO + report
- **3a. CEO read-path:** add `[DELEGATE: portfolio_stats]` to `maic_ceo_agent.py` → returns the scorecard JSON; inject into Maic's prompt. "Which strategy is profitable / who needs improvement / how" now answered from real numbers (+ backtest context).
- **3b. Complete `eod_review.py`** (remove SCAFFOLD): compute the scorecard, generate sample-gated LLM proposals, deliver to Telegram + dashboard, **register in `services.yaml`** (daily EOD + weekly deep).
- **3c. Improvement trigger** (owner's call — improve, NOT demote): when a strategy is `LOSING` over `n≥30`, it is flagged **"in improvement"** (not demoted) and enqueued for the Phase 5 loop. CEO/Telegram reports it as "Strategy X under improvement — iteration k, last change Y, PF trend Z" so the owner sees progress toward profitability, not a kill notice.

### Phase 4 — Dashboard  *(mandatory per project rule)*
- **One new "Strategy Performance" page** that **supersedes Journal's stats half** (relabel `/journal` → "Trade Log" for raw trades). **Do NOT** big-bang-merge the signal/chart pages (jtcc/signals/desk/intraday/scalp/iconic) — that's a separate redesign; descoped.
- **Verdict-first layout** (not a table): 3 hero MetricCards (net P&L window · profitable X/Y · needs-fix N), then **ranked sections Profitable → Losing → Insufficient**, sorted by net P&L within each. **2 levels:** primary rows = agent rollup (MTF/JTCC/Scalp/Iconic); expand → per-sub-strategy + per-symbol + failure-mode bars + equity sparkline + full "how". Losing rows show the **≤90-char fix inline**. Window toggle 7d/30d/All (sample-guard is window-aware).
- **Required states (plan specifies them, else looks broken):** loading skeleton; empty ("no closed trades yet — appear after positions close + reconcile"); **insufficient-sample** bucket (`◌ n=X · need 20`, never green/red under threshold); **paper-gated** badge (`Advisory — paper-gated by promotion_gate`); **reconciler-stale** stamp ("last reconciled HH:MM" + "unreconciled (n open)" rather than silently dropping).
- Reuse design system (DESIGN.md): `MetricCard`, `.glass` rows, `StatusDot` verdict dot, `MistakeBadge`, mono `font-tabular`, flat charts (no gradients/shadows; animate only the status dot).

### Phase 5 — Improvement loop  *(the north star — improve until profitable, never kill)*
Per `LOSING` (or marginal) strategy, run an iterative loop that drives it toward profitability:
1. **Diagnose** — pull `loss_patterns` (2c, mistakes) + `win_patterns` (2d, correct decisions) + the strategy's original backtest verdict.
2. **Research** — query existing engines (`strategy_researcher.py`, `strategy_scout`, `factory/research.py`, video/NotebookLM sources) for refinements relevant to this strategy's failure mode (e.g. better SL placement, session filter, confluence weighting).
3. **Propose a change** — concrete, bounded (param tweak / symbol filter / session restriction / confluence threshold). Reinforce what `win_patterns` shows works; fix what `loss_patterns` shows fails.
4. **Backtest the change** (REAL-COST, the existing harness) → must beat the current config AND clear `PF≥1.3` before going further (no live change on backtest-only hope).
5. **Gate + apply** — human approval (Telegram button / dashboard) behind `promotion_gate` + fail-closed safety; apply to the live config.
6. **Re-measure** — track live PF over the next `n≥30`; if still losing, loop again (iteration k+1) with the new data. **Stop only when profitable** (sustained `PF≥1.3`).

Each iteration is journaled (`logs/_improvement/<strategy>.jsonl`: hypothesis → change → backtest delta → live result) so the loop learns across attempts and the owner/CEO sees the improvement history. The loop **proposes and backtests autonomously**; **applying a live change stays human-gated** (one Telegram tap). Nothing is ever killed — a strategy that can't be made profitable after K iterations is parked as "needs human rethink," still visible, not deleted.

---

## Decision audit trail (autoplan auto-decisions)
| # | Phase | Decision | Principle | Rejected |
|---|-------|----------|-----------|----------|
| 1 | Eng | Reconciler in bridge, not standalone/agent | P3/P5 | standalone service (extra process+HTTP hop) |
| 2 | Eng | Journal append-only + fold-on-read; reconciler = single close-writer | P5 | keep full-rewrite (data-loss across processes) |
| 3 | Eng | Add bulk `/history/deals?from=&to=` | P1 | rely on per-ticket only (can't poll/backfill) |
| 4 | Eng | Canonical magic registry; attribute strategy from journal not magic | P4/P5 | per-agent magic sets (drops scalp/iconic; can't split shared-magic strategies) |
| 5 | CEO | Tag closes with sub-strategy + account/demo; portfolio top-line | P1 | per-agent only (can't drive kill/keep) |
| 6 | CEO | Fuse backtest-PF + live-PF in scorecard | P1 | live-only (reads "insufficient" everywhere for months) |
| 7 | CEO/Eng | Hard-gate LLM "how" by sample size; anchor to backtest | P1 | free LLM fixes on tiny N (confident overfit nonsense) |
| 8 | Design | Verdict-first ranked page, not table; 2-level rollup | P5/P1 | flat scorecard table (buries the verdict) |
| 9 | Design | Descope journal/jtcc/signals/tv consolidation | P3 | big-bang merge (stalls the analytics win) |
| 10 | Eng | Outcome from `deal.reason`; isolated-DD labelled ≠ account-DD | P5 | price-tolerance only; DD mislabel |

## Owner decisions (gate)
- **User Challenge resolved — IMPROVE, don't kill.** Owner rejected auto-demote of losers. North star = iterate each strategy toward profitability using its mistakes + its correct decisions + research (Phase 5). Phase 3c flags "in improvement," never demotes. Added Phase 2d **win analyzer** so the loop learns from what works, not only what fails.
- **v1 scope = Full build, Phase 1–4** (owner's call). Phase 5 improvement loop follows once visibility (1–4) is live. Note: with today's tiny live sample, the dashboard will honestly show many strategies as "insufficient (n<X)" for the first months — backtest-PF columns carry the verdict until live N grows. That's expected, not a bug.

## Sequencing
Phase 1 is the keystone — build and **verify against MT5 to the penny** before anything else. Phases 2–4 follow (v1); Phase 4 consumes the Phase 2 scorecard. Phase 5 (improvement loop) is the goal and begins once 1–4 are live.
