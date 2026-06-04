import { useState, useEffect } from 'react'
import { apiFetch } from '../lib/api'
import { Badge } from '../components/ui/Badge'
import { Table } from '../components/ui/Table'
import { MetricCard } from '../components/ui/MetricCard'
import type { ReactNode } from 'react'

interface Trade {
  ticket: number
  symbol: string
  direction: string
  entry_price: number
  exit_price: number | null
  sl: number
  tp: number
  volume: number
  source: string
  strategies: string[]
  agent: string
  backend: string
  confluence_score: number
  rationale: string
  open_time: string
  close_time: string | null
  pnl: number | null
  outcome: string
  hold_minutes: number | null
  actual_rr: number | null
}

interface StratStats {
  trades: number
  wins: number
  losses: number
  win_rate_pct: number
  profit_factor: number | null
  net_pnl: number
  avg_hold_minutes: number | null
  expectancy: number
}

interface MistakeAgg {
  loss_count: number
  mistake_counts: Record<string, number>
  top_mistake: string
  suggestion: string
  avg_confluence: number | null
  avg_hold_minutes: number | null
  premature_sl_pct: number
}

interface LossAnalysis {
  total_losses: number
  by_strategy: Record<string, MistakeAgg>
  by_source: Record<string, MistakeAgg>
  by_symbol: Record<string, MistakeAgg>
  trades: Array<{ ticket: number; symbol: string; mistake: string; pnl: number | null; close_time: string | null }>
}

interface Stats {
  total: StratStats
  by_source: Record<string, StratStats>
  by_strategy: Record<string, StratStats>
  by_symbol: Record<string, StratStats>
}

function pnlClass(v: number | null) {
  if (v == null) return 'text-text-muted'
  return v >= 0 ? 'text-profit' : 'text-loss'
}

function fmt(v: number | null, prefix = '$') {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${prefix}${Math.abs(v).toFixed(2)}`
}

function fmtPct(v: number | null) {
  if (v == null) return '—'
  return `${v.toFixed(1)}%`
}

function outcomeVariant(o: string): 'buy' | 'sell' | 'neutral' {
  if (o === 'TP_HIT') return 'buy'
  if (o === 'SL_HIT') return 'sell'
  return 'neutral'
}

function StatsTable({ label, data }: { label: string; data: Record<string, StratStats> }) {
  const rows = Object.entries(data).filter(([, s]) => s.trades > 0)
  if (!rows.length) return null
  return (
    <div className="glass rounded-xl p-4">
      <p className="eyebrow mb-3">{label}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-text-muted text-xs uppercase tracking-wider border-b border-border">
              <th className="text-left pb-2 pr-4">Name</th>
              <th className="text-right pb-2 px-2">Trades</th>
              <th className="text-right pb-2 px-2">WR</th>
              <th className="text-right pb-2 px-2">PF</th>
              <th className="text-right pb-2 px-2">Expectancy</th>
              <th className="text-right pb-2 pl-2">Net PnL</th>
            </tr>
          </thead>
          <tbody>
            {rows.sort(([, a], [, b]) => b.net_pnl - a.net_pnl).map(([name, s]) => (
              <tr key={name} className="border-b border-border/40 hover:bg-white/[0.02]">
                <td className="py-2 pr-4 font-medium text-text-primary truncate max-w-[200px]">{name}</td>
                <td className="py-2 px-2 text-right text-text-secondary">{s.trades}</td>
                <td className="py-2 px-2 text-right">
                  <span className={s.win_rate_pct >= 50 ? 'text-profit' : 'text-loss'}>
                    {fmtPct(s.win_rate_pct)}
                  </span>
                </td>
                <td className="py-2 px-2 text-right">
                  <span className={s.profit_factor != null && s.profit_factor >= 1 ? 'text-profit' : 'text-loss'}>
                    {s.profit_factor != null ? s.profit_factor.toFixed(2) : '—'}
                  </span>
                </td>
                <td className={`py-2 px-2 text-right font-mono ${pnlClass(s.expectancy)}`}>
                  {fmt(s.expectancy)}
                </td>
                <td className={`py-2 pl-2 text-right font-mono font-semibold ${pnlClass(s.net_pnl)}`}>
                  {fmt(s.net_pnl)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const MISTAKE_LABEL: Record<string, string> = {
  QUICK_STOP:     'Quick Stop',
  LOW_CONFLUENCE: 'Low Confluence',
  POOR_RR_SETUP:  'Poor RR Setup',
  DEAD_SESSION:   'Dead Session',
  PREMATURE_SL:   'Premature SL',
  NORMAL_LOSS:    'Normal Loss',
}

const MISTAKE_COLOR: Record<string, string> = {
  QUICK_STOP:     'bg-orange-500/20 text-orange-300',
  LOW_CONFLUENCE: 'bg-yellow-500/20 text-yellow-300',
  POOR_RR_SETUP:  'bg-red-500/20 text-red-300',
  DEAD_SESSION:   'bg-purple-500/20 text-purple-300',
  PREMATURE_SL:   'bg-blue-500/20 text-blue-300',
  NORMAL_LOSS:    'bg-white/10 text-text-muted',
}

function MistakeBadge({ type }: { type: string }) {
  const cls = MISTAKE_COLOR[type] ?? 'bg-white/10 text-text-muted'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>
      {MISTAKE_LABEL[type] ?? type}
    </span>
  )
}

function LossAnalysisSection({ data }: { data: LossAnalysis }) {
  const rows = Object.entries(data.by_strategy).filter(([, v]) => v.loss_count > 0)
  if (!rows.length && data.total_losses === 0) {
    return (
      <div className="glass rounded-xl p-6 text-center text-text-muted text-sm">
        No losing trades yet — nothing to analyze.
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="eyebrow">Loss Pattern Analysis</p>
        <span className="text-xs text-text-muted">{data.total_losses} SL hits analysed · post-close M5 price check included</span>
      </div>

      {/* Per-strategy breakdown */}
      {rows.length > 0 && (
        <div className="glass rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="text-left px-4 py-3">Strategy</th>
                  <th className="text-right px-3 py-3">Losses</th>
                  <th className="text-left px-3 py-3">Top Mistake</th>
                  <th className="text-right px-3 py-3">Premature SL%</th>
                  <th className="text-right px-3 py-3">Avg Conf</th>
                  <th className="text-left px-4 py-3">Suggestion</th>
                </tr>
              </thead>
              <tbody>
                {rows.sort(([, a], [, b]) => b.loss_count - a.loss_count).map(([name, agg]) => (
                  <tr key={name} className="border-b border-border/40 hover:bg-white/[0.02]">
                    <td className="px-4 py-3 font-medium text-text-primary truncate max-w-[160px]">{name}</td>
                    <td className="px-3 py-3 text-right text-loss font-semibold">{agg.loss_count}</td>
                    <td className="px-3 py-3">
                      <MistakeBadge type={agg.top_mistake} />
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-text-secondary">
                      {agg.premature_sl_pct > 0
                        ? <span className={agg.premature_sl_pct > 30 ? 'text-blue-300' : ''}>{agg.premature_sl_pct}%</span>
                        : '—'}
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-text-secondary">
                      {agg.avg_confluence != null ? agg.avg_confluence.toFixed(0) : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted max-w-[280px]">{agg.suggestion}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* By Source */}
      {Object.keys(data.by_source).length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(data.by_source).map(([src, agg]) => (
            <div key={src} className="glass rounded-xl p-4 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-text-primary uppercase tracking-wide">{src}</p>
                <span className="text-loss text-sm font-bold">{agg.loss_count} losses</span>
              </div>
              <div className="flex items-center gap-2">
                <MistakeBadge type={agg.top_mistake} />
                {agg.premature_sl_pct > 0 && (
                  <span className="text-[10px] text-blue-300">{agg.premature_sl_pct}% premature</span>
                )}
              </div>
              <p className="text-[11px] text-text-muted leading-snug">{agg.suggestion}</p>
            </div>
          ))}
        </div>
      )}

      {/* Mistake type legend */}
      <div className="flex flex-wrap gap-2 pt-1">
        {Object.entries(MISTAKE_LABEL).map(([k, v]) => (
          <span key={k} className={`text-[10px] px-2 py-1 rounded ${MISTAKE_COLOR[k]}`}>{v}</span>
        ))}
      </div>
    </div>
  )
}

export function Journal() {
  const [trades, setTrades]       = useState<Trade[]>([])
  const [stats, setStats]         = useState<Stats | null>(null)
  const [analysis, setAnalysis]   = useState<LossAnalysis | null>(null)
  const [filter, setFilter]       = useState({ source: '', symbol: '', outcome: '' })
  const [loading, setLoading]     = useState(true)

  const load = () => {
    const params = new URLSearchParams({ limit: '500' })
    if (filter.source)  params.set('source', filter.source)
    if (filter.symbol)  params.set('symbol', filter.symbol)
    if (filter.outcome) params.set('outcome', filter.outcome)
    Promise.all([
      apiFetch(`/api/journal/trades?${params}`).then(r => r.json()),
      apiFetch('/api/journal/stats').then(r => r.json()),
      apiFetch('/api/journal/analysis').then(r => r.json()),
    ]).then(([t, s, a]) => {
      setTrades(t.trades ?? [])
      setStats(s)
      setAnalysis(a.error ? null : a)
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  useEffect(() => { load() }, [filter])
  useEffect(() => {
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [filter])

  const total = stats?.total
  const openCount = trades.filter(t => t.outcome === 'OPEN').length

  const columns: { key: string; header: string; render: (t: Trade) => ReactNode; align?: 'left' | 'right' | 'center' }[] = [
    {
      key: 'time', header: 'Opened',
      render: (t: Trade) => {
        const d = new Date(t.open_time)
        return <span className="text-text-muted text-xs">{d.toLocaleDateString()} {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      }
    },
    {
      key: 'dir', header: 'Dir',
      render: (t: Trade) => <Badge variant={t.direction === 'BUY' ? 'buy' : 'sell'}>{t.direction}</Badge>
    },
    { key: 'sym', header: 'Symbol', render: (t: Trade) => <span className="font-semibold">{t.symbol}</span> },
    { key: 'src', header: 'Source', render: (t: Trade) => <span className="text-xs text-text-muted">{t.source}</span> },
    {
      key: 'strat', header: 'Strategies',
      render: (t: Trade) => (
        <div className="flex flex-wrap gap-1">
          {(t.strategies ?? []).slice(0, 2).map(s => (
            <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent">{s}</span>
          ))}
          {(t.strategies ?? []).length > 2 && (
            <span className="text-[10px] text-text-muted">+{t.strategies.length - 2}</span>
          )}
        </div>
      )
    },
    { key: 'vol',   header: 'Lots',  render: (t: Trade) => t.volume.toFixed(2), align: 'right' as const },
    { key: 'entry', header: 'Entry', render: (t: Trade) => t.entry_price.toFixed(5), align: 'right' as const },
    {
      key: 'outcome', header: 'Outcome',
      render: (t: Trade) => <Badge variant={outcomeVariant(t.outcome)}>{t.outcome}</Badge>
    },
    {
      key: 'pnl', header: 'PnL', align: 'right' as const,
      render: (t: Trade) => (
        <span className={`font-mono font-semibold ${pnlClass(t.pnl)}`}>
          {t.pnl != null ? fmt(t.pnl) : '—'}
        </span>
      )
    },
    {
      key: 'rr', header: 'RR', align: 'right' as const,
      render: (t: Trade) => (
        <span className="text-text-muted text-xs">
          {t.actual_rr != null ? `1:${t.actual_rr}` : '—'}
        </span>
      )
    },
    {
      key: 'hold', header: 'Hold', align: 'right' as const,
      render: (t: Trade) => {
        const m = t.hold_minutes
        if (m == null) return <span className="text-text-muted">—</span>
        return <span className="text-xs text-text-muted">{m < 60 ? `${m}m` : `${Math.floor(m / 60)}h${Math.round(m % 60)}m`}</span>
      }
    },
  ]

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="eyebrow mb-1">Performance Attribution</p>
          <h1 className="text-2xl font-bold text-text-primary">Trade Journal</h1>
          <p className="text-text-muted text-sm mt-1">
            {loading ? 'Loading…' : `${trades.length} trades · ${openCount} open · auto-refresh 30s`}
          </p>
        </div>
        <button onClick={load} className="px-3 py-1.5 text-sm rounded-lg glass hover:bg-white/[0.06] transition">
          Refresh
        </button>
      </div>

      {/* Summary metric cards */}
      {total && total.trades > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 reveal" style={{ ['--i' as string]: 0 }}>
          <MetricCard label="Total Trades" value={String(total.trades)} tone="neutral" />
          <MetricCard label="Win Rate" value={fmtPct(total.win_rate_pct)}
            tone={total.win_rate_pct >= 50 ? 'profit' : 'loss'} />
          <MetricCard label="Profit Factor"
            value={total.profit_factor != null ? total.profit_factor.toFixed(2) : '—'}
            tone={total.profit_factor != null && total.profit_factor >= 1 ? 'profit' : 'loss'} />
          <MetricCard label="Net PnL" value={fmt(total.net_pnl)}
            tone={total.net_pnl >= 0 ? 'profit' : 'loss'} />
        </div>
      )}

      {/* Per-strategy / per-source stats */}
      {stats && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 reveal" style={{ ['--i' as string]: 1 }}>
          <StatsTable label="By Strategy" data={stats.by_strategy} />
          <StatsTable label="By Source"   data={stats.by_source} />
        </div>
      )}

      {stats && Object.keys(stats.by_symbol ?? {}).length > 0 && (
        <div className="reveal" style={{ ['--i' as string]: 2 }}>
          <StatsTable label="By Symbol" data={stats.by_symbol} />
        </div>
      )}

      {/* Loss analysis */}
      {(analysis || (!loading && stats?.total?.losses !== undefined && stats.total.losses > 0)) && (
        <div className="reveal" style={{ ['--i' as string]: 3 }}>
          {analysis
            ? <LossAnalysisSection data={analysis} />
            : (
              <div className="glass rounded-xl p-4 text-center text-text-muted text-sm">
                Loss analysis unavailable.
              </div>
            )
          }
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 reveal" style={{ ['--i' as string]: 4 }}>
        {[
          { label: 'Source', key: 'source', opts: ['', 'MTF_EMA', 'JTCC', 'CPP'] },
          { label: 'Outcome', key: 'outcome', opts: ['', 'OPEN', 'TP_HIT', 'SL_HIT', 'MANUAL'] },
        ].map(({ label, key, opts }) => (
          <div key={key} className="flex items-center gap-2">
            <span className="text-xs text-text-muted">{label}:</span>
            <select
              className="text-sm bg-bg-surface border border-border rounded px-2 py-1 text-text-primary"
              value={(filter as any)[key]}
              onChange={e => setFilter(f => ({ ...f, [key]: e.target.value }))}
            >
              {opts.map(o => <option key={o} value={o}>{o || 'All'}</option>)}
            </select>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Symbol:</span>
          <input
            className="text-sm bg-bg-surface border border-border rounded px-2 py-1 text-text-primary w-24"
            placeholder="XAUUSD…"
            value={filter.symbol}
            onChange={e => setFilter(f => ({ ...f, symbol: e.target.value.toUpperCase() }))}
          />
        </div>
        {(filter.source || filter.symbol || filter.outcome) && (
          <button
            onClick={() => setFilter({ source: '', symbol: '', outcome: '' })}
            className="text-xs text-text-muted hover:text-text-primary transition"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Trade table */}
      <div className="reveal" style={{ ['--i' as string]: 5 }}>
        <div className="glass rounded-xl overflow-hidden">
          {trades.length === 0 && !loading ? (
            <div className="py-16 text-center text-text-muted">
              <p className="text-lg">No trades recorded yet.</p>
              <p className="text-sm mt-1">Trades appear here automatically when the bot opens positions.</p>
            </div>
          ) : (
            <Table columns={columns} data={trades} keyFn={t => String(t.ticket)} />
          )}
        </div>
      </div>
    </div>
  )
}
