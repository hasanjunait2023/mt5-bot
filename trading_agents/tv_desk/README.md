# TV Desk — TradingView analysis agents

Two scheduled agents that read TradingView directly (via the `tradingview-mcp`
desktop over CDP), run institutional structure analysis, **mark up the chart**,
screenshot it, and publish to the dashboard + Telegram. TradingView is the single
data source AND the drawing canvas — no MT5.

| Agent | When | Output |
|-------|------|--------|
| **Intraday Analyst** (`intraday_analyst.py`) | once/day at NY close (configurable BD hour) | 3 intraday day-trades per symbol, 1:2 & 1:3, open+close within the day |
| **Session Scalper** (`session_scalper.py`) | 30 min before Asia / London / NY open | 2–3 scalps per symbol for the upcoming session, 1:2 (+1:3 runner) |

Instruments (7 favorites, configurable in `config.py` / `TV_DESK_SYMBOLS`):
Gold `OANDA:XAUUSD`, Bitcoin `BINANCE:BTCUSDT`, Silver `OANDA:XAGUSD`,
Oil `TVC:USOIL`, `OANDA:EURUSD`, `OANDA:GBPUSD`, `OANDA:USDJPY`.

## Pipeline (per symbol)

`structure.py` (reuses Alpha Desk zones/liquidity/orderflow on TV OHLCV) →
`synthesize.py` (LLM via `llm_fallback.chat_resilient` + **deterministic RR
validator** that recomputes SL/TP to the exact target; structure-based fallback
if the LLM is offline) → `annotate.py` (draws zones, key levels, E/SL/TP lines +
risk/reward boxes, screenshots) → `store.py` (logs/<agent>/) → Telegram + dashboard.

## Run manually

```bash
# one-off (no Telegram):
TV_DESK_NO_TELEGRAM=1 python -m trading_agents.tv_desk.intraday_analyst --once
TV_DESK_NO_TELEGRAM=1 python -m trading_agents.tv_desk.session_scalper --once --session london

# restrict symbols:
python -m trading_agents.tv_desk.intraday_analyst --once --symbol BTCUSD --symbol XAUUSD

# scheduled (what services.yaml runs):
python -m trading_agents.tv_desk.intraday_analyst --loop
python -m trading_agents.tv_desk.session_scalper --loop
```

## Prerequisites

1. **TradingView desktop running + logged in** with CDP on :9222
   (`C:\Users\Junait\tradingview-mcp\launch_tv_cdp.ps1`). Agents pre-check
   `tv_health_check` and skip the run (with a Telegram warning) if it's down.
2. **Dedicated layout** named `AUTOMATION` (set `TV_DESK_LAYOUT` to change).
   Create it once in TradingView so the agents draw there and leave your main
   chart untouched. If it doesn't exist they fall back to the active chart
   (clearing their own drawings each pass).
3. **Telegram topics** — new categories `analyst_daily`, `scalp_asia/london/ny`
   are added to `telegram_hq`. Run `/hq_setup` once so their forum threads are
   created; until then posts land in the group's General topic.

## Config knobs (env)

- `ANALYST_RUN_BD_HOUR` (default 0 = midnight BD ≈ 18:00 UTC; ~2 for true NY close)
- `TV_DESK_SYMBOLS` (JSON list to retarget instruments)
- `TV_DESK_LAYOUT`, `TV_MCP_SERVER`, `TV_NODE`
- `TV_DESK_NO_TELEGRAM=1` to silence Telegram (testing)

## Honest note on win rate

Configured for "more setups, lower bar" — so expect a **lower hit rate by
design**. Every call is persisted; wire the win-rate measurement (planned) to
tighten the filter once there's real data. No system guarantees a high win rate.

## Dashboard

- `/intraday` and `/session-scalp` pages (Sidebar → Intraday Analyst / Session
  Scalper). Per-symbol cards: bias, dealing range, PDH/PDL, entry table
  (E/SL/TP1/TP2/RR/win%), annotated TV screenshot.
- **Performance panel** (measured): win-rate by symbol (+ by session for scalper)
  and a recent-closed-trades feed, fed by `tracker.py` / `_perf.json`.
- API: `/api/intraday/{state,events,perf,chart/{id}}`,
  `/api/session-scalp/{state,events,perf,chart/{id}}`.

## Marking

Trades are drawn with the native TradingView **Long/Short Position tool** only
(green target = TP1, red stop = SL) — clean, no extra lines. Levels are exact:
distances converted to ticks via each symbol's `mintick` (config). TP2 stays in
the data; the chart shows the 1:2 target.

## "Make it perfect" checklist (manual, one-time)

1. **AUTOMATION layout** — in TradingView create a saved layout named `AUTOMATION`
   with a *clean* chart (few/no indicators). The agents draw there → spotless
   screenshots. Without it they use the active chart (works, just busier).
2. **/hq_setup** — run once in Telegram so the topics `analyst_daily`,
   `scalp_asia/london/ny` get forum threads. Until then the agents **skip**
   Telegram posts (no General-topic spam — guarded in `_common._topic_ready`).
3. **Sleep / reboot survival** — the orchestrator already supervises both agents
   (auto-restart on death). To also survive PC sleep/reboot, install it as a
   Windows service (admin):  `powershell -ExecutionPolicy Bypass -File scripts/install_service.ps1`
4. **Measurement phase** — let `_perf.json` accumulate real win-rate for ~1-2
   weeks before trusting setups with real risk. Tuning is "more setups / lower
   bar" by design → lower hit rate; tighten once data shows the winning
   symbols/sessions.
