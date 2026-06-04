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
| _seed_ | — | no runs yet |

## Backlog (highest-value first — agent may add/reorder)
<!-- Concrete, scoped improvement ideas. Agent picks the top viable one if it has
     no stronger idea from its own review of the current build. -->
1. Establish a per-page consistency baseline: shared PageHeader rhythm, panel spacing scale, empty-state polish.
2. Hierarchy pass on the highest-traffic pages first (Overview, Positions, History).
3. Microinteractions: hover/active states, reveal stagger, loading skeletons over bare spinners.

## Run log (newest first)
<!-- agent appends one block per run -->
<!--
### YYYY-MM-DD HH:MM UTC — <Page/Component>
- Change: <one line>
- Why premium: <reference / rationale>
- Build: pass · Visual: no regression · Deployed: :8010 · Commit: <sha>
-->
