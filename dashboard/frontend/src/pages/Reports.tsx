import { useState, useEffect } from 'react'
import clsx from 'clsx'
import { EquityCurveChart } from '../components/charts/EquityCurveChart'
import { DrawdownChart } from '../components/charts/DrawdownChart'
import { MonthlyHeatmap } from '../components/charts/MonthlyHeatmap'
import { Table } from '../components/ui/Table'
import { apiFetch } from '../lib/api'
import { Badge } from '../components/ui/Badge'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'

// ── types ────────────────────────────────────────────────────────────────────
interface BacktestMetrics {
  total_trades?: number
  wins?: number
  losses?: number
  win_rate_pct?: number
  profit_factor?: number
  net_pnl?: number
  total_profit?: number
  total_loss?: number
  max_drawdown_pct?: number
  sharpe_ratio?: number
  final_balance?: number
  [key: string]: number | string | undefined
}

interface BacktestSymbol {
  metrics: BacktestMetrics
  hourly: Array<{ hour: number; trades: number; wr: number }>
}

interface EABacktest {
  ea_key: string
  ea_name: string
  symbols: Record<string, BacktestSymbol>
  summary: {
    total_trades: number
    avg_win_rate: number | null
    avg_profit_factor: number | null
    symbols_tested: string[]
  }
}

interface ReportsData {
  equity_curve: Array<{ t: string; equity: number }>
  drawdown_series: Array<{ t: string; drawdown: number }>
  monthly_returns: Record<string, number>
  symbol_stats: Record<string, { profit_factor: number; win_rate: number; total_patterns: number }>
  ea_backtests: EABacktest[]
}

// ── helpers ──────────────────────────────────────────────────────────────────
function pct(v: number | null | undefined, suffix = '%') {
  if (v == null) return '—'
  return `${v.toFixed(1)}${suffix}`
}
function num(v: number | null | undefined, dp = 2) {
  if (v == null) return '—'
  return v.toFixed(dp)
}
function money(v: number | null | undefined) {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}$${Math.abs(v).toFixed(2)}`
}

const EA_ACCENT: Record<string, string> = {
  MTF_EMA_Scalper:            'before:bg-accent',
  ScalpMaster_HFT:            'before:bg-profit',
  ScalpMaster_HFT_Aggressive: 'before:bg-warning',
  XAUUSD_Gold_Scalper:        'before:bg-yellow-400',
  BTCUSD_Scalper:             'before:bg-purple-400',
}

// ── sub-components ───────────────────────────────────────────────────────────
function HourGrid({ hourly }: { hourly: EABacktest['symbols'][string]['hourly'] }) {
  if (!hourly.length) return null
  return (
    <div>
      <p className="eyebrow mb-2">Hour-by-Hour Win Rate (Server Time)</p>
      <div className="flex flex-wrap gap-1.5">
        {hourly.map(h => (
          <div key={h.hour} className="bg-white/[0.04] ring-1 ring-border rounded-lg px-2 py-1.5 text-center min-w-[56px]">
            <p className="text-text-muted text-[10px]">{String(h.hour).padStart(2,'0')}:00</p>
            <p className={clsx('font-mono font-bold text-xs',
              h.wr >= 60 ? 'text-profit' : h.wr >= 45 ? 'text-warning' : 'text-loss')}>
              {h.wr.toFixed(0)}%
            </p>
            <p className="text-text-muted text-[10px]">{h.trades}T</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function SymbolBacktest({ sym, result }: { sym: string; result: BacktestSymbol }) {
  const [open, setOpen] = useState(false)
  const m = result.metrics
  const pf = m.profit_factor ?? 0
  const wr = m.win_rate_pct ?? 0
  const pnl = m.net_pnl ?? 0
  const dd = m.max_drawdown_pct ?? 0

  return (
    <div className="rounded-xl ring-1 ring-border overflow-hidden bg-white/[0.015]">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.04] transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <Badge variant="neutral">{sym}</Badge>
          <span className="text-text-secondary text-xs">{m.total_trades?.toFixed(0) ?? '—'} trades</span>
        </div>
        <div className="flex items-center gap-4">
          <span className={clsx('font-mono text-xs font-semibold', wr >= 55 ? 'text-profit' : wr >= 45 ? 'text-warning' : 'text-loss')}>
            WR {pct(wr)}
          </span>
          <span className={clsx('font-mono text-xs font-semibold', pf >= 1.5 ? 'text-profit' : pf >= 1 ? 'text-warning' : 'text-loss')}>
            PF {num(pf)}
          </span>
          <span className={clsx('font-mono text-xs font-semibold', pnl >= 0 ? 'text-profit' : 'text-loss')}>
            {money(pnl)}
          </span>
          <span className="text-text-muted text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="px-4 py-4 space-y-4 border-t border-border">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {[
              { label: 'Win Rate',       val: pct(wr),          color: wr >= 55 ? 'text-profit' : wr >= 45 ? 'text-warning' : 'text-loss' },
              { label: 'Profit Factor',  val: num(pf),          color: pf >= 1.5 ? 'text-profit' : pf >= 1 ? 'text-warning' : 'text-loss' },
              { label: 'Net P&L',        val: money(pnl),       color: pnl >= 0 ? 'text-profit' : 'text-loss' },
              { label: 'Max Drawdown',   val: pct(dd),          color: dd <= 10 ? 'text-profit' : dd <= 25 ? 'text-warning' : 'text-loss' },
              { label: 'Total Trades',   val: m.total_trades?.toFixed(0) ?? '—', color: 'text-text-primary' },
              { label: 'Wins / Losses',  val: `${m.wins?.toFixed(0) ?? '—'} / ${m.losses?.toFixed(0) ?? '—'}`, color: 'text-text-primary' },
              { label: 'Sharpe Ratio',   val: num(m.sharpe_ratio),color: (m.sharpe_ratio ?? 0) >= 1 ? 'text-profit' : 'text-warning' },
              { label: 'Final Balance',  val: `$${num(m.final_balance)}`, color: 'text-text-primary' },
            ].map(c => (
              <div key={c.label} className="bg-white/[0.04] ring-1 ring-border rounded-lg p-2.5">
                <p className="eyebrow mb-1">{c.label}</p>
                <p className={clsx('font-mono font-bold text-sm font-tabular', c.color)}>{c.val}</p>
              </div>
            ))}
          </div>

          <HourGrid hourly={result.hourly} />
        </div>
      )}
    </div>
  )
}

function EABacktestCard({ bt }: { bt: EABacktest }) {
  const accent = EA_ACCENT[bt.ea_key] ?? 'before:bg-border'
  const hasData = bt.summary.symbols_tested.length > 0
  const wr = bt.summary.avg_win_rate
  const pf = bt.summary.avg_profit_factor

  return (
    <div
      className={clsx(
        'glass relative overflow-hidden',
        "before:content-[''] before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1 before:z-10",
        accent,
      )}
    >
      <div className="px-5 py-4 border-b border-border flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-text-primary font-semibold text-sm">{bt.ea_name}</p>
          <p className="text-text-muted text-xs mt-0.5 truncate">
            {hasData
              ? `Backtest data: ${bt.summary.symbols_tested.join(' · ')}`
              : 'No backtest data available'}
          </p>
        </div>
        {hasData && (
          <div className="flex items-center gap-6 text-xs shrink-0">
            <div className="text-right">
              <p className="eyebrow mb-1">Avg WR</p>
              <p className={clsx('font-mono font-bold', (wr ?? 0) >= 55 ? 'text-profit' : (wr ?? 0) >= 45 ? 'text-warning' : 'text-loss')}>
                {pct(wr)}
              </p>
            </div>
            <div className="text-right">
              <p className="eyebrow mb-1">Avg PF</p>
              <p className={clsx('font-mono font-bold', (pf ?? 0) >= 1.5 ? 'text-profit' : (pf ?? 0) >= 1 ? 'text-warning' : 'text-loss')}>
                {num(pf)}
              </p>
            </div>
            <div className="text-right">
              <p className="eyebrow mb-1">Trades</p>
              <p className="font-mono font-bold text-text-primary">{bt.summary.total_trades}</p>
            </div>
          </div>
        )}
      </div>

      {hasData ? (
        <div className="p-4 space-y-2.5">
          {Object.entries(bt.symbols).map(([sym, result]) => (
            <SymbolBacktest key={sym} sym={sym} result={result} />
          ))}
        </div>
      ) : (
        <div className="px-5 py-4 text-text-muted text-xs italic">
          Run `python mt5_bridge/backtest.py --symbol BTCUSD` to generate backtest data for this EA.
        </div>
      )}
    </div>
  )
}

// ── main page ────────────────────────────────────────────────────────────────
export function Reports() {
  const [data, setData] = useState<ReportsData | null>(null)

  useEffect(() => {
    const load = () => apiFetch('/api/reports').then(r => r.json()).then(setData).catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  if (!data) return <div className="text-text-muted text-sm">Loading reports…</div>

  const symRows = Object.entries(data.symbol_stats ?? {}).map(([sym, s]) => ({ sym, ...s }))

  return (
    <div className="space-y-4 md:space-y-6">
      <PageHeader
        title="Reports & Analytics"
        subtitle="Live equity curve, drawdown, and EA backtest results"
      />

      {/* Equity + Drawdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Equity Curve" i={0}>
          <EquityCurveChart data={data.equity_curve} />
        </Panel>
        <Panel title="Drawdown" i={1}>
          <DrawdownChart data={data.drawdown_series} />
        </Panel>
      </div>

      {/* Strategy KB symbol stats */}
      {symRows.length > 0 && (
        <Panel title="Symbol Performance (Strategy KB)" i={2}>
          <Table
            columns={[
              { key: 'sym', header: 'Symbol', render: r => <span className="font-semibold">{r.sym}</span> },
              { key: 'pf',  header: 'Avg Profit Factor', align: 'right' as const,
                render: r => <span className={r.profit_factor >= 1.5 ? 'text-profit' : r.profit_factor >= 1 ? 'text-warning' : 'text-loss'}>{r.profit_factor.toFixed(2)}</span> },
              { key: 'wr',  header: 'Avg Win Rate', align: 'right' as const,
                render: r => <span className={r.win_rate >= 60 ? 'text-profit' : 'text-text-primary'}>{r.win_rate.toFixed(1)}%</span> },
              { key: 'pats', header: 'Strategies', render: r => r.total_patterns.toString(), align: 'right' as const },
            ]}
            data={symRows}
            keyFn={r => r.sym}
          />
        </Panel>
      )}

      {/* Monthly returns */}
      {Object.keys(data.monthly_returns ?? {}).length > 0 && (
        <Panel title="Monthly Returns" i={3}>
          <MonthlyHeatmap data={data.monthly_returns} />
        </Panel>
      )}

      {/* EA Backtests */}
      <div className="reveal" style={{ ['--i' as string]: 4 }}>
        <div className="mb-4">
          <h2 className="text-text-primary text-base font-semibold">EA Backtest Results</h2>
          <p className="text-text-muted text-xs mt-1">
            Results from Python MTF backtester — click a symbol row to expand full metrics &amp; hourly win rates.
            Color-coded: <span className="text-profit">green ≥ 55% WR / PF ≥ 1.5</span>,{' '}
            <span className="text-warning">amber ≥ 45%</span>,{' '}
            <span className="text-loss">red below</span>.
          </p>
        </div>
        <div className="space-y-4">
          {(data.ea_backtests ?? []).map(bt => (
            <EABacktestCard key={bt.ea_key} bt={bt} />
          ))}
        </div>
      </div>
    </div>
  )
}
