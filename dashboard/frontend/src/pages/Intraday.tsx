import { useEffect, useMemo, useState } from 'react'
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
    mode?: string
    last_run?: string | null
    next_run?: string | null
    updated_at?: string | null
    errors?: { symbol: string; error: string }[]
  }
  latest: TvEvent[]
  count: number
}

function fmt(ts?: string | null): string {
  if (!ts) return '—'
  try { return new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return ts }
}

export function Intraday() {
  const [resp, setResp] = useState<StateResp | null>(null)
  const [perf, setPerf] = useState<PerfData | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [r, p] = await Promise.all([apiFetch('/intraday/state'), apiFetch('/intraday/perf')])
        if (r.ok) { const d = await r.json(); if (!cancelled) setResp(d) }
        if (p.ok) { const d = await p.json(); if (!cancelled) setPerf(d) }
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 15_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const latest = resp?.latest ?? []
  const running = resp?.state?.running ?? false
  const totalEntries = useMemo(
    () => latest.reduce((a, e) => a + (e.entries?.length ?? 0), 0), [latest])
  const t = perf?.totals ?? {}

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Intraday Analyst</h1>
          <p className="text-text-secondary text-sm mt-1">
            Daily TradingView day-trade plan — 3 entries/symbol at 1:2 &amp; 1:3, marked on chart.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusDot status={running ? 'running' : 'offline'} />
          <span className="text-sm text-text-secondary">
            last run {fmt(resp?.state?.last_run)}
            {resp?.state?.next_run ? ` · next ${fmt(resp.state.next_run)}` : ''}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <MetricCard label="Symbols"  value={latest.length}                          tone="accent" />
        <MetricCard label="Entries"  value={totalEntries}                           tone="neutral" />
        <MetricCard label="Win rate" value={t.win_rate != null ? `${t.win_rate}%` : '—'}
                    tone={(t.win_rate ?? 0) >= 50 ? 'profit' : 'loss'}
                    sub={t.win != null ? `${t.win}W / ${t.loss}L` : 'no closes yet'} />
        <MetricCard label="Total R"  value={t.total_R != null ? t.total_R : '—'}
                    tone={(t.total_R ?? 0) >= 0 ? 'profit' : 'loss'}
                    sub={t.pending != null ? `${t.pending} pending` : undefined} />
      </div>

      <Panel i={0} title="Latest Plan (per symbol)">
        {latest.length === 0 ? (
          <div className="text-text-tertiary text-sm py-6 text-center">
            No analysis yet — runs once per day at NY close, or trigger manually:
            <code className="ml-1 text-text-secondary">python -m trading_agents.tv_desk.intraday_analyst --once</code>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {latest.map(ev => <AnalysisCard key={ev.id} ev={ev} agent="intraday" />)}
          </div>
        )}
      </Panel>

      <PerfPanel perf={perf} i={1} />
    </div>
  )
}
