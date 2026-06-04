## VPS is the target (definition of done)

The live system runs on the **VPS** (`trader@72.62.228.196`), not locally — the
local stack is down by choice. Therefore **every change targets the VPS**: a task
is NOT done until the change is deployed to the VPS *and verified running there*.
"Committed locally" or "works locally" is not done. After any code/config change,
confirm it took effect on the VPS (file present, service restarted, new PID,
state/log reflects it). Deploy gotchas (auto-deploy restarts only dashboard +
telegram; agents/bridge need manual restart; VPS repo is behind + dirty so NO
blanket `git pull` — copy only changed files): see `docs/OPS_RUNBOOK.md`.

## Operations

For anything operational — VPS access/deploy, account info, service list, restart
procedures, ports, where state/logs live, secrets location — read
`docs/OPS_RUNBOOK.md` first. It is the single source of operational truth shared
across all sessions. If an operational fact changes, update it there so the next
session inherits it.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
