import { useEffect, useState } from 'react'
import { Panel } from '../components/ui/Panel'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { apiFetch } from '../lib/api'
import { AnalysisCard, type TvEvent } from '../components/tvdesk/AnalysisCard'
import { PerfPanel, type PerfData } from '../components/tvdesk/PerfPanel'

interface StateResp {
  state: {
    running?: boolean
    idle?: boolean
    session?: string | null
    next_session?: string | null
    last_run?: string | null
    next_run?: string | null
  }
  latest: TvEvent[]
  count: number
}

const SESSION_LABEL: Record<string, string> = {
  asia: '🌏 Asia', london: '🌅 London', ny: '🗽 New York',
}

function fmt(ts?: string | null): string {
  if (!ts) return '—'
  try { return new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return ts }
}

export function SessionScalp() {
  const [resp, setResp] = useState<StateResp | null>(null)
  const [perf, setPerf] = useState<PerfData | null>(null)
  const [filter, setFilter] = useState<string>('all')

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [r, p] = await Promise.all([apiFetch('/session-scalp/state'), apiFetch('/session-scalp/perf')])
        if (r.ok) { const d = await r.json(); if (!cancelled) setResp(d) }
        if (p.ok) { const d = await p.json(); if (!cancelled) setPerf(d) }
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 15_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const t = perf?.totals ?? {}

  const latest = resp?.latest ?? []
  const running = resp?.state?.running ?? false
  const filtered = filter === 'all' ? latest : latest.filter(e => e.session === filter)
  const totalEntries = filtered.reduce((a, e) => a + (e.entries?.length ?? 0), 0)
  const nextSession = resp?.state?.next_session

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Session Scalper</h1>
          <p className="text-text-secondary text-sm mt-1">
            2–3 scalps for the upcoming session — fires 30 min before Asia / London / NY open.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusDot status={running ? 'running' : 'offline'} />
          <span className="text-sm text-text-secondary">
            {nextSession ? `next: ${SESSION_LABEL[nextSession] ?? nextSession} · ` : ''}
            run {fmt(resp?.state?.last_run)}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <MetricCard label="Symbols"  value={filtered.length} tone="accent" />
        <MetricCard label="Scalps"   value={totalEntries}    tone="neutral" />
        <MetricCard label="Win rate" value={t.win_rate != null ? `${t.win_rate}%` : '—'}
                    tone={(t.win_rate ?? 0) >= 50 ? 'profit' : 'loss'}
                    sub={t.win != null ? `${t.win}W / ${t.loss}L` : 'no closes yet'} />
        <MetricCard label="Total R"  value={t.total_R != null ? t.total_R : '—'}
                    tone={(t.total_R ?? 0) >= 0 ? 'profit' : 'loss'}
                    sub={t.pending != null ? `${t.pending} pending` : undefined} />
      </div>

      <Panel
        i={0}
        title="Scalp Setups"
        right={
          <div className="flex items-center gap-2">
            {(['all', 'asia', 'london', 'ny'] as const).map(t => (
              <button key={t} onClick={() => setFilter(t)}
                className={`px-3 h-7 rounded-md text-[11px] font-semibold uppercase tracking-wider transition-all ${
                  filter === t ? 'bg-white/[0.08] text-text-primary ring-1 ring-border'
                               : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.03]'}`}>
                {t}
              </button>
            ))}
          </div>
        }
      >
        {filtered.length === 0 ? (
          <div className="text-text-tertiary text-sm py-6 text-center">
            No scalps yet — fires pre-session, or trigger manually:
            <code className="ml-1 text-text-secondary">python -m trading_agents.tv_desk.session_scalper --once --session london</code>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map(ev => <AnalysisCard key={ev.id} ev={ev} agent="session-scalp" />)}
          </div>
        )}
      </Panel>

      <PerfPanel perf={perf} showSession i={1} />
    </div>
  )
}
