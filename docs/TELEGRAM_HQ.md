# Telegram HQ — Operator Guide

The HQ is one Telegram **supergroup** where every team posts to its own
**forum topic**. It's the system's headquarter: notifications go out by team,
EA approvals and Maic chat work two-way in-topic, a daily digest rolls
everything up, and the dashboard controls it all.

## One-time setup

1. **Create a supergroup** in Telegram (new group → add at least one member,
   then it can be upgraded to a supergroup automatically).
2. **Enable Topics**: open the group → *Edit* → toggle **Topics** on.
3. **Add the bot** to the group, then promote it to **Admin** and grant the
   **Manage Topics** permission (also keep "Post messages").
4. In the group, send **`/hq_setup`**. The bot creates all 10 topics, captures
   their thread ids, links the group, and posts a hello message in each topic.
5. Verify with **`/hq_status`** — every topic should show a thread id and 🟢.

That's it. The group id and topic map are saved to
`trading_agents/telegram_hq_config.json` (no manual id copying).

## The 10 topics

| Topic | What lands here |
|---|---|
| 🧭 CEO · Maic | Chat with Maic; delegation summaries |
| 💹 Live Trading | Trades, signals, trader offline / MT5 down / daily-DD breach, live-trader errors |
| 🛡️ EA Guardian | Live EA watchdog anomalies |
| 🎓 EA Coach · Approvals | Graduation / improvement decisions — **reply YES / NO / TEST MORE here** |
| 🧪 EA Validator | Compatibility matrices, verdicts |
| 🛠️ Dev Team | Code review, tests, debug, sync drift, doc updates |
| 🔭 Strategy Scout | New ideas, backtests, pitches |
| 🧭 Supervisor | System-wide audits |
| 📊 Daily Digest · Reminders | Daily rollup + reminders for unanswered approvals |
| 🚨 Critical Alerts | Mirror of every CRITICAL from any team |

Severity (good / bad / error) is shown **inside** each topic with an
`ℹ️ / ⚠️ / 🚨` prefix.

## Two-way control

- **Approvals** — when EA Coach asks a question, just reply `YES`, `NO`, or
  `TEST MORE` in the *EA Coach · Approvals* topic. If several EAs are waiting,
  prefix the EA name: `S6 YES`.
- **Maic** — type anything in the *CEO · Maic* topic (or any topic) and Maic
  answers. Each topic keeps its own conversation thread.
- Commands: `/hq_setup`, `/hq_status`, `/status`, `/reset`, `/start`.

## Dashboard

**Dashboard → Telegram HQ**:

- Setup status + instructions if not linked.
- **Topic Routing** — per-topic enable/mute toggle and a **Test** button.
- **Behavior** — mirror-critical toggle, daily-digest on/off, digest hour
  (UTC), approval-reminder interval.
- **Recent Notifications** — live audit feed from `logs/telegram/outbox.jsonl`.

## How it works

- Single hub: `trading_agents/telegram_hq.py`. Everything routes through
  `send(category, message, level)`. `dev_agents/notifier.py` is a thin
  backward-compatible shim over it (legacy `notify()` calls still work and land
  in Dev Team).
- The digest/reminders runner `trading_agents/telegram_hq_digest.py` is started
  automatically by `start_bot.ps1` (run `--once` / `--reminders` to fire manually).
- Backend (`dashboard/backend/core/state_manager.py`, `log_tailer.py`) pushes
  trader-offline / MT5-down / daily-DD / ERROR events into the `live_trading`
  topic.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/hq_setup` says Topics not enabled | Enable *Topics* in group Edit settings |
| `/hq_setup` errors creating topics | Make the bot an admin with **Manage Topics** |
| Nothing arrives | `/hq_status` — is the group linked? Is the topic 🟢 enabled? Token in `.env`? |
| Want to test without spamming | Set `TELEGRAM_HQ_DRYRUN=1` — writes to the outbox only |
| Identical message dropped | Hub de-dupes identical text within 60s (anti-spam) |
