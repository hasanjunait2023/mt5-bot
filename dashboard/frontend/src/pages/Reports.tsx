import { useState, useEffect } from 'react'
import { EquityCurveChart } from '../components/charts/EquityCurveChart'
import { DrawdownChart } from '../components/charts/DrawdownChart'
import { MonthlyHeatmap } from '../components/charts/MonthlyHeatmap'
import { Table } from '../components/ui/Table'
import { Badge } from '../components/ui/Badge'

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

const EA_COLORS: Record<string, string> = {
  MTF_EMA_Scalper:            'border-accent',
  ScalpMaster_HFT:            'border-profit',
  ScalpMaster_HFT_Aggressive: 'border-warning',
  XAUUSD_Gold_Scalper:        'border-yellow-400',
  BTCUSD_Scalper:             'border-purple-400',
}

// ── sub-components ───────────────────────────────────────────────────────────
function HourGrid({ hourly }: { hourly: EABacktest['symbols'][string]['hourly'] }) {
  if (!hourly.length) return null
  return (
    <div>
      <p className="text-text-muted text-[10px] uppercase tracking-widest mb-2">Hour-by-Hour Win Rate (Server Time)</p>
      <div className="flex flex-wrap gap-1">
        {hourly.map(h => (
          <div key={h.hour} className="bg-bg-base rounded px-2 py-1 text-center min-w-[54px]">
            <p className="text-text-muted text-[10px]">{String(h.hour).padStart(2,'0')}:00</p>
            <p className={`font-mono font-bold text-xs ${h.wr >= 60 ? 'text-profit' : h.wr >= 45 ? 'text-warning' : 'text-loss'}`}>
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
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Symbol header row */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-bg-elevated hover:bg-bg-overlay transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <Badge variant="neutral">{sym}</Badge>
          <span className="text-text-secondary text-xs">{m.total_trades?.toFixed(0) ?? '—'} trades</span>
        </div>
        <div className="flex items-center gap-4">
          <span className={`font-mono text-xs font-semibold ${wr >= 55 ? 'text-profit' : wr >= 45 ? 'text-warning' : 'text-loss'}`}>
            WR {pct(wr)}
          </span>
          <span className={`font-mono text-xs font-semibold ${pf >= 1.5 ? 'text-profit' : pf >= 1 ? 'text-warning' : 'text-loss'}`}>
            PF {num(pf)}
          </span>
          <span className={`font-mono text-xs font-semibold ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
            {money(pnl)}
          </span>
          <span className="text-text-muted text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="px-4 py-3 space-y-4">
          {/* Key metrics grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
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
              <div key={c.label} className="bg-bg-elevated rounded p-2">
                <p className="text-text-muted text-[10px] uppercase tracking-widest mb-0.5">{c.label}</p>
                <p className={`font-mono font-bold text-sm ${c.color}`}>{c.val}</p>
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
  const borderColor = EA_COLORS[bt.ea_key] ?? 'border-border'
  const hasData = bt.summary.symbols_tested.length > 0
  const wr = bt.summary.avg_win_rate
  const pf = bt.summary.avg_profit_factor

  return (
    <div className={`bg-bg-surface border-l-4 ${borderColor} border border-border rounded-lg overflow-hidden`}>
      {/* EA header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <p className="text-text-primary font-semibold text-sm">{bt.ea_name}</p>
          <p className="text-text-muted text-xs mt-0.5">
            {hasData
              ? `Backtest data: ${bt.summary.symbols_tested.join(' · ')}`
              : 'No backtest data available'}
          </p>
        </div>
        {hasData && (
          <div className="flex items-center gap-6 text-xs">
            <div className="text-right">
              <p className="text-text-muted text-[10px] uppercase tracking-widest">Avg WR</p>
              <p className={`font-mono font-bold ${(wr ?? 0) >= 55 ? 'text-profit' : (wr ?? 0) >= 45 ? 'text-warning' : 'text-loss'}`}>
                {pct(wr)}
              </p>
            </div>
            <div className="text-right">
              <p className="text-text-muted text-[10px] uppercase tracking-widest">Avg PF</p>
              <p className={`font-mono font-bold ${(pf ?? 0) >= 1.5 ? 'text-profit' : (pf ?? 0) >= 1 ? 'text-warning' : 'text-loss'}`}>
                {num(pf)}
              </p>
            </div>
            <div className="text-right">
              <p className="text-text-muted text-[10px] uppercase tracking-widest">Trades</p>
              <p className="font-mono font-bold text-text-primary">{bt.summary.total_trades}</p>
            </div>
          </div>
        )}
      </div>

      {/* Per-symbol results */}
      {hasData ? (
        <div className="p-3 space-y-2">
          {Object.entries(bt.symbols).map(([sym, result]) => (
            <SymbolBacktest key={sym} sym={sym} result={result} />
          ))}
        </div>
      ) : (
        <div className="px-4 py-4 text-text-muted text-xs italic">
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
    const load = () => fetch('/api/reports').then(r => r.json()).then(setData).catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  if (!data) return <div className="text-text-muted text-sm">Loading reports…</div>

  const symRows = Object.entries(data.symbol_stats ?? {}).map(([sym, s]) => ({ sym, ...s }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold mb-1">Reports & Analytics</h1>
        <p className="text-text-muted text-sm">Live equity curve, drawdown, and EA backtest results</p>
      </div>

      {/* Equity + Drawdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Equity Curve</h2>
          <EquityCurveChart data={data.equity_curve} />
        </div>
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Drawdown</h2>
          <DrawdownChart data={data.drawdown_series} />
        </div>
      </div>

      {/* Strategy KB symbol stats */}
      {symRows.length > 0 && (
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Symbol Performance (Strategy KB)</h2>
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
        </div>
      )}

      {/* Monthly returns */}
      {Object.keys(data.monthly_returns ?? {}).length > 0 && (
        <div className="bg-bg-surface border border-border rounded-lg p-4">
          <h2 className="text-text-secondary text-xs uppercase tracking-widest mb-3">Monthly Returns</h2>
          <MonthlyHeatmap data={data.monthly_returns} />
        </div>
      )}

      {/* EA Backtests */}
      <div>
        <h2 className="text-text-primary text-base font-semibold mb-1">EA Backtest Results</h2>
        <p className="text-text-muted text-xs mb-4">
          Results from Python MTF backtester — click a symbol row to expand full metrics &amp; hourly win rates.
          Color-coded: <span className="text-profit">green ≥ 55% WR / PF ≥ 1.5</span>,{' '}
          <span className="text-warning">amber ≥ 45%</span>,{' '}
          <span className="text-loss">red below</span>.
        </p>
        <div className="space-y-4">
          {(data.ea_backtests ?? []).map(bt => (
            <EABacktestCard key={bt.ea_key} bt={bt} />
          ))}
        </div>
      </div>
    </div>
  )
}
