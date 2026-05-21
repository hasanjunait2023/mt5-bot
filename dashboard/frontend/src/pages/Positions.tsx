import { useState, useEffect } from 'react'
import { Table } from '../components/ui/Table'
import { Badge } from '../components/ui/Badge'
import { PriceBar } from '../components/ui/PriceBar'
import { apiFetch } from '../lib/api'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'
import { PnLBarChart } from '../components/charts/PnLBarChart'
import type { Position } from '../types/trading'

export function Positions() {
  const [positions, setPositions] = useState<Position[]>([])

  useEffect(() => {
    const load = () =>
      apiFetch('/api/positions').then(r => r.json()).then(d => setPositions(d.positions ?? []))
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  const totalPnL = positions.reduce((s, p) => s + p.profit, 0)
  const chartData = positions.map(p => ({ label: p.symbol, value: p.profit }))

  const columns = [
    { key: 'dir', header: 'Dir', render: (p: Position) => <Badge variant={p.direction === 'BUY' ? 'buy' : 'sell'}>{p.direction}</Badge> },
    { key: 'sym', header: 'Symbol', render: (p: Position) => <span className="font-semibold">{p.symbol}</span> },
    { key: 'vol', header: 'Lots', render: (p: Position) => p.volume.toFixed(2), align: 'right' as const },
    { key: 'entry', header: 'Entry', render: (p: Position) => p.entry_price.toFixed(5), align: 'right' as const },
    { key: 'current', header: 'Current', render: (p: Position) => p.current_price?.toFixed(5) ?? '—', align: 'right' as const },
    { key: 'pnl', header: 'P&L', align: 'right' as const, render: (p: Position) => (
      <span className={`font-semibold ${p.profit >= 0 ? 'text-profit' : 'text-loss'}`}>
        {p.profit >= 0 ? '+' : ''}${p.profit.toFixed(2)}
      </span>
    )},
    { key: 'bar', header: 'SL ← → TP', render: (p: Position) => (
      <PriceBar pipsToSl={p.pips_to_sl ?? 0} pipsToTp={p.pips_to_tp ?? 0} />
    )},
    { key: 'dur', header: 'Open', render: (p: Position) => {
      const m = p.duration_mins ?? 0
      return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`
    }},
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Live Positions"
        subtitle={`${positions.length} open · updates every 5s`}
        right={
          <div className="text-right">
            <p className="eyebrow mb-1.5">Total P&L</p>
            <p className={`text-2xl font-mono font-bold font-tabular ${totalPnL >= 0 ? 'text-profit' : 'text-loss'}`}>
              {totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}
            </p>
          </div>
        }
      />

      <div className="reveal" style={{ ['--i' as string]: 0 }}>
        <Table
          columns={columns}
          data={positions}
          keyFn={p => p.ticket}
          emptyText="No open positions"
        />
      </div>

      {chartData.length > 0 && (
        <Panel title="P&L by Position" i={1}>
          <PnLBarChart data={chartData} />
        </Panel>
      )}
    </div>
  )
}
