import clsx from 'clsx'
import { useTrading } from '../contexts/TradingContext'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { Badge } from '../components/ui/Badge'
import { LogLine } from '../components/ui/LogLine'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'
import { EquityMiniChart } from '../components/charts/EquityMiniChart'
import { EquityCurveChart } from '../components/charts/EquityCurveChart'
import type { LogEntry } from '../types/trading'

export function Overview() {
  const {
    account, positions, equity_history,
    trader_running, mt5_connected,
    agents, last_signals, daily_trades,
    recent_events,
  } = useTrading()

  const traderStatus = !trader_running ? 'offline' : !mt5_connected ? 'warning' : 'running'
  const pnlPos = account.daily_pnl >= 0
  const eqDelta = account.equity - account.balance

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Page header */}
      <PageHeader
        title="Overview"
        subtitle="Real-time account & system snapshot"
        right={
          <div className="hidden sm:flex items-center gap-2 px-3 h-8 rounded-full bg-tint/[0.04] ring-1 ring-border">
            <StatusDot status={traderStatus} />
            <span className="text-text-secondary text-xs font-medium">
              {trader_running ? (mt5_connected ? 'Trading live' : 'Bot up · MT5 down') : 'Bot offline'}
            </span>
          </div>
        }
      />

      {/* Hero financial row — equity is the number a trader watches */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Equity"
          value={account.equity}
          prefix="$"
          hero
          tone="accent"
          delta={eqDelta}
          deltaLabel="vs balance"
          positive={eqDelta >= 0}
        />
        <MetricCard
          label="Balance"
          value={account.balance}
          prefix="$"
          right={<EquityMiniChart data={equity_history} height={40} />}
        />
        <MetricCard
          label="Daily P&L"
          value={Math.abs(account.daily_pnl)}
          prefix={pnlPos ? '+$' : '-$'}
          tone={pnlPos ? 'profit' : 'loss'}
        />
        <MetricCard
          label="Open Positions"
          value={positions.length}
          tone={positions.length > 0 ? 'accent' : 'neutral'}
        />
      </div>

      {/* Equity curve — the trader's headline chart */}
      <Panel
        title="Equity Curve"
        i={0}
        right={
          <span className="text-[11px] font-mono text-text-muted">
            session · {equity_history.length} pts
          </span>
        }
      >
        <EquityCurveChart data={equity_history} />
      </Panel>

      {/* Risk strip — drawdown shown against its limit so risk is felt, not just read */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <RiskCard
          label="Daily Drawdown"
          pct={account.daily_dd_pct}
          limit={3}
          caution={2}
        />
        <RiskCard
          label="Total Drawdown"
          pct={account.total_dd_pct}
          limit={20}
          caution={10}
        />
        <MetricCard label="Free Margin" value={account.free_margin} prefix="$" />
      </div>

      {/* System status */}
      <Panel title="System Status" i={0}>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <StatusDot
            status={traderStatus}
            label={
              trader_running
                ? `Live Trader · ${mt5_connected ? 'MT5 Connected' : 'MT5 Disconnected'}`
                : 'Live Trader Offline'
            }
          />
          <StatusDot
            status={agents.strategy_researcher.last_updated ? 'running' : 'offline'}
            label={`Strategy Researcher · ${agents.strategy_researcher.successful} found`}
          />
          <StatusDot
            status={agents.performance_optimizer.total_adaptations > 0 ? 'running' : 'offline'}
            label={`Optimizer · ${agents.performance_optimizer.total_adaptations} adaptations`}
          />
        </div>
      </Panel>

      {/* Last signals */}
      {Object.keys(last_signals).length > 0 && (
        <Panel title="Last Signals" i={1}>
          <div className="flex flex-wrap gap-2.5">
            {Object.entries(last_signals).map(([sym, sig]) => (
              <div
                key={sym}
                className="flex items-center gap-2 px-3 h-9 rounded-lg bg-tint/[0.03] ring-1 ring-border"
              >
                <span className="text-text-secondary text-xs font-mono">{sym}</span>
                {sig.direction ? (
                  <Badge variant={sig.direction === 'BUY' ? 'buy' : 'sell'}>
                    {sig.direction}
                  </Badge>
                ) : (
                  <Badge variant="neutral">—</Badge>
                )}
                {daily_trades[sym] !== undefined && (
                  <span className="text-text-muted text-xs font-mono">
                    {daily_trades[sym]}tx
                  </span>
                )}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* Open positions */}
      {positions.length > 0 && (
        <Panel title="Open Positions" i={2}>
          <div className="space-y-1">
            {positions.map(p => (
              <div
                key={p.ticket}
                className="flex items-center justify-between text-sm font-mono py-2 px-1 rounded-md hover:bg-tint/[0.03] transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <Badge variant={p.direction === 'BUY' ? 'buy' : 'sell'}>
                    {p.direction}
                  </Badge>
                  <span className="text-text-primary font-semibold">{p.symbol}</span>
                  <span className="text-text-muted">{p.volume} lot</span>
                </div>
                <span
                  className={clsx(
                    'font-tabular font-semibold',
                    p.profit >= 0 ? 'text-profit' : 'text-loss',
                  )}
                >
                  {p.profit >= 0 ? '+' : '−'}${Math.abs(p.profit).toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* Recent events */}
      {recent_events && recent_events.length > 0 && (
        <Panel title="Recent Events" i={3}>
          <div className="space-y-0.5">
            {(recent_events as LogEntry[]).slice(-15).map((e, i) => (
              <LogLine key={i} entry={e} />
            ))}
          </div>
        </Panel>
      )}
    </div>
  )
}

/* Drawdown gauge — proportional fill toward the limit, color escalates with risk */
function RiskCard({
  label, pct, limit, caution,
}: { label: string; pct: number; limit: number; caution: number }) {
  const v = Math.max(0, pct)
  const fill = Math.min(100, (v / limit) * 100)
  const tone = v >= limit ? 'loss' : v >= caution ? 'warning' : 'profit'
  const barColor =
    tone === 'loss' ? 'bg-loss' : tone === 'warning' ? 'bg-warning' : 'bg-profit'
  const txtColor =
    tone === 'loss' ? 'text-loss' : tone === 'warning' ? 'text-warning' : 'text-profit'

  return (
    <div className="glass glass-hover p-5 flex flex-col gap-3 min-w-0">
      <div className="flex items-center justify-between">
        <p className="eyebrow truncate">{label}</p>
        <span className="text-text-muted text-[11px] font-mono">limit {limit}%</span>
      </div>
      <div className="flex items-end gap-2">
        <span className={clsx('font-mono font-bold text-2xl leading-none font-tabular', txtColor)}>
          {v.toFixed(2)}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-tint/[0.06] overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-700', barColor)}
          style={{ width: `${fill}%` }}
        />
      </div>
    </div>
  )
}
