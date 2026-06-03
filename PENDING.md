# Pending Board

Single place for two kinds of unfinished work:

1. **Pending tasks** — things deferred on purpose. Edit this section by hand.
2. **Stalled agents** — agents whose work stopped progressing (state file went
   stale past its `max_age` in `configs/services.yaml`). Auto-detected by
   `scripts/pending_tracker.py`; do not edit that section by hand.

Run a scan: `python scripts/pending_tracker.py --once`
Run continuously (VPS): `python scripts/pending_tracker.py --loop --interval 300`

---

## Pending tasks (manual)

| # | Task | Deferred | Note |
|---|------|----------|------|
| 1 | VPS dashboard auth verify — `DASHBOARD_PASSWORD` / `DASHBOARD_ALLOWED_ORIGINS` set on VPS `.env` | 2026-06-03 | prod-gated; run `grep` on VPS `.env`, fail-open if unset |
| 2 | VPS-side terminal relaunch (wine `terminal64.exe`) | 2026-06-03 | bridge self-heal + Windows watchdog already done; VPS leg needs wine path + test |
| 3 | Scaling: **auto de-risk after losses** | 2026-06-03 | safest scaling add (capital protection); design + backtest first |
| 4 | Scaling (risk-increasing): live pyramiding / equity-tier risk ladder / win-streak risk-up | 2026-06-03 | only if backtest-proven; pyramiding flagged "proven impossible" on current symbols |
| 5 | VPS restart: bridge + Iconic + Scalp — load close-reconciler (`a0daf09`) + demo-execution (`3bef3a4`); then check `/reconciler/status` | 2026-06-03 | do on next VPS visit; code committed, needs restart to take effect |
| 6 | Signal systems → demo execution: signal_engine / alpha_desk / factory_paper have no executor; need separate Exness demo accounts (decide count) + per-system routing | 2026-06-03 | 1 account = margin conflict with the 4 live agents; bigger infra task, awaiting account count |
| 7 | Secrets/SSH cross-session sharing — adopt **sops + age** encrypted-in-repo (recommended). Keys exist: `~/.ssh/vps_trader`, `~/.ssh/vps_controller` | 2026-06-04 | scaffold ready; needs go-ahead to encrypt+commit on the key-holding box (real secrets → GitHub, encrypted) |

> Add a row when you say "keep this pending". Remove it when done.

---

## Stalled agents (auto — do not edit)

<!-- STALLED:START -->
_No scan yet. Run `python scripts/pending_tracker.py --once`._
<!-- STALLED:END -->
