import { useState, useEffect } from 'react'
import { Badge } from '../components/ui/Badge'
import { StatusDot } from '../components/ui/StatusDot'
import { Table } from '../components/ui/Table'

interface EAPosition {
  ticket: number; symbol: string; direction: 'BUY' | 'SELL'
  volume: number; entry_price: number; current_price: number
  profit: number; open_time: number; sl: number; tp: number
}

interface EA {
  name: string; magic: number; filename: string; file_exists: boolean
  symbols: string; timeframe: string; strategy: string; sessions: string
  risk_pct: number | null; rr_ratio: number | null; max_dd: number | null; daily_dd: number | null
  is_active: boolean; position_count: number; total_pnl: number
  live_positions: EAPosition[]
  parameters: Record<string, string | number>
  ea_key: string
}

interface EAData {
  eas: EA[]
  summary: { total_eas: number; active_eas: number; total_positions: number; total_pnl: number }
}

const STRATEGY_COLORS: Record<string, string> = {
  'MTF_EMA_Scalper':          'text-accent',
  'ScalpMaster_HFT':          'text-profit',
  'ScalpMaster_HFT_Aggressive': 'text-warning',
  'XAUUSD_Gold_Scalper':      'text-yellow-400',
  'BTCUSD_Scalper':           'text-purple-400',
}

function ParamGrid({ params }: { params: Record<string, string | number> }) {
  const entries = Object.entries(params).filter(([k]) =>
    !['MagicNumber','Slippage','TradeComment','MaxOpenTrades','MaxTradesPerDay','MaxTradesDay'].includes(k)
  ).slice(0, 24)

  if (!entries.length) return <p className="text-text-muted text-xs">No parameters extracted</p>

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between text-xs">
          <span className="text-text-secondary">{k}</span>
          <span className="text-text-primary font-mono">{String(v)}</span>
        </div>
      ))}
    </div>
  )
}

function EACard({ ea }: { ea: EA }) {
  const [expanded, setExpanded] = useState(false)
  const nameColor = STRATEGY_COLORS[ea.ea_key] ?? 'text-text-primary'

  const posColumns = [
    { key: 'dir',     header: 'Dir',    render: (p: EAPosition) => <Badge variant={p.direction === 'BUY' ? 'buy' : 'sell'}>{p.direction}</Badge> },
    { key: 'sym',     header: 'Symbol', render: (p: EAPosition) => <span className="font-semibold">{p.symbol}</span> },
    { key: 'vol',     header: 'Lots',   render: (p: EAPosition) => p.volume.toFixed(2), align: 'right' as const },
    { key: 'entry',   header: 'Entry',  render: (p: EAPosition) => p.entry_price.toFixed(5), align: 'right' as const },
    { key: 'current', header: 'Price',  render: (p: EAPosition) => p.current_price.toFixed(5), align: 'right' as const },
    { key: 'pnl',     header: 'P&L',    align: 'right' as const,
      render: (p: EAPosition) => <span className={p.profit >= 0 ? 'text-profit' : 'text-loss'}>{p.profit >= 0 ? '+' : ''}${p.profit.toFixed(2)}</span> },
  ]

  return (
    <div className="bg-bg-surface border border-border rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          <StatusDot status={ea.is_active ? 'running' : 'offline'} />
          <div>
            <p className={`font-semibold text-sm ${nameColor}`}>{ea.name}</p>
            <p className="text-text-muted text-xs font-mono">{ea.filename} · Magic {ea.magic}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {ea.position_count > 0 && (
            <div className="text-right">
              <p className="text-text-muted text-xs">{ea.position_count} position{ea.position_count !== 1 ? 's' : ''}</p>
              <p className={`font-mono font-bold text-sm ${ea.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                {ea.total_pnl >= 0 ? '+' : ''}${ea.total_pnl.toFixed(2)}
              </p>
            </div>
          )}
          <button onClick={() => setExpanded(e => !e)}
            className="text-text-muted hover:text-text-primary text-xs px-2 py-1 bg-bg-elevated rounded transition-colors">
            {expanded ? '▲ Less' : '▼ More'}
          </button>
        </div>
      </div>

      {/* Always-visible info */}
      <div className="px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <p className="text-text-muted uppercase tracking-widest text-[10px] mb-0.5">Symbols</p>
          <p className="text-text-primary font-mono">{ea.symbols}</p>
        </div>
        <div>
          <p className="text-text-muted uppercase tracking-widest text-[10px] mb-0.5">Timeframe</p>
          <p className="text-text-primary">{ea.timeframe}</p>
        </div>
        <div>
          <p className="text-text-muted uppercase tracking-widest text-[10px] mb-0.5">Risk / RR</p>
          <p className="text-text-primary font-mono">
            {ea.risk_pct != null ? `${ea.risk_pct}%` : '—'} / {ea.rr_ratio != null ? `1:${ea.rr_ratio}` : '—'}
          </p>
        </div>
        <div>
          <p className="text-text-muted uppercase tracking-widest text-[10px] mb-0.5">Max DD</p>
          <p className="text-text-primary font-mono">{ea.max_dd != null ? `${ea.max_dd}%` : '—'}</p>
        </div>
      </div>

      {/* Strategy description */}
      <div className="px-4 pb-3">
        <p className="text-text-secondary text-xs">{ea.strategy}</p>
        <p className="text-text-muted text-xs mt-0.5">Sessions: {ea.sessions}</p>
      </div>

      {/* Expanded: live positions + parameters */}
      {expanded && (
        <div className="border-t border-border">
          {ea.live_positions.length > 0 && (
            <div className="px-4 py-3">
              <p className="text-text-secondary text-xs uppercase tracking-widest mb-2">Live Positions</p>
              <Table columns={posColumns} data={ea.live_positions} keyFn={p => p.ticket} />
            </div>
          )}
          <div className="px-4 py-3 border-t border-border">
            <p className="text-text-secondary text-xs uppercase tracking-widest mb-2">EA Parameters</p>
            <ParamGrid params={ea.parameters} />
          </div>
        </div>
      )}
    </div>
  )
}

export function EAs() {
  const [data, setData] = useState<EAData | null>(null)

  useEffect(() => {
    const load = () => fetch('/api/eas').then(r => r.json()).then(setData).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [])

  if (!data) return <div className="text-text-muted text-sm">Loading EAs…</div>

  const { eas, summary } = data

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold mb-1">Expert Advisors</h1>
        <p className="text-text-muted text-sm">All MQL5 EAs — live positions tracked by magic number</p>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Total EAs',       value: summary.total_eas },
          { label: 'Active EAs',      value: summary.active_eas, color: summary.active_eas > 0 ? 'text-profit' : 'text-text-muted' },
          { label: 'Total Positions', value: summary.total_positions },
          { label: 'Combined P&L',    value: `${summary.total_pnl >= 0 ? '+' : ''}$${summary.total_pnl.toFixed(2)}`,
            color: summary.total_pnl >= 0 ? 'text-profit' : 'text-loss' },
        ].map(c => (
          <div key={c.label} className="bg-bg-surface border border-border rounded-lg p-3">
            <p className="text-text-muted text-xs uppercase tracking-widest">{c.label}</p>
            <p className={`text-2xl font-mono font-bold mt-1 ${c.color ?? 'text-text-primary'}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* EA cards */}
      <div className="space-y-4">
        {eas.map(ea => <EACard key={ea.magic} ea={ea} />)}
      </div>
    </div>
  )
}
