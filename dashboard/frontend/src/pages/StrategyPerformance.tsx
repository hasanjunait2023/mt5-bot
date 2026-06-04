import { useEffect, useState } from 'react'
import { MetricCard } from '../components/ui/MetricCard'
import { Badge } from '../components/ui/Badge'
import { apiFetch } from '../lib/api'

interface Card {
  strategy: string
  verdict: 'PROFITABLE' | 'LOSING' | 'INSUFFICIENT'
  in_improvement: boolean
  live_pf: number | null
  backtest_pf: number | null
  win_rate: number | null
  expectancy: number | null
  net_pnl: number | null
  max_drawdown: number | null
  avg_rr: number | null
  n: number
  trend: 'up' | 'down' | 'flat'
  top_failure: string | null
  fix_headline: string
  fix_details: string[]
  top_strength: string | null
  strength_note: string
}
interface Scorecard {
  generated_at?: string
  window_days?: number
  portfolio: { net_pnl: number; profit_factor: number | null; trades: number }
  counts: { profitable: number; losing: number; insufficient: number }
  strategies: Card[]
  improvement_queue: string[]
  error?: string
}

const TREND: Record<string, string> = { up: '▲', down: '▼', flat: '▬' }
const money = (x: number | null) =>
  x == null ? '—' : (x >= 0 ? `+$${x.toLocaleString()}` : `-$${Math.abs(x).toLocaleString()}`)

function Row({ c }: { c: Card }) {
  const [open, setOpen] = useState(false)
  const dotColor = c.verdict === 'PROFITABLE' ? 'bg-profit' : c.verdict === 'LOSING' ? 'bg-loss' : 'bg-text-muted'
  return (
    <div className="glass rounded-xl">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-3 p-4 text-left">
        <span className={`h-2.5 w-2.5 rounded-full ${dotColor}`} />
        <span className="font-semibold text-text-primary min-w-[150px]">{c.strategy}</span>
        <span className="font-mono text-sm text-text-secondary">PF {c.live_pf ?? '—'}</span>
        {c.backtest_pf != null && <span className="font-mono text-xs text-text-muted">bt {c.backtest_pf}</span>}
        <span className="font-mono text-sm text-text-secondary">{c.win_rate ?? '—'}%</span>
        <span className={`font-mono text-sm ${(c.net_pnl ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{money(c.net_pnl)}</span>
        <span className="font-mono text-xs text-text-muted">n={c.n}</span>
        <span className="text-text-secondary">{TREND[c.trend]}</span>
        {c.in_improvement && <Badge tone="orange">improving</Badge>}
        <span className="ml-auto text-text-muted">{open ? '▾' : '▸'}</span>
      </button>
      {c.verdict === 'LOSING' && c.fix_headline && !open && (
        <div className="px-11 pb-3 -mt-1 text-xs text-loss/90 truncate">fix: {c.fix_headline}</div>
      )}
      {open && (
        <div className="border-t border-border px-11 py-3 space-y-2 text-sm">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs text-text-secondary">
            <span>expectancy: {c.expectancy ?? '—'}</span>
            <span>avg RR: {c.avg_rr ?? '—'}</span>
            <span>max DD (isolated): {money(c.max_drawdown)}</span>
            <span>backtest PF: {c.backtest_pf ?? '—'}</span>
          </div>
          {c.top_strength && (
            <div className="text-profit/90"><span className="font-semibold">strength:</span> {c.strength_note || c.top_strength}</div>
          )}
          {c.top_failure && (
            <div className="text-loss/90"><span className="font-semibold">top failure:</span> {c.top_failure}</div>
          )}
          {c.fix_headline && <div className="text-text-primary"><span className="font-semibold">fix:</span> {c.fix_headline}</div>}
          {c.fix_details?.map((d, i) => <div key={i} className="text-text-secondary pl-4">• {d}</div>)}
        </div>
      )}
    </div>
  )
}

function Section({ title, cards }: { title: string; cards: Card[] }) {
  if (!cards.length) return null
  return (
    <div className="space-y-2">
      <h3 className="eyebrow text-text-secondary">{title} ({cards.length})</h3>
      {cards.map(c => <Row key={c.strategy} c={c} />)}
    </div>
  )
}

export default function StrategyPerformance() {
  const [sc, setSc] = useState<Scorecard | null>(null)
  const [recon, setRecon] = useState<{ last_run: string | null } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    const load = () => {
      apiFetch('/api/scorecard').then(r => r.json()).then(d => { if (alive) { setSc(d); setLoading(false) } }).catch(() => alive && setLoading(false))
      apiFetch('/api/reconciler/status').then(r => r.json()).then(d => alive && setRecon(d)).catch(() => {})
    }
    load()
    const t = setInterval(load, 30000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (loading) return (
    <div className="space-y-3">
      {[0, 1, 2].map(i => <div key={i} className="glass rounded-xl h-14 animate-pulse" />)}
    </div>
  )

  if (!sc || sc.error) return (
    <div className="glass rounded-xl p-8 text-center text-text-secondary">
      {sc?.error || 'Scorecard unavailable.'}
    </div>
  )

  if (!sc.strategies.length) return (
    <div className="glass rounded-xl p-8 text-center text-text-secondary">
      No closed trades yet. Strategies appear here once positions close and reconcile against MT5 history.
    </div>
  )

  const byV = (v: string) => sc.strategies.filter(c => c.verdict === v)
  const stamp = recon?.last_run ? new Date(recon.last_run).toLocaleTimeString() : '—'

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <MetricCard hero label="Portfolio net (30d)" value={sc.portfolio.net_pnl}
          prefix={sc.portfolio.net_pnl >= 0 ? '+$' : '-$'}
          tone={sc.portfolio.net_pnl >= 0 ? 'profit' : 'loss'} />
        <MetricCard label="Profitable" value={`${sc.counts.profitable}/${sc.strategies.length}`} tone="accent" />
        <MetricCard label="In improvement" value={sc.improvement_queue.length}
          tone={sc.improvement_queue.length ? 'loss' : 'neutral'} />
      </div>

      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>Portfolio PF: {sc.portfolio.profit_factor ?? '—'} · {sc.portfolio.trades} closed trades</span>
        <span>last reconciled {stamp}</span>
      </div>

      <Section title="PROFITABLE" cards={byV('PROFITABLE')} />
      <Section title="LOSING / IN IMPROVEMENT" cards={byV('LOSING')} />
      <Section title="INSUFFICIENT SAMPLE" cards={byV('INSUFFICIENT')} />
    </div>
  )
}
