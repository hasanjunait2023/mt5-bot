# Strategy Standard — Universal Rules for All Trading Agents

Every strategy/agent in this system — whether built by human or AI — must follow these rules.
Failure to comply means the strategy **will not be monitored and will not go live**.

---

## 1. Manifest Required

Every strategy must have a YAML file in `trading_agents/registry/strategies/<name>.yaml`.

**Required fields:**
```yaml
name:        Human-readable name
id:          Unique snake_case identifier (e.g. iconic, scalp_gs11)
mode:        paper | live | dry-run
state_file:  Path to _agent_state.json (relative to project root)
```

No manifest = not monitored = not live. There are no exceptions.

---

## 2. State Schema — Heartbeat Required

Every agent must write `updated_at` (ISO 8601 UTC) on every bar/tick cycle.
State files older than 120 seconds are marked **stale** on the dashboard.

Minimum state file shape:
```json
{
  "agent_name": "...",
  "agent_id": "...",
  "status": "running|halted|stopped",
  "mode": "paper|live|dry-run",
  "updated_at": "2026-05-22T11:00:00+00:00"
}
```

Use `BaseAgent.write_state()` from `trading_agents/base_agent.py` — it enforces this.

---

## 3. Paper-Trade Gate — No Exceptions

Before any strategy touches real money:
- Minimum **20 paper trades** completed
- **Profit Factor ≥ 1.3** on those trades
- Both conditions must be met simultaneously

Use `BaseAgent.paper_gate_check(trades, pf)` to evaluate.
The gate is tracked per-strategy in the manifest's `paper_gate:` block.

---

## 4. Global Risk Rules — Cannot Be Overridden

| Rule | Value | Notes |
|------|-------|-------|
| Max daily DD (demo) | **20%** | Halt + Telegram alert at this level |
| Max daily DD (live) | **6%** | Tighten when going live |
| Max risk per trade | **2%** of equity | Hard ceiling |
| Max concurrent trades (system) | **8** | Across all strategies |
| News blackout | **±30 min** around high-impact news | No new entries |

These are enforced by `registry/manifest.py` at load time.
Any manifest that exceeds these will be **rejected** and quarantined.

---

## 5. Per-Strategy Rules — Allowed Overrides

These can be customized per strategy (within global limits):

| Setting | Default | Override Allowed |
|---------|---------|-----------------|
| `risk.pct_per_trade` | 1.0% | Yes, max 2% |
| `risk.daily_dd_pct` | 20% (demo) | Yes, can be lower |
| `risk.max_concurrent` | 2 | Yes, ≤ global max |
| `symbols` | any | Fully custom |
| `timeframes` | any | Fully custom |
| Sessions/kill zones | any | Fully custom |
| SL/TP distances | any | Fully custom |
| Spread limits | any | Fully custom |

---

## 6. Trade Journal — Mandatory

Every trade open/close must call:
```python
from trading_agents.trade_journal import open_trade, close_trade

open_trade(ticket=..., symbol=..., direction=..., entry_price=...,
           sl=..., tp=..., volume=..., source="my_strategy")
close_trade(ticket=..., exit_price=..., pnl=...)
```

Or use `BaseAgent.log_trade()` which wraps this safely.

---

## 7. Logs Isolation

Each agent writes only to its own log directory:
```
logs/{agent_id}/
├── _agent_state.json    ← state heartbeat
├── _agent_daily.json    ← daily rollover data
└── _paper_trades.jsonl  ← trade log (append-only)
```

Do NOT write to another agent's folder.

---

## 8. Backtest Required Before Live

Walk-forward backtest result must be recorded in the manifest or backtest_reports/:
- At minimum: Profit Factor, Win Rate, Max DD on out-of-sample data
- No backtest = stays in paper mode permanently

---

## 9. For AI-Generated Strategies

Claude Code must produce the manifest YAML **before writing any agent code**.
The manifest is the contract. Code that has no manifest will not be deployed.

Checklist for AI-generated strategy:
- [ ] Manifest YAML created in `registry/strategies/`
- [ ] Walk-forward backtest run (not just in-sample)
- [ ] State file heartbeat implemented
- [ ] Paper gate wired (20 trades / PF 1.3)
- [ ] Trade journal calls present
- [ ] Risk limits within global rules
- [ ] Dashboard page exists or Hub card is sufficient

---

## 10. Adding a New Strategy — Checklist

```
1. Drop <name>.yaml into trading_agents/registry/strategies/
2. Write agent in trading_agents/<name>/agent.py
3. Inherit BaseAgent or implement write_state() + paper_gate_check()
4. Run backtest, record results
5. Start in paper mode: python -m trading_agents.<name>.agent --paper
6. Wait for gate: 20 trades + PF ≥ 1.3
7. Promote: change manifest mode: live
8. Dashboard Hub shows it automatically — no manual wiring
```
