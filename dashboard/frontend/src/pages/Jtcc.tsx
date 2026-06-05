import { useEffect, useState } from 'react'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { Badge } from '../components/ui/Badge'
import { Panel } from '../components/ui/Panel'

interface ConfluenceData {
  buy_count: number
  sell_count: number
  buy_strategies: string[]
  sell_strategies: string[]
  session: string | null
  trend: string | null
  news_blocked: boolean
  updated_at: string
}

interface JtccState {
  status: string
  dry_run: boolean
  started_at: string | null
  symbols: string[]
  daily_api_calls: number
  api_calls_limit: number
  confluence: Record<string, ConfluenceData>
  last_signals: any[]
  performance: { total_trades: number; wins: number; losses: number; total_pnl: number; win_rate_pct: number }
  strategy_stats: Record<string, { trades: number; wins: number; pnl: number }>
}

interface EquityPoint { ts: string; pnl: number; equity: number; drawdown: number; symbol: string }
interface GuardianState { issues_count: number; issues: { severity: string; msg: string }[]; checked_at: string | null }
interface LatencyState { updated_at: number | null; stats: Record<string, { p50_ms: number; p95_ms: number; calls: number; error_rate_pct: number }> }
interface CoachState { last_run: string | null; proposal: any; analysis: any[] }
interface HeatmapState { matrix: Record<string, Record<string, { trades: number; wins: number; pnl: number }>> }

const EMPTY_STATE: JtccState = {
  status: 'offline', dry_run: false, started_at: null, symbols: [],
  daily_api_calls: 0, api_calls_limit: 15, confluence: {}, last_signals: [],
  performance: { total_trades: 0, wins: 0, losses: 0, total_pnl: 0, win_rate_pct: 0 },
  strategy_stats: {},
}

function ConfluenceBar({ symbol, data }: { symbol: string; data: ConfluenceData }) {
  const total = data.buy_count + data.sell_count
  const buyPct = total > 0 ? (data.buy_count / total) * 100 : 50
  const sellPct = 100 - buyPct
  const dominant = data.buy_count > data.sell_count ? 'BUY' : data.sell_count > data.buy_count ? 'SELL' : 'NEUTRAL'

  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-text-primary font-semibold tracking-wide">{symbol}</span>
          {data.trend && (
            <Badge tone={data.trend === 'BULLISH' ? 'green' : data.trend === 'BEARISH' ? 'red' : 'gray'}>{data.trend}</Badge>
          )}
          {data.news_blocked && <Badge tone="orange">NEWS BLOCK</Badge>}
        </div>
        {data.session && <span className="font-mono text-xs text-text-secondary">{data.session.toUpperCase()}</span>}
      </div>
      <div className="relative h-3 rounded-full overflow-hidden bg-tint/[0.05]">
        <div className="absolute left-0 top-0 h-full bg-emerald-500/60 transition-all duration-500" style={{ width: `${buyPct}%` }} />
        <div className="absolute right-0 top-0 h-full bg-red-500/60 transition-all duration-500" style={{ width: `${sellPct}%` }} />
      </div>
      <div className="flex justify-between text-xs">
        <div className="text-emerald-400 font-medium">{data.buy_count} BUY</div>
        <Badge tone={dominant === 'BUY' ? 'green' : dominant === 'SELL' ? 'red' : 'gray'}>{total} total</Badge>
        <div className="text-red-400 font-medium">{data.sell_count} SELL</div>
      </div>
    </div>
  )
}

function EquitySparkline({ points }: { points: EquityPoint[] }) {
  if (!points.length) return <div className="text-text-tertiary text-sm">No trades closed yet.</div>
  const equities = points.map(p => p.equity)
  const min = Math.min(0, ...equities)
  const max = Math.max(0, ...equities)
  const range = max - min || 1
  const width = 600, height = 120
  const points_str = points.map((p, i) => {
    const x = (i / Math.max(points.length - 1, 1)) * width
    const y = height - ((p.equity - min) / range) * height
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const last = points[points.length - 1]
  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-32">
        <line x1="0" y1={height - ((0 - min) / range) * height} x2={width} y2={height - ((0 - min) / range) * height}
              stroke="rgba(120,130,150,0.20)" strokeDasharray="3 3" />
        <polyline points={points_str} fill="none" stroke={last.equity >= 0 ? '#10b981' : '#ef4444'} strokeWidth="2" />
      </svg>
      <div className="flex justify-between text-xs text-text-secondary">
        <span>{points.length} trades</span>
        <span className={`font-mono ${last.equity >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          Equity: {last.equity >= 0 ? '+' : ''}{last.equity.toFixed(2)}
        </span>
        <span className="text-yellow-400 font-mono">Max DD: -{Math.max(...points.map(p => p.drawdown)).toFixed(2)}</span>
      </div>
    </div>
  )
}

function StrategyHeatmap({ matrix }: { matrix: HeatmapState['matrix'] }) {
  const strategies = Object.keys(matrix)
  const symbols = Array.from(new Set(strategies.flatMap(s => Object.keys(matrix[s])))).sort()
  if (!strategies.length) return <div className="text-text-tertiary text-sm">No closed trades yet.</div>

  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="text-left p-2 text-text-secondary">Strategy</th>
            {symbols.map(sym => <th key={sym} className="p-2 text-text-secondary">{sym}</th>)}
          </tr>
        </thead>
        <tbody>
          {strategies.map(strat => (
            <tr key={strat}>
              <td className="p-2 text-text-primary font-medium">{strat}</td>
              {symbols.map(sym => {
                const cell = matrix[strat]?.[sym]
                if (!cell) return <td key={sym} className="p-2 text-text-tertiary">—</td>
                const pnl = cell.pnl
                const intensity = Math.min(1, Math.abs(pnl) / 100)
                const bg = pnl > 0
                  ? `rgba(16, 185, 129, ${0.15 + intensity * 0.5})`
                  : pnl < 0
                    ? `rgba(239, 68, 68, ${0.15 + intensity * 0.5})`
                    : 'rgba(120,130,150,0.08)'
                return (
                  <td key={sym} className="p-2 text-center rounded" style={{ background: bg }}>
                    <div className={`font-mono ${pnl >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}
                    </div>
                    <div className="text-text-tertiary text-[10px]">{cell.trades}t</div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LatencyTable({ stats }: { stats: LatencyState['stats'] }) {
  const entries = Object.entries(stats)
  if (!entries.length) return <div className="text-text-tertiary text-sm">No latency data yet.</div>
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-text-secondary text-xs border-b border-line/40">
          <th className="text-left py-2">Component</th>
          <th className="text-right py-2 px-2">Calls</th>
          <th className="text-right py-2 px-2">p50</th>
          <th className="text-right py-2 px-2">p95</th>
          <th className="text-right py-2 px-2">Errors</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([label, s]) => (
          <tr key={label} className="border-b border-line/20 last:border-0">
            <td className="py-2 text-text-primary font-mono text-xs">{label}</td>
            <td className="py-2 px-2 text-right text-text-secondary">{s.calls}</td>
            <td className="py-2 px-2 text-right font-mono text-text-secondary">{s.p50_ms}ms</td>
            <td className="py-2 px-2 text-right font-mono text-text-secondary">{s.p95_ms}ms</td>
            <td className="py-2 px-2 text-right">
              <Badge tone={s.error_rate_pct > 30 ? 'red' : s.error_rate_pct > 10 ? 'yellow' : 'green'}>
                {s.error_rate_pct}%
              </Badge>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Jtcc() {
  const [state, setState] = useState<JtccState>(EMPTY_STATE)
  const [equity, setEquity] = useState<EquityPoint[]>([])
  const [guardian, setGuardian] = useState<GuardianState>({ issues_count: 0, issues: [], checked_at: null })
  const [latency, setLatency] = useState<LatencyState>({ updated_at: null, stats: {} })
  const [heatmap, setHeatmap] = useState<HeatmapState>({ matrix: {} })
  const [coach, setCoach] = useState<CoachState>({ last_run: null, proposal: null, analysis: [] })

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [s, e, g, l, h, c] = await Promise.all([
          fetch('/api/jtcc').then(r => r.json()).catch(() => EMPTY_STATE),
          fetch('/api/jtcc/equity').then(r => r.json()).catch(() => ({ points: [] })),
          fetch('/api/jtcc/guardian').then(r => r.json()).catch(() => ({ issues_count: 0, issues: [] })),
          fetch('/api/jtcc/latency').then(r => r.json()).catch(() => ({ stats: {} })),
          fetch('/api/jtcc/heatmap').then(r => r.json()).catch(() => ({ matrix: {} })),
          fetch('/api/jtcc/coach').then(r => r.json()).catch(() => ({ proposal: null, analysis: [] })),
        ])
        setState(s); setEquity(e.points || []); setGuardian(g); setLatency(l); setHeatmap(h); setCoach(c)
      } catch { /* offline */ }
    }
    fetchAll()
    const interval = setInterval(fetchAll, 3000)
    return () => clearInterval(interval)
  }, [])

  const isRunning = state.status === 'running'
  const isOffline = state.status === 'offline'
  const apiUsagePct = state.api_calls_limit > 0 ? (state.daily_api_calls / state.api_calls_limit) * 100 : 0
  const confluenceSymbols = Object.entries(state.confluence)
  const criticalIssues = guardian.issues.filter(i => i.severity === 'CRITICAL').length

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="eyebrow">JTCC</p>
          <h1 className="text-text-primary text-2xl font-bold tracking-tight">Junait Trading Command Center</h1>
          <p className="text-text-secondary text-sm mt-0.5">
            4-layer signal engine · Guardian · Coach · Daily Digest
          </p>
        </div>
        <div className="flex gap-2">
          {criticalIssues > 0 && <Badge tone="red">{criticalIssues} CRITICAL</Badge>}
          {guardian.issues_count > 0 && criticalIssues === 0 && <Badge tone="orange">{guardian.issues_count} issues</Badge>}
          <div className="flex items-center gap-2 px-3 h-8 rounded-full bg-tint/[0.04] ring-1 ring-border">
            <StatusDot status={isRunning ? 'running' : isOffline ? 'offline' : 'warning'} />
            <span className="text-text-secondary text-xs font-medium">
              {isOffline ? 'Offline' : isRunning ? `Running${state.dry_run ? ' (dry)' : ''}` : state.status}
            </span>
          </div>
        </div>
      </div>

      {/* Guardian issues alert */}
      {guardian.issues_count > 0 && (
        <Panel title={`Guardian Alerts (${guardian.issues_count})`}>
          <div className="space-y-2">
            {guardian.issues.slice(0, 5).map((i, idx) => (
              <div key={idx} className="flex items-start gap-3">
                <Badge tone={i.severity === 'CRITICAL' ? 'red' : i.severity === 'ERROR' ? 'orange' : 'yellow'}>
                  {i.severity}
                </Badge>
                <span className="text-text-secondary text-sm flex-1">{i.msg}</span>
              </div>
            ))}
            {guardian.checked_at && (
              <p className="text-text-tertiary text-xs">
                Last check: {new Date(guardian.checked_at).toLocaleString()}
              </p>
            )}
          </div>
        </Panel>
      )}

      {/* Coach proposal alert */}
      {coach.proposal && (
        <Panel title="JTCC Coach Proposal">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge tone="blue">{coach.proposal.type}</Badge>
              <span className="text-text-primary font-medium">{coach.proposal.strategy}</span>
            </div>
            <div className="text-sm text-text-secondary">{coach.proposal.reason}</div>
            <div className="text-xs text-text-tertiary">
              Action: {coach.proposal.action} | Impact: {coach.proposal.expected_impact}
            </div>
          </div>
        </Panel>
      )}

      {/* Top metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Claude API Calls" value={`${state.daily_api_calls} / ${state.api_calls_limit}`}
          sub={`${(100 - apiUsagePct).toFixed(0)}% budget remaining`}
          tone={apiUsagePct > 80 ? 'red' : apiUsagePct > 50 ? 'yellow' : 'green'} hero />
        <MetricCard label="Total P&L" value={`${state.performance.total_pnl >= 0 ? '+' : ''}${state.performance.total_pnl.toFixed(2)}`}
          sub={`${state.performance.wins}W · ${state.performance.losses}L · ${state.performance.win_rate_pct}% WR`}
          tone={state.performance.total_pnl >= 0 ? 'green' : 'red'} />
        <MetricCard label="Guardian Status" value={guardian.issues_count === 0 ? 'Healthy' : `${guardian.issues_count} alerts`}
          sub={guardian.checked_at ? `Checked ${new Date(guardian.checked_at).toLocaleTimeString()}` : 'No check yet'}
          tone={criticalIssues > 0 ? 'red' : guardian.issues_count > 0 ? 'yellow' : 'green'} />
        <MetricCard label="Active Symbols" value={state.symbols.length || '—'}
          sub={state.symbols.slice(0, 3).join(' · ') || 'Offline'} tone="gray" />
      </div>

      {/* Equity curve */}
      <Panel title="JTCC Equity Curve">
        <EquitySparkline points={equity} />
      </Panel>

      {/* Confluence */}
      <div>
        <h2 className="text-text-primary font-semibold mb-3">Live Strategy Confluence</h2>
        {confluenceSymbols.length === 0 ? (
          <div className="glass rounded-xl p-8 text-center text-text-secondary">
            {isOffline ? 'JTCC offline. Run: .\\start_jtcc_agents.ps1' : 'Waiting for first bar close…'}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {confluenceSymbols.map(([s, d]) => <ConfluenceBar key={s} symbol={s} data={d} />)}
          </div>
        )}
      </div>

      {/* Heatmap */}
      {Object.keys(heatmap.matrix).length > 0 && (
        <Panel title="Strategy × Symbol Heatmap (lifetime P&L)">
          <StrategyHeatmap matrix={heatmap.matrix} />
        </Panel>
      )}

      {/* Latency */}
      {Object.keys(latency.stats).length > 0 && (
        <Panel title="Pipeline Latency">
          <LatencyTable stats={latency.stats} />
        </Panel>
      )}

      {/* API usage bar */}
      <Panel title="Daily Claude API Budget (max 15 calls)">
        <div className="space-y-2">
          <div className="flex justify-between text-xs text-text-secondary">
            <span>{state.daily_api_calls} used</span>
            <span>{state.api_calls_limit - state.daily_api_calls} remaining</span>
          </div>
          <div className="h-2 rounded-full bg-tint/[0.05] overflow-hidden">
            <div className={`h-full rounded-full transition-all duration-500 ${apiUsagePct > 80 ? 'bg-red-500' : apiUsagePct > 50 ? 'bg-yellow-500' : 'bg-emerald-500'}`}
                 style={{ width: `${Math.min(100, apiUsagePct)}%` }} />
          </div>
        </div>
      </Panel>
    </div>
  )
}
