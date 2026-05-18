import { useState, useEffect } from 'react'
import { StatusDot } from '../components/ui/StatusDot'
import { Badge } from '../components/ui/Badge'
import { Table } from '../components/ui/Table'

interface AgentsData {
  live_trader: {
    running: boolean
    mt5_connected: boolean
    symbols: string[]
    last_signals: Record<string, { direction: string | null; bar_time: string | null }>
    daily_trades: Record<string, number>
    timestamp: string | null
  }
  strategy_researcher: {
    total_strategies: number
    successful: number
    failed: number
    last_updated: string | null
    symbol_stats: Record<string, { successful_patterns: number; failed_patterns: number }>
  }
  performance_optimizer: {
    total_adaptations: number
    last_adaptation: Record<string, unknown> | null
    monthly_cycles: number
  }
  execution_manager: {
    daily_records: number
    last_day: Record<string, unknown> | null
  }
}

function AgentCard({ title, status, items }: { title: string; status: 'running' | 'stopped' | 'offline'; items: [string, string][] }) {
  return (
    <div className="bg-bg-surface border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-text-primary font-semibold text-sm">{title}</h3>
        <StatusDot status={status} />
      </div>
      <dl className="space-y-1">
        {items.map(([k, v]) => (
          <div key={k} className="flex justify-between text-xs">
            <dt className="text-text-secondary">{k}</dt>
            <dd className="text-text-primary font-mono">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function BotsAgents() {
  const [agents, setAgents] = useState<AgentsData | null>(null)

  useEffect(() => {
    const load = () => fetch('/api/agents').then(r => r.json()).then(setAgents).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [])

  if (!agents) return <div className="text-text-muted text-sm">Loading…</div>

  const lt = agents.live_trader
  const sr = agents.strategy_researcher
  const po = agents.performance_optimizer
  const em = agents.execution_manager

  const signalRows = lt.symbols.map(sym => ({
    sym,
    dir: lt.last_signals[sym]?.direction ?? null,
    time: lt.last_signals[sym]?.bar_time ?? null,
    trades: lt.daily_trades[sym] ?? 0,
  }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold mb-1">Bots & Agents</h1>
        <p className="text-text-muted text-sm">Status of all running components</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <AgentCard
          title="Live Trader"
          status={lt.running ? (lt.mt5_connected ? 'running' : 'stopped') : 'offline'}
          items={[
            ['MT5 Connected', lt.mt5_connected ? '✓ Yes' : '✗ No'],
            ['Symbols', lt.symbols.length.toString()],
            ['Last tick', lt.timestamp ? lt.timestamp.slice(11, 19) + ' UTC' : '—'],
          ]}
        />
        <AgentCard
          title="Strategy Researcher"
          status={sr.last_updated ? 'running' : 'offline'}
          items={[
            ['Total tested', sr.total_strategies.toString()],
            ['Successful', sr.successful.toString()],
            ['Failed', sr.failed.toString()],
            ['Symbols tracked', Object.keys(sr.symbol_stats ?? {}).length.toString()],
          ]}
        />
        <AgentCard
          title="Perf Optimizer"
          status={po.total_adaptations > 0 ? 'running' : 'offline'}
          items={[
            ['Total adaptations', po.total_adaptations.toString()],
            ['Monthly cycles', po.monthly_cycles.toString()],
            ['Last adaptation', po.last_adaptation ? '✓ Done' : '—'],
          ]}
        />
        <AgentCard
          title="Execution Manager"
          status={em.daily_records > 0 ? 'running' : 'offline'}
          items={[
            ['Daily records', em.daily_records.toString()],
            ['Last day P&L', em.last_day ? (em.last_day as Record<string, number>).net_pnl_pct?.toFixed(2) + '%' ?? '—' : '—'],
          ]}
        />
      </div>

      {/* Per-symbol signals table */}
      <div className="bg-bg-surface border border-border rounded-lg p-4">
        <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Symbol Signals (Today)</h2>
        <Table
          columns={[
            { key: 'sym', header: 'Symbol', render: r => <span className="font-semibold">{r.sym}</span> },
            { key: 'dir', header: 'Last Signal', render: r => r.dir ? <Badge variant={r.dir === 'BUY' ? 'buy' : 'sell'}>{r.dir}</Badge> : <span className="text-text-muted">—</span> },
            { key: 'time', header: 'Bar Time', render: r => <span className="text-text-muted">{r.time ? r.time.slice(11, 16) + ' UTC' : '—'}</span> },
            { key: 'trades', header: 'Trades Today', render: r => r.trades.toString(), align: 'right' as const },
          ]}
          data={signalRows}
          keyFn={r => r.sym}
          emptyText="No symbols tracked"
        />
      </div>

      {/* Strategy knowledge base */}
      {Object.keys(sr.symbol_stats ?? {}).length > 0 && (
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Strategy Knowledge Base</h2>
          <Table
            columns={[
              { key: 'sym', header: 'Symbol', render: r => <span className="font-semibold">{r.sym}</span> },
              { key: 'ok', header: 'Successful', render: r => <span className="text-profit">{r.ok}</span>, align: 'right' as const },
              { key: 'fail', header: 'Failed', render: r => <span className="text-loss">{r.fail}</span>, align: 'right' as const },
            ]}
            data={Object.entries(sr.symbol_stats).map(([sym, s]) => ({ sym, ok: s.successful_patterns, fail: s.failed_patterns }))}
            keyFn={r => r.sym}
          />
        </div>
      )}
    </div>
  )
}
