# Dashboard UI Polish — backlog & run log

Owned by the **dashboard-designer** agent (`.claude/skills/dashboard-designer/SKILL.md`),
which runs twice daily and makes ONE focused premium-UI improvement per run.
The agent reads this file first (to avoid repeating work and to pick the next
target) and appends to it last. Humans can reorder the backlog or drop notes here.

## Design system (do not drift from these)
- Tokens: `dashboard/frontend/tailwind.config.ts` · System doc: `dashboard/DESIGN.md`
- Utilities: `.glass`, `.eyebrow`, `.reveal`; ambient backdrop; `MetricCard` (hero/tone)
- Aesthetic: premium glass / cinematic, dark, tabular-num for figures, restrained motion.

## Pages (rotation pool — 26)
Overview · Fleet · StrategyPerformance · Positions · History · BotsAgents · SystemAgents ·
Pending · Reports · Logs · EAs · CppPortfolio · Jtcc · Signals · Desk · Iconic · Asia ·
Scalp · VolumeProfile · Journal · TelegramHQ · Settings · Hub · Factory · Intraday · SessionScalp

## Per-page polish state
<!-- agent maintains: page → last-polished date + one-line of what was done -->
| Page | Last polished | Notes |
|------|---------------|-------|
| _shared: PageLoader (App)_ | 2026-06-06 | Premium shimmer skeleton (header rail + metric grid + panel) replacing bare "Loading…" — shown on every lazy route transition |
| _shared: PageHeader_ | 2026-06-05 | Gradient accent kicker bar anchoring the title — consistent header rhythm across all routes |
| _shared: Table_ | 2026-06-04 | Premium empty-state (glyph badge + composed message) — lifts every data table |

## Backlog (highest-value first — agent may add/reorder)
<!-- Concrete, scoped improvement ideas. Agent picks the top viable one if it has
     no stronger idea from its own review of the current build. -->
1. Establish a per-page consistency baseline: shared PageHeader rhythm, panel spacing scale, empty-state polish.
2. Hierarchy pass on the highest-traffic pages first (Overview, Positions, History).
3. Microinteractions: hover/active states, reveal stagger, loading skeletons over bare spinners.

## Run log (newest first)
<!-- agent appends one block per run -->

### 2026-06-06 — PageLoader (shared, App.tsx)
- Change: Replaced the route-level Suspense fallback's bare `Loading…` text (a single pulsing string) with a premium skeleton scaffold that mirrors the common page shape — a kicker rail + title/subtitle header block, a 4-up metric-card grid (using the real `.glass` card surface + padding), and a primary panel with row placeholders. Each placeholder is a soft `bg-tint/30` block with a horizontal `animate-shimmer` sheen sweep; the whole thing fades in via `.reveal`. Shows on EVERY lazy route transition (all 26 routes).
- Why premium: Structural skeletons that match the destination layout are the signature loading pattern of premium fintech/SaaS dashboards — they communicate "content arriving" and preserve spatial stability, vs a centered spinner/string that reads as unfinished and shifts layout on load. Realizes backlog #3 (loading skeletons over bare spinners). Single-file, zero new deps — reuses existing `shimmer` keyframe, `.glass`/`.reveal` utilities, and `tint`/`sheen` tokens.
- Build: pass (local `npx vite build` 9.65s + VPS `npx vite build` 16.38s) · Visual: skipped (time-boxed; additive className-only skeleton, very low risk + prior Windows browser-daemon instability — relied on build-gate + live bundle/HTTP canary) · Deployed: :8010 (live serves new bundle `index-CrH-AkQv.js`, HTTP 200) · Commit: a090f39

### 2026-06-05 — PageHeader (shared)
- Change: Added a slim (3px) vertical gradient accent kicker bar (`from-accent to-accent-dim`, rounded, faint accent glow) to the left of the title block in the shared `PageHeader`. Self-stretches to the title+subtitle height. Propagates a consistent premium header anchor to every route that uses `PageHeader` (12+ pages).
- Why premium: A colored kicker rail beside the heading is a signature fintech/terminal hierarchy cue — it anchors the Z-pattern entry point and gives every page a deliberate, branded start instead of bare text. Uses only existing tokens (`accent`/`accent-dim`, `bg-gradient-to-b`, rounded-full) — no new deps, no aesthetic drift. Realizes backlog #1 (shared PageHeader rhythm), which the prior run designed but could not ship.
- Note: This run unblocked the prior skip — the VPS `./pages/Strength` divergence is resolved (VPS now has `pages/Strength.tsx`; its `npx vite build` succeeds). VPS frontend rebuilds cleanly again.
- Build: pass (local `npx vite build` 8.77s + VPS `npx vite build` 20.92s) · Visual: skipped (time-boxed; additive className-only change, very low risk — relied on build-gate + live bundle/HTTP canary) · Deployed: :8010 (live serves new bundle `index-DEc2gNMN.js`, HTTP 200) · Commit: edc95f2

### 2026-06-05 05:54 UTC — PageHeader (shared) — SKIPPED (blocked)
- Intended change: add a premium accent kicker bar (gradient `from-accent to-accent-dim`) anchoring the title in the shared `PageHeader`, propagating consistent header rhythm to all 26 routes (backlog #1). JSX/className-only, backward compatible.
- Why skipped: could not obtain a verified passing build gate. (a) Local build impossible — `dashboard/frontend/node_modules` is not installed (only `@babel` present) and the npm registry is unreachable (`npm error ... read ECONNRESET`), so `npx vite build` / `npm i` both fail. (b) VPS build gate fails on a PRE-EXISTING, unrelated divergence, NOT this change: `Could not resolve "./pages/Strength" from "src/App.tsx"`. Local `App.tsx` has no such import and no `pages/Strength*` exists locally — the VPS frontend source tree is diverged/dirty and currently cannot rebuild.
- Action taken: reverted local edit (`git checkout`) and restored the VPS `PageHeader.tsx` to origin/master. The failed VPS build did NOT emit a new `dist/`, so the live bundle was never replaced. Canary: live :8010 returns HTTP 200, still serving `index-B8_ePNGl.js` — no regression, no harm.
- ⚠️ Human action needed: the VPS `dashboard/frontend/src/App.tsx` imports a non-existent `./pages/Strength`. The frontend cannot be rebuilt on the VPS until this is reconciled — this will block ALL future dashboard-designer deploys, not just this one.
- Build: BLOCKED (local deps missing + registry ECONNRESET; VPS pre-existing `./pages/Strength` resolve error) · Visual: skipped · Deployed: none (reverted) · Commit: log-only

### 2026-06-04 13:20 UTC — Table (shared primitive)
- Change: Replaced the bare muted "No data" text in the shared `Table` empty cell with a composed empty state — an outlined glyph badge (soft glass circle) above the message in clearer `text-secondary` hierarchy, with a gentle `reveal` fade. Propagates to every data table (Positions, History, EAs, BotsAgents, Journal, Reports, SystemAgents).
- Why premium: Polished empty states are a signature of premium fintech UIs; a bare centered string reads as unfinished. Icon-in-circle + restrained copy is the established pattern (backlog item #1: empty-state polish). Uses only existing tokens (border, bg-white/[0.03], text-muted/secondary, reveal, font-sans) — no new deps.
- Build: pass (local `npx vite build` + VPS `npx vite build` 31.66s) · Visual: verified on identical preview build — desktop Positions ("No open positions"), desktop History ("No trades found"), and mobile Positions all render correctly, centered, responsive, no regression · Deployed: :8010 (live serves new bundle `index-CVDjXt8b.js`) · Commit: fef45e6
- Note: live logged-in canary screenshot was blocked by local headless-browser daemon instability on Windows (daemon dropped mid-session); verification relied on the byte-identical preview build + confirmed live bundle hash + clean live page load.

<!--
### YYYY-MM-DD HH:MM UTC — <Page/Component>
- Change: <one line>
- Why premium: <reference / rationale>
- Build: pass · Visual: no regression · Deployed: :8010 · Commit: <sha>
-->
