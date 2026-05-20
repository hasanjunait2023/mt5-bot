import { useState, useEffect } from 'react'
import clsx from 'clsx'
import { Badge } from '../components/ui/Badge'
import { StatusDot } from '../components/ui/StatusDot'
import { Table } from '../components/ui/Table'
import { PageHeader } from '../components/ui/PageHeader'

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
  'MTF_EMA_Scalper':            'text-accent',
  'ScalpMaster_HFT':            'text-profit',
  'ScalpMaster_HFT_Aggressive': 'text-warning',
  'XAUUSD_Gold_Scalper':        'text-yellow-400',
  'BTCUSD_Scalper':             'text-purple-400',
}

function ParamGrid({ params }: { params: Record<string, string | number> }) {
  const entries = Object.entries(params).filter(([k]) =>
    !['MagicNumber','Slippage','TradeComment','MaxOpenTrades','MaxTradesPerDay','MaxTradesDay'].includes(k)
  ).slice(0, 24)

  if (!entries.length) return <p className="text-text-muted text-xs">No parameters extracted</p>

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between text-xs gap-2">
          <span className="text-text-secondary truncate">{k}</span>
          <span className="text-text-primary font-mono shrink-0">{String(v)}</span>
        </div>
      ))}
    </div>
  )
}

function InfoCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="eyebrow mb-1">{label}</p>
      <p className="text-text-primary text-xs font-mono">{children}</p>
    </div>
  )
}

function EACard({ ea, i }: { ea: EA; i: number }) {
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
    <div
      className="glass glass-hover reveal overflow-hidden"
      style={{ ['--i' as string]: i }}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border">
        <div className="flex items-center gap-3 min-w-0">
          <StatusDot status={ea.is_active ? 'running' : 'offline'} />
          <div className="min-w-0">
            <p className={clsx('font-semibold text-sm truncate', nameColor)}>{ea.name}</p>
            <p className="text-text-muted text-xs font-mono truncate">{ea.filename} · Magic {ea.magic}</p>
          </div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          {ea.position_count > 0 && (
            <div className="text-right">
              <p className="text-text-muted text-xs">{ea.position_count} position{ea.position_count !== 1 ? 's' : ''}</p>
              <p className={clsx('font-mono font-bold text-sm font-tabular', ea.total_pnl >= 0 ? 'text-profit' : 'text-loss')}>
                {ea.total_pnl >= 0 ? '+' : ''}${ea.total_pnl.toFixed(2)}
              </p>
            </div>
          )}
          <button onClick={() => setExpanded(e => !e)}
            className="text-text-secondary hover:text-text-primary text-xs px-3 h-8 bg-white/[0.04] ring-1 ring-border rounded-lg transition-colors">
            {expanded ? '▲ Less' : '▼ More'}
          </button>
        </div>
      </div>

      {/* Always-visible info */}
      <div className="px-5 py-4 grid grid-cols-2 md:grid-cols-4 gap-4">
        <InfoCell label="Symbols">{ea.symbols}</InfoCell>
        <InfoCell label="Timeframe">{ea.timeframe}</InfoCell>
        <InfoCell label="Risk / RR">
          {ea.risk_pct != null ? `${ea.risk_pct}%` : '—'} / {ea.rr_ratio != null ? `1:${ea.rr_ratio}` : '—'}
        </InfoCell>
        <InfoCell label="Max DD">{ea.max_dd != null ? `${ea.max_dd}%` : '—'}</InfoCell>
      </div>

      {/* Strategy description */}
      <div className="px-5 pb-4">
        <p className="text-text-secondary text-xs">{ea.strategy}</p>
        <p className="text-text-muted text-xs mt-1">Sessions: {ea.sessions}</p>
      </div>

      {/* Expanded: live positions + parameters */}
      {expanded && (
        <div className="border-t border-border">
          {ea.live_positions.length > 0 && (
            <div className="px-5 py-4">
              <p className="eyebrow mb-3">Live Positions</p>
              <Table columns={posColumns} data={ea.live_positions} keyFn={p => p.ticket} />
            </div>
          )}
          <div className="px-5 py-4 border-t border-border">
            <p className="eyebrow mb-3">EA Parameters</p>
            <ParamGrid params={ea.parameters} />
          </div>
        </div>
      )}
    </div>
  )
}

// ── ICT Walk-Forward types ─────────────────────────────────────────
interface ICTPeriod {
  pf: number; dd: number; wr: number; trades: number; ret_pct: number
}
interface ICTSymbol {
  in_sample: ICTPeriod; out_of_sample: ICTPeriod
  full_period?: ICTPeriod
  degradation_pct: number; passed: boolean
  verdict?: 'PASS' | 'PENDING' | 'FAIL'
  note?: string
}
interface ICTResults {
  available: boolean; message?: string
  generated_at?: string; in_sample_end?: string
  symbols: Record<string, ICTSymbol>; promoted: string[]
}

function ICTWalkForward({ data }: { data: ICTResults | null }) {
  if (!data) return null

  if (!data.available) {
    return (
      <div className="space-y-3">
        <p className="eyebrow">ICT 2022 Walk-Forward Validation</p>
        <div className="glass p-5 text-sm text-text-muted">
          {data.message ?? 'No ICT results yet. Run: python backtest_runner.py --ict-wf'}
        </div>
      </div>
    )
  }

  const symbols = Object.entries(data.symbols)
  const splitDate = data.in_sample_end ?? '2025-01-01'

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <p className="eyebrow">ICT 2022 Mentorship Model — Walk-Forward Validation</p>
        <span className="text-xs text-text-muted font-mono">
          split {splitDate}
          {data.generated_at && ` · run ${new Date(data.generated_at).toLocaleDateString()}`}
        </span>
      </div>

      {/* Promoted banner */}
      {data.promoted.length > 0 && (
        <div className="glass p-3 flex items-center gap-3 border border-profit/30 rounded-xl">
          <span className="text-profit text-lg">✓</span>
          <p className="text-sm text-profit font-semibold">
            Promoted to ready_ea: {data.promoted.join(', ')}
          </p>
        </div>
      )}

      {/* Per-symbol cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {symbols.map(([sym, r], i) => {
          const pass = r.passed
          return (
            <div
              key={sym}
              className={clsx(
                'glass reveal relative overflow-hidden p-5 space-y-4',
                pass ? 'ring-1 ring-profit/30' : 'ring-1 ring-loss/20'
              )}
              style={{ ['--i' as string]: i + 6 }}
            >
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />

              {/* Symbol header */}
              <div className="flex items-center justify-between">
                <p className="font-bold text-base text-text-primary">{sym}</p>
                {(() => {
                  const v = r.verdict ?? (pass ? 'PASS' : 'FAIL')
                  const cls = v === 'PASS'
                    ? 'bg-profit/20 text-profit'
                    : v === 'PENDING'
                      ? 'bg-warning/20 text-warning'
                      : 'bg-loss/20 text-loss'
                  return (
                    <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-full', cls)}>
                      {v}
                    </span>
                  )
                })()}
              </div>

              {/* Degradation */}
              <div>
                <p className="eyebrow mb-1">OOS Degradation</p>
                <p className={clsx(
                  'text-2xl font-mono font-bold font-tabular',
                  r.degradation_pct >= 80 ? 'text-profit' : 'text-warning'
                )}>
                  {r.degradation_pct.toFixed(0)}%
                </p>
                <p className="text-text-muted text-xs">(need ≥ 80% to pass)</p>
              </div>

              {/* In-sample vs OOS table */}
              <div className="grid grid-cols-3 gap-1 text-xs">
                <span className="text-text-muted" />
                <span className="text-text-muted text-center font-semibold">In-Sample</span>
                <span className="text-text-muted text-center font-semibold">OOS</span>

                {[
                  { label: 'PF',      is: r.in_sample.pf.toFixed(2),     oos: r.out_of_sample.pf.toFixed(2),
                    oosClass: r.out_of_sample.pf >= 1.3 ? 'text-profit' : 'text-loss' },
                  { label: 'WR',      is: `${r.in_sample.wr}%`,          oos: `${r.out_of_sample.wr}%`,
                    oosClass: r.out_of_sample.wr >= 40 ? 'text-profit' : 'text-loss' },
                  { label: 'DD',      is: `${r.in_sample.dd}%`,          oos: `${r.out_of_sample.dd}%`,
                    oosClass: r.out_of_sample.dd <= 12 ? 'text-profit' : 'text-loss' },
                  { label: 'Trades',  is: r.in_sample.trades,            oos: r.out_of_sample.trades,
                    oosClass: 'text-text-primary' },
                  { label: 'Return',  is: `${r.in_sample.ret_pct >= 0 ? '+' : ''}${r.in_sample.ret_pct}%`,
                    oos: `${r.out_of_sample.ret_pct >= 0 ? '+' : ''}${r.out_of_sample.ret_pct}%`,
                    oosClass: r.out_of_sample.ret_pct >= 0 ? 'text-profit' : 'text-loss' },
                ].map(row => (
                  <>
                    <span key={row.label + 'l'} className="text-text-secondary py-0.5">{row.label}</span>
                    <span key={row.label + 'i'} className="text-text-primary font-mono text-center py-0.5">{row.is}</span>
                    <span key={row.label + 'o'} className={clsx('font-mono font-bold text-center py-0.5', row.oosClass)}>{row.oos}</span>
                  </>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {symbols.some(([, r]) => r.note) && (
        <div className="space-y-1">
          {symbols.filter(([, r]) => r.note).map(([sym, r]) => (
            <p key={sym} className="text-xs text-text-muted">
              <span className="text-text-secondary font-semibold">{sym}:</span> {r.note}
            </p>
          ))}
        </div>
      )}
      <p className="text-xs text-text-muted">
        Walk-forward: params locked from full-period optimization, validated blind on unseen OOS data.
        Real-cost applied. Thresholds: OOS PF ≥ 1.3, DD ≤ 12%, IS-to-OOS degradation ≤ 20%.
      </p>
    </div>
  )
}

interface EAPerfRow {
  magic: number; name: string; group: string
  trades: number; win_rate: number; profit_factor: number
  net_pnl: number; avg_win: number; avg_loss: number
  max_drawdown: number; last_close?: string
}
interface EAPerf {
  available: boolean; message?: string
  generated_at?: string; lookback_days?: number
  account?: { login?: number; server?: string; balance?: number; equity?: number; currency?: string }
  summary?: { total_eas?: number; total_trades?: number; total_net_pnl?: number }
  eas: EAPerfRow[]
  note?: string
}

function RealizedPerformance({ perf }: { perf: EAPerf | null }) {
  if (!perf) return null
  const rows = (perf.eas ?? []).filter(e => e.trades > 0)
  const acct = perf.account ?? {}
  const sum = perf.summary ?? {}

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <p className="eyebrow">Realized Performance — real fills incl. spread/commission</p>
        {perf.generated_at && (
          <span className="text-xs text-text-muted font-mono">
            updated {new Date(perf.generated_at).toLocaleString()}
          </span>
        )}
      </div>

      {!perf.available && (
        <div className="glass p-5 text-sm text-text-muted">
          {perf.message ?? 'No realized performance report yet.'}
        </div>
      )}

      {perf.available && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: `Account ${acct.login ?? ''}`, value: acct.server ?? '—', mono: false },
              { label: 'Balance', value: `$${(acct.balance ?? 0).toFixed(2)}` },
              { label: 'Equity', value: `$${(acct.equity ?? 0).toFixed(2)}` },
              { label: `Net P&L (${perf.lookback_days ?? 30}d)`,
                value: `${(sum.total_net_pnl ?? 0) >= 0 ? '+' : ''}$${(sum.total_net_pnl ?? 0).toFixed(2)}`,
                color: (sum.total_net_pnl ?? 0) >= 0 ? 'text-profit' : 'text-loss' },
            ].map((c, idx) => (
              <div key={c.label} className="glass reveal relative overflow-hidden p-5"
                   style={{ ['--i' as string]: idx }}>
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
                <p className="eyebrow">{c.label}</p>
                <p className={clsx('text-xl font-bold mt-2',
                  c.mono === false ? 'text-text-primary' : 'font-mono font-tabular',
                  c.color ?? 'text-text-primary')}>{c.value}</p>
              </div>
            ))}
          </div>

          <Table<EAPerfRow>
            columns={[
              { key: 'name', header: 'EA', render: r => (
                <span className="font-medium text-text-primary">{r.name}
                  <span className="text-text-muted text-xs ml-2">{r.group}</span></span>) },
              { key: 'trades', header: 'Trades', align: 'right', render: r => r.trades },
              { key: 'wr', header: 'Win %', align: 'right',
                render: r => `${r.win_rate.toFixed(1)}%` },
              { key: 'pf', header: 'PF', align: 'right',
                render: r => <span className={r.profit_factor >= 1 ? 'text-profit' : 'text-loss'}>
                  {r.profit_factor.toFixed(2)}</span> },
              { key: 'net', header: 'Net $', align: 'right',
                render: r => <span className={r.net_pnl >= 0 ? 'text-profit' : 'text-loss'}>
                  {r.net_pnl >= 0 ? '+' : ''}{r.net_pnl.toFixed(2)}</span> },
              { key: 'aw', header: 'Avg W', align: 'right', render: r => r.avg_win.toFixed(2) },
              { key: 'al', header: 'Avg L', align: 'right', render: r => r.avg_loss.toFixed(2) },
              { key: 'dd', header: 'Max DD $', align: 'right',
                render: r => <span className="text-loss">{r.max_drawdown.toFixed(2)}</span> },
            ]}
            data={rows}
            keyFn={r => r.magic}
            emptyText="No closed trades yet — waiting for first fills."
          />

          <p className="text-xs text-text-muted">
            ⚠️ Early sample = not a verdict. Need ~20–50+ trades per EA before
            judging. Backtest excluded spread/commission; these numbers are real.
          </p>
        </>
      )}
    </div>
  )
}

export function EAs() {
  const [data, setData] = useState<EAData | null>(null)
  const [perf, setPerf] = useState<EAPerf | null>(null)
  const [ict,  setIct]  = useState<ICTResults | null>(null)

  useEffect(() => {
    const load = () => {
      fetch('/api/eas').then(r => r.json()).then(setData).catch(() => {})
      fetch('/api/ea-performance').then(r => r.json()).then(setPerf).catch(() => {})
      fetch('/api/ict/results').then(r => r.json()).then(setIct).catch(() => {})
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  if (!data) return <div className="text-text-muted text-sm">Loading EAs…</div>

  const { eas, summary } = data

  return (
    <div className="space-y-6">
      <PageHeader
        title="Expert Advisors"
        subtitle="All MQL5 EAs — live positions tracked by magic number"
      />

      {/* Summary bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Total EAs',       value: summary.total_eas },
          { label: 'Active EAs',      value: summary.active_eas, color: summary.active_eas > 0 ? 'text-profit' : 'text-text-muted' },
          { label: 'Total Positions', value: summary.total_positions },
          { label: 'Combined P&L',    value: `${summary.total_pnl >= 0 ? '+' : ''}$${summary.total_pnl.toFixed(2)}`,
            color: summary.total_pnl >= 0 ? 'text-profit' : 'text-loss' },
        ].map((c, idx) => (
          <div
            key={c.label}
            className="glass glass-hover reveal relative overflow-hidden p-5"
            style={{ ['--i' as string]: idx }}
          >
            <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
            <p className="eyebrow">{c.label}</p>
            <p className={clsx('text-2xl font-mono font-bold mt-2 font-tabular', c.color ?? 'text-text-primary')}>
              {c.value}
            </p>
          </div>
        ))}
      </div>

      {/* ICT 2022 Walk-Forward Validation */}
      <ICTWalkForward data={ict} />

      {/* Realized performance (closed trades, real spread-inclusive) */}
      <RealizedPerformance perf={perf} />

      {/* EA cards */}
      <div className="space-y-4">
        {eas.map((ea, idx) => <EACard key={ea.magic} ea={ea} i={idx + 4} />)}
      </div>
    </div>
  )
}
