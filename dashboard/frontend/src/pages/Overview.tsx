import { useTrading } from '../contexts/TradingContext'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { Badge } from '../components/ui/Badge'
import { LogLine } from '../components/ui/LogLine'
import { EquityMiniChart } from '../components/charts/EquityMiniChart'
import type { LogEntry } from '../types/trading'

export function Overview() {
  const {
    account, positions, equity_history,
    trader_running, mt5_connected,
    agents, last_signals, daily_trades,
    recent_events,
  } = useTrading()

  const traderStatus = !trader_running ? 'offline' : !mt5_connected ? 'warning' : 'running'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold mb-1">Overview</h1>
        <p className="text-text-muted text-sm">Real-time account and system snapshot</p>
      </div>

      {/* Account KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Balance"
          value={account.balance}
          prefix="$"
          right={<EquityMiniChart data={equity_history} height={40} />}
        />
        <MetricCard
          label="Equity"
          value={account.equity}
          prefix="$"
          delta={account.equity - account.balance}
          positive={account.equity >= account.balance}
          deltaLabel="vs balance"
        />
        <MetricCard
          label="Daily P&L"
          value={account.daily_pnl}
          prefix={account.daily_pnl >= 0 ? '+$' : '-$'}
          positive={account.daily_pnl >= 0}
        />
        <MetricCard
          label="Daily Drawdown"
          value={account.daily_dd_pct}
          suffix="%"
          positive={account.daily_dd_pct < 2}
        />
      </div>

      {/* Secondary row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard label="Total Drawdown" value={account.total_dd_pct} suffix="%" positive={account.total_dd_pct < 10} />
        <MetricCard label="Free Margin" value={account.free_margin} prefix="$" />
        <MetricCard label="Open Positions" value={positions.length} />
      </div>

      {/* Bot Status */}
      <div className="bg-bg-surface border border-border rounded-lg p-4">
        <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">System Status</h2>
        <div className="flex flex-wrap gap-6">
          <div>
            <StatusDot
              status={traderStatus}
              label={trader_running ? `Live Trader (${mt5_connected ? 'MT5 Connected' : 'MT5 Disconnected'})` : 'Live Trader Offline'}
            />
          </div>
          <StatusDot
            status={agents.strategy_researcher.last_updated ? 'running' : 'offline'}
            label={`Strategy Researcher (${agents.strategy_researcher.successful} strategies)`}
          />
          <StatusDot
            status={agents.performance_optimizer.total_adaptations > 0 ? 'running' : 'offline'}
            label={`Optimizer (${agents.performance_optimizer.total_adaptations} adaptations)`}
          />
        </div>
      </div>

      {/* Last signals + daily trades */}
      {Object.keys(last_signals).length > 0 && (
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Last Signals</h2>
          <div className="flex flex-wrap gap-3">
            {Object.entries(last_signals).map(([sym, sig]) => (
              <div key={sym} className="flex items-center gap-2">
                <span className="text-text-secondary text-xs font-mono">{sym}</span>
                {sig.direction ? (
                  <Badge variant={sig.direction === 'BUY' ? 'buy' : 'sell'}>{sig.direction}</Badge>
                ) : (
                  <Badge variant="neutral">—</Badge>
                )}
                {daily_trades[sym] !== undefined && (
                  <span className="text-text-muted text-xs font-mono">{daily_trades[sym]}tx</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Open positions mini table */}
      {positions.length > 0 && (
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Open Positions</h2>
          <div className="space-y-2">
            {positions.map(p => (
              <div key={p.ticket} className="flex items-center justify-between text-sm font-mono py-1 border-b border-border last:border-0">
                <div className="flex items-center gap-2">
                  <Badge variant={p.direction === 'BUY' ? 'buy' : 'sell'}>{p.direction}</Badge>
                  <span className="text-text-primary">{p.symbol}</span>
                  <span className="text-text-muted">{p.volume}L</span>
                </div>
                <span className={p.profit >= 0 ? 'text-profit' : 'text-loss'}>
                  {p.profit >= 0 ? '+' : ''}${p.profit.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent events */}
      {recent_events && recent_events.length > 0 && (
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Recent Events</h2>
          <div className="space-y-0.5">
            {(recent_events as LogEntry[]).slice(-15).map((e, i) => (
              <LogLine key={i} entry={e} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
