import { useState, useEffect } from 'react'
import { StatusDot } from '../components/ui/StatusDot'
import { Badge } from '../components/ui/Badge'
import { Table } from '../components/ui/Table'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'
import { apiFetch } from '../lib/api'

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

function AgentCard({
  title, status, items, i,
}: {
  title: string
  status: 'running' | 'stopped' | 'offline'
  items: [string, string][]
  i: number
}) {
  return (
    <div
      className="glass glass-hover reveal relative overflow-hidden p-5"
      style={{ ['--i' as string]: i }}
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-sheen/15 to-transparent" />
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-text-primary font-semibold text-sm">{title}</h3>
        <StatusDot status={status} />
      </div>
      <dl className="space-y-2">
        {items.map(([k, v]) => (
          <div key={k} className="flex justify-between items-center text-xs">
            <dt className="text-text-secondary">{k}</dt>
            <dd className="text-text-primary font-mono font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function BotsAgents() {
  const [agents, setAgents] = useState<AgentsData | null>(null)

  useEffect(() => {
    const load = () => apiFetch('/api/agents').then(r => r.json()).then(setAgents).catch(() => {})
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
    <div className="space-y-4 md:space-y-6">
      <PageHeader title="Bots & Agents" subtitle="Status of all running components" />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <AgentCard
          title="Live Trader"
          status={lt.running ? (lt.mt5_connected ? 'running' : 'stopped') : 'offline'}
          i={0}
          items={[
            ['MT5 Connected', lt.mt5_connected ? '✓ Yes' : '✗ No'],
            ['Symbols', lt.symbols.length.toString()],
            ['Last tick', lt.timestamp ? lt.timestamp.slice(11, 19) + ' UTC' : '—'],
          ]}
        />
        <AgentCard
          title="Strategy Researcher"
          status={sr.last_updated ? 'running' : 'offline'}
          i={1}
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
          i={2}
          items={[
            ['Total adaptations', po.total_adaptations.toString()],
            ['Monthly cycles', po.monthly_cycles.toString()],
            ['Last adaptation', po.last_adaptation ? '✓ Done' : '—'],
          ]}
        />
        <AgentCard
          title="Execution Manager"
          status={em.daily_records > 0 ? 'running' : 'offline'}
          i={3}
          items={[
            ['Daily records', em.daily_records.toString()],
            ['Last day P&L', em.last_day ? ((em.last_day as Record<string, number>).net_pnl_pct?.toFixed(2) ?? '—') + '%' : '—'],
          ]}
        />
      </div>

      {/* Per-symbol signals table */}
      <Panel title="Symbol Signals (Today)" i={4}>
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
      </Panel>

      {/* Strategy knowledge base */}
      {Object.keys(sr.symbol_stats ?? {}).length > 0 && (
        <Panel title="Strategy Knowledge Base" i={5}>
          <Table
            columns={[
              { key: 'sym', header: 'Symbol', render: r => <span className="font-semibold">{r.sym}</span> },
              { key: 'ok', header: 'Successful', render: r => <span className="text-profit">{r.ok}</span>, align: 'right' as const },
              { key: 'fail', header: 'Failed', render: r => <span className="text-loss">{r.fail}</span>, align: 'right' as const },
            ]}
            data={Object.entries(sr.symbol_stats).map(([sym, s]) => ({ sym, ok: s.successful_patterns, fail: s.failed_patterns }))}
            keyFn={r => r.sym}
          />
        </Panel>
      )}
    </div>
  )
}
