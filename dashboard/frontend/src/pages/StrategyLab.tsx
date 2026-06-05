import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { apiFetch } from '../lib/api'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { MetricCard } from '../components/ui/MetricCard'
import { Badge } from '../components/ui/Badge'
import { Table } from '../components/ui/Table'

// ── Types (mirror dashboard/backend/api/strategy_lab.py) ──────────────────────
interface Funnel {
  discovered: number; building: number; backtested: number
  soak: number; live_ready: number; rejected: number
}
interface LbRow {
  job_id: string; title: string; strategy_id: string | null; stage: string
  source: string; score: number | null; bucket: string
  soak_pf: number; soak_wr: number; soak_trades: number; soak_days: number; soak_open: number
  bt_pf: number; bt_wr: number; bt_verdict: string; graduated: boolean
}
interface PipeRow {
  job_id: string; title: string; strategy_id: string | null; stage: string; status: string
  bucket: string; source: string; score: number | null; verdict: string; created_at: string | null
}
interface LabData {
  updated_at: string
  hunter: { runs: number; opened_total: number; last: { collected?: number; fresh?: number; opened?: number } }
  funnel: Funnel
  total_jobs: number
  leaderboard: LbRow[]
  pipeline: PipeRow[]
}

const FUNNEL_STEPS: { k: keyof Funnel; label: string; tone: string }[] = [
  { k: 'discovered', label: 'Discovered', tone: 'text-text-secondary' },
  { k: 'building', label: 'Building', tone: 'text-accent' },
  { k: 'backtested', label: 'Backtested', tone: 'text-warning' },
  { k: 'soak', label: 'Demo Soak', tone: 'text-accent' },
  { k: 'live_ready', label: 'Live-Ready', tone: 'text-profit' },
]

function sourceTone(s: string): 'red' | 'blue' | 'green' | 'yellow' | 'gray' {
  if (s === 'youtube') return 'red'
  if (s === 'web') return 'blue'
  if (s === 'llm') return 'green'
  if (s === 'papers') return 'yellow'
  return 'gray'
}
function pfTone(pf: number): 'green' | 'red' | 'yellow' {
  return pf >= 1.3 ? 'green' : pf < 1 ? 'red' : 'yellow'
}
function lbStatus(r: LbRow): { label: string; tone: 'green' | 'yellow' | 'blue' } {
  if (r.graduated) return { label: 'READY · REAL', tone: 'green' }
  if (r.stage === 'GATE_LIVE') return { label: 'AWAITING OK', tone: 'yellow' }
  return { label: 'SOAKING', tone: 'blue' }
}
function stageTone(b: string): 'gray' | 'blue' | 'yellow' | 'green' | 'red' {
  if (b === 'building' || b === 'soak') return 'blue'
  if (b === 'backtested') return 'yellow'
  if (b === 'live_ready') return 'green'
  if (b === 'rejected') return 'red'
  return 'gray'
}
function shortDate(s: string | null): string {
  if (!s) return '—'
  try { return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) } catch { return '—' }
}

export function StrategyLab() {
  const [data, setData] = useState<LabData | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await apiFetch('/strategy-lab/leaderboard')
        if (!cancelled && r.ok) { setData(await r.json()); setErr(false) }
        else if (!cancelled) setErr(true)
      } catch { if (!cancelled) setErr(true) }
    }
    load()
    const id = setInterval(load, 20_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const champion = data?.leaderboard[0]
  const f = data?.funnel

  return (
    <div className="space-y-5">
      <PageHeader
        title="Strategy Lab"
        subtitle="Autonomous discovery → backtest → demo soak → real-money. Champion = top live demo performer."
        right={data && <span className="eyebrow">Hunter run #{data.hunter.runs}</span>}
      />

      {err && !data && (
        <Panel title="Strategy Lab"><p className="text-sm text-loss">Failed to load leaderboard.</p></Panel>
      )}

      {/* Headline metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <MetricCard
          hero
          label="Champion Demo PF"
          value={champion ? champion.soak_pf : 0}
          tone={champion ? pfTone(champion.soak_pf) : 'neutral'}
          sub={champion ? `${champion.title.slice(0, 28)} · ${champion.soak_trades}t` : 'no strategy on demo yet'}
        />
        <MetricCard
          label="On Demo Soak"
          value={String(f?.soak ?? 0)}
          tone="accent"
          sub="strategies live-trading demo"
        />
        <MetricCard
          label="Live-Ready"
          value={String(f?.live_ready ?? 0)}
          tone="green"
          sub="awaiting your real-money OK"
        />
        <MetricCard
          label="Discovered Total"
          value={String(data?.total_jobs ?? 0)}
          sub={`${data?.hunter.opened_total ?? 0} opened by hunter`}
        />
      </div>

      {/* Funnel strip */}
      <Panel title="Discovery Funnel" i={1}>
        <div className="flex flex-wrap items-stretch gap-2">
          {FUNNEL_STEPS.map((step, idx) => (
            <div key={step.k} className="flex items-center gap-2">
              <div className="glass rounded-lg px-4 py-3 min-w-[112px] text-center">
                <div className={clsx('font-mono font-bold text-2xl leading-none', step.tone)}>
                  {f?.[step.k] ?? 0}
                </div>
                <div className="eyebrow mt-1.5">{step.label}</div>
              </div>
              {idx < FUNNEL_STEPS.length - 1 && <span className="text-text-muted text-lg">→</span>}
            </div>
          ))}
          <div className="flex items-center ml-auto">
            <div className="rounded-lg px-4 py-3 min-w-[96px] text-center ring-1 ring-loss/20 bg-loss/[0.04]">
              <div className="font-mono font-bold text-2xl leading-none text-loss">{f?.rejected ?? 0}</div>
              <div className="eyebrow mt-1.5">Rejected</div>
            </div>
          </div>
        </div>
      </Panel>

      {/* Champion / Challenger leaderboard */}
      <Panel title="Champion / Challenger — Live Demo Ranking" i={2}>
        <Table<LbRow>
          data={data?.leaderboard ?? []}
          keyFn={r => r.job_id}
          emptyText="No strategy on demo yet — the hunter is still building candidates."
          columns={[
            { key: 'rank', header: '#', align: 'right', render: r => {
              const i = (data?.leaderboard ?? []).indexOf(r)
              return <span className={i === 0 ? 'text-profit font-bold' : 'text-text-muted'}>{i === 0 ? '★' : i + 1}</span>
            } },
            { key: 'title', header: 'Strategy', render: r => (
              <div className="flex flex-col">
                <span className="text-text-primary font-semibold max-w-[260px] truncate">{r.title}</span>
                <span className="text-[11px] text-text-muted">{r.strategy_id ?? '—'}</span>
              </div>
            ) },
            { key: 'source', header: 'Source', render: r => <Badge tone={sourceTone(r.source)}>{r.source}</Badge> },
            { key: 'score', header: 'Grade', align: 'right', render: r => r.score != null
              ? <span className={r.score >= 85 ? 'text-profit' : r.score >= 70 ? 'text-warning' : 'text-text-muted'}>{r.score}</span>
              : <span className="text-text-muted">—</span> },
            { key: 'pf', header: 'Demo PF', align: 'right', render: r => (
              <span className={clsx('font-bold', r.soak_pf >= 1.3 ? 'text-profit' : r.soak_pf < 1 ? 'text-loss' : 'text-warning')}>
                {r.soak_pf.toFixed(2)}
              </span>
            ) },
            { key: 'wr', header: 'WR', align: 'right', render: r => `${r.soak_wr.toFixed(0)}%` },
            { key: 'trades', header: 'Trades', align: 'right', render: r => <span>{r.soak_trades}<span className="text-text-muted">{r.soak_open ? ` (${r.soak_open})` : ''}</span></span> },
            { key: 'days', header: 'Days', align: 'right', render: r => r.soak_days.toFixed(1) },
            { key: 'bt', header: 'Backtest PF', align: 'right', render: r => (
              <span className="text-text-muted">{r.bt_pf ? r.bt_pf.toFixed(2) : '—'}</span>
            ) },
            { key: 'status', header: 'Status', render: r => { const s = lbStatus(r); return <Badge tone={s.tone}>{s.label}</Badge> } },
          ]}
        />
      </Panel>

      {/* Full discovery pipeline */}
      <Panel title="Discovery Pipeline — all candidates" i={3}>
        <Table<PipeRow>
          data={data?.pipeline ?? []}
          keyFn={r => r.job_id}
          emptyText="No candidates discovered yet."
          columns={[
            { key: 'title', header: 'Candidate', render: r => (
              <span className="text-text-primary max-w-[300px] truncate inline-block">{r.title}</span>
            ) },
            { key: 'source', header: 'Source', render: r => <Badge tone={sourceTone(r.source)}>{r.source}</Badge> },
            { key: 'score', header: 'Grade', align: 'right', render: r => r.score != null ? r.score : '—' },
            { key: 'stage', header: 'Stage', render: r => <Badge tone={stageTone(r.bucket)}>{r.stage}</Badge> },
            { key: 'verdict', header: 'Backtest', render: r => <span className="text-text-muted text-xs">{r.verdict || '—'}</span> },
            { key: 'created', header: 'Found', align: 'right', render: r => <span className="text-text-muted">{shortDate(r.created_at)}</span> },
          ]}
        />
      </Panel>
    </div>
  )
}
