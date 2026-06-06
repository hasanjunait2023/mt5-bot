import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '../lib/api'
import { MetricCard } from '../components/ui/MetricCard'

interface HunterStats {
  runs: number
  created_jobs: number
  top: string[]
  last_run_at: string | null
  last_scorecard: { collected: number; fresh: number; opened: number } | null
  by_status: Record<string, number>
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface JobSummary {
  job_id: string
  created_at: string
  stage: string
  status: string
  is_strategy: boolean | null
  strategy_id: string | null
  title: string
  youtube_url: string
  verdict: string
}

interface Approval { state: string; by: string | null; at: string | null; note: string }
interface Job extends JobSummary {
  source: Record<string, any>
  classification_reason: string
  approvals: Record<string, Approval>
  artifacts: Record<string, string>
  metrics: { backtest?: any; optimize?: any; soak?: any }
  history: { at: string; stage: string; msg: string }[]
  error: string | null
  _artifacts_present: Record<string, boolean>
  _pending_gate: string | null
}

const STAGES = [
  'INGEST', 'CLASSIFY', 'RESEARCH_NB', 'RESEARCH_VIDEO', 'MERGE_SPEC', 'BUILD_PLAN',
  'GATE_PLAN', 'CODEGEN', 'BACKTEST', 'GATE_BACKTEST', 'OPTIMIZE', 'DEMO_DEPLOY',
  'SOAK', 'GATE_LIVE', 'DONE',
]

const STATUS_TONE: Record<string, string> = {
  RUNNING: 'text-accent', WAITING_APPROVAL: 'text-amber-400',
  DONE: 'text-profit', REJECTED: 'text-loss', FAILED: 'text-loss',
}

const ARTIFACTS = ['plan', 'spec', 'discovery', 'deep', 'backtest', 'transcript'] as const
type ArtName = typeof ARTIFACTS[number]

// ── Page ────────────────────────────────────────────────────────────────────────
export function Factory() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [selId, setSelId] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [ytUrl, setYtUrl] = useState('')
  const [nbUrl, setNbUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<ArtName>('plan')
  const [artifact, setArtifact] = useState<string>('')
  const [hunter, setHunter] = useState<HunterStats | null>(null)

  const loadHunter = useCallback(async () => {
    try {
      const r = await apiFetch('/api/factory/hunter')
      if (r.ok) setHunter(await r.json())
    } catch { /* ignore */ }
  }, [])

  const loadJobs = useCallback(async () => {
    try {
      const r = await apiFetch('/api/factory/jobs')
      const d = await r.json()
      setJobs(d.jobs || [])
      if (!selId && d.jobs?.length) setSelId(d.jobs[0].job_id)
    } catch { /* ignore */ }
  }, [selId])

  const loadJob = useCallback(async (id: string) => {
    try {
      const r = await apiFetch(`/api/factory/jobs/${id}`)
      if (r.ok) setJob(await r.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadHunter(); const t = setInterval(loadHunter, 30000); return () => clearInterval(t) }, [loadHunter])
  useEffect(() => { loadJobs(); const t = setInterval(loadJobs, 8000); return () => clearInterval(t) }, [loadJobs])
  useEffect(() => {
    if (!selId) return
    loadJob(selId)
    const t = setInterval(() => loadJob(selId), 5000)
    return () => clearInterval(t)
  }, [selId, loadJob])

  useEffect(() => {
    if (!selId || !job?._artifacts_present?.[tab]) { setArtifact(''); return }
    apiFetch(`/api/factory/jobs/${selId}/artifact?name=${tab}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setArtifact(d?.content || ''))
      .catch(() => setArtifact(''))
  }, [selId, tab, job])

  async function ingest() {
    if (!ytUrl.trim()) return
    setBusy(true)
    try {
      const r = await apiFetch('/api/factory/ingest', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ youtube_url: ytUrl.trim(), notebook_url: nbUrl.trim() }),
      })
      const d = await r.json()
      setYtUrl(''); setNbUrl('')
      await loadJobs()
      if (d.job_id) setSelId(d.job_id)
    } finally { setBusy(false) }
  }

  async function gate(action: 'approve' | 'reject', g: string) {
    if (!selId) return
    await apiFetch(`/api/factory/jobs/${selId}/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gate: g, by: 'dashboard' }),
    })
    await loadJob(selId); await loadJobs()
  }

  async function requeue() {
    if (!selId) return
    await apiFetch(`/api/factory/jobs/${selId}/requeue`, { method: 'POST' })
    await loadJob(selId); await loadJobs()
  }

  const bt = job?.metrics?.backtest || {}
  const soak = job?.metrics?.soak || {}

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-text-primary">Strategy Factory</h1>
        <p className="text-text-muted text-sm mt-0.5">
          YouTube → research → code → backtest → demo soak → real-money gate
        </p>
      </div>

      {/* Source Hunter Leaderboard */}
      {hunter && (
        <div className="glass p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="eyebrow">Source Hunter Pipeline</p>
            {hunter.last_run_at && (
              <span className="text-[11px] text-text-muted">
                last run {new Date(hunter.last_run_at).toLocaleString()}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard label="Total Runs" value={hunter.runs} />
            <MetricCard label="Jobs Created" value={hunter.created_jobs} />
            <MetricCard label="Last Batch Found" value={hunter.last_scorecard?.collected ?? 0} sub="candidates" />
            <MetricCard label="Last Batch Opened" value={hunter.last_scorecard?.opened ?? 0} sub="jobs" />
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(hunter.by_status).map(([st, n]) => (
              <span key={st} className={`text-[11px] px-2.5 py-1 rounded-full font-mono ${
                st === 'DONE' ? 'bg-profit/10 text-profit' :
                st === 'WAITING_APPROVAL' ? 'bg-amber-400/10 text-amber-400' :
                st === 'REJECTED' || st === 'FAILED' ? 'bg-loss/10 text-loss' :
                'bg-tint/[0.05] text-text-muted'
              }`}>{st} {n}</span>
            ))}
          </div>
          {hunter.top.length > 0 && (
            <div>
              <p className="text-[11px] text-text-muted mb-1.5">Top candidates from last run</p>
              <div className="space-y-1">
                {hunter.top.map((t, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[11px] font-mono text-accent/60 w-4 shrink-0">#{i + 1}</span>
                    <span className="text-xs text-text-secondary truncate">{t}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Ingest */}
      <div className="glass p-4 flex flex-col gap-3">
        <p className="eyebrow">Start a new strategy</p>
        <div className="flex flex-col md:flex-row gap-2">
          <input
            value={ytUrl} onChange={e => setYtUrl(e.target.value)}
            placeholder="YouTube video URL"
            className="flex-1 bg-bg-surface/60 border border-border rounded-lg px-3 h-10 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <input
            value={nbUrl} onChange={e => setNbUrl(e.target.value)}
            placeholder="NotebookLM notebook URL (optional, for deep research)"
            className="flex-1 bg-bg-surface/60 border border-border rounded-lg px-3 h-10 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <button
            onClick={ingest} disabled={busy || !ytUrl.trim()}
            className="h-10 px-5 rounded-lg bg-accent/90 hover:bg-accent text-bg-base font-semibold text-sm disabled:opacity-40 transition"
          >{busy ? 'Starting…' : 'Start'}</button>
        </div>
        <p className="text-text-muted text-[11px]">
          Tip: create a NotebookLM notebook, add this video as a source, and paste the notebook URL
          for the full A-to-Z research (audio overview + grounded Q&A).
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-5">
        {/* Job list */}
        <div className="glass p-3 space-y-1.5 max-h-[70vh] overflow-y-auto">
          <p className="eyebrow px-1 pb-1">Jobs ({jobs.length})</p>
          {jobs.length === 0 && <p className="text-text-muted text-sm px-1 py-6 text-center">No jobs yet.</p>}
          {jobs.map(j => (
            <button
              key={j.job_id} onClick={() => setSelId(j.job_id)}
              className={`w-full text-left px-3 py-2 rounded-lg transition ring-1 ${
                selId === j.job_id ? 'bg-tint/[0.06] ring-border' : 'ring-transparent hover:bg-tint/[0.03]'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-text-primary font-medium truncate">
                  {j.strategy_id ? `${j.strategy_id} · ` : ''}{j.title || j.youtube_url}
                </span>
                {j.status === 'WAITING_APPROVAL' && <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[11px] text-text-muted">{j.stage}</span>
                <span className={`text-[11px] font-mono ${STATUS_TONE[j.status] || 'text-text-muted'}`}>{j.status}</span>
              </div>
            </button>
          ))}
        </div>

        {/* Detail */}
        <div className="space-y-4">
          {!job && <div className="glass p-8 text-center text-text-muted text-sm">Select a job.</div>}
          {job && (
            <>
              {/* Stepper */}
              <div className="glass p-4">
                <div className="flex flex-wrap gap-1.5">
                  {STAGES.map(s => {
                    const idx = STAGES.indexOf(job.stage)
                    const here = s === job.stage
                    const done = STAGES.indexOf(s) < idx || job.status === 'DONE'
                    return (
                      <span key={s} className={`text-[10px] px-2 py-1 rounded font-mono ${
                        here ? 'bg-accent/20 text-accent ring-1 ring-accent/40'
                        : done ? 'bg-profit/10 text-profit/80' : 'bg-tint/[0.03] text-text-muted'
                      }`}>{s}</span>
                    )
                  })}
                </div>
                <p className="text-xs text-text-muted mt-3">
                  {job.classification_reason || job.source?.title || job.source?.youtube_url}
                </p>
                {job.error && <p className="text-xs text-loss mt-2">⚠ {job.error}</p>}
              </div>

              {/* Gate actions */}
              {job._pending_gate && (
                <div className="glass p-4 ring-1 ring-amber-400/30">
                  <p className="text-sm text-amber-400 font-semibold mb-2">
                    Awaiting approval: {job._pending_gate.toUpperCase()} gate
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => gate('approve', job._pending_gate!)}
                      className="h-9 px-4 rounded-lg bg-profit/90 hover:bg-profit text-bg-base font-semibold text-sm transition">
                      Approve
                    </button>
                    <button onClick={() => gate('reject', job._pending_gate!)}
                      className="h-9 px-4 rounded-lg bg-loss/80 hover:bg-loss text-white font-semibold text-sm transition">
                      Reject
                    </button>
                  </div>
                </div>
              )}
              {job.status === 'FAILED' && (
                <button onClick={requeue}
                  className="h-9 px-4 rounded-lg bg-tint/[0.06] hover:bg-tint/[0.1] text-text-primary text-sm transition">
                  Requeue (retry)
                </button>
              )}

              {/* Metrics */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard label="Backtest PF" value={bt.profit_factor ?? 0}
                  tone={(bt.profit_factor ?? 0) >= 1.3 ? 'profit' : 'neutral'} sub={bt.verdict || '—'} />
                <MetricCard label="Backtest WR" value={bt.win_rate_pct ?? 0} suffix="%" />
                <MetricCard label="Backtest trades" value={bt.trades ?? 0} />
                <MetricCard label="Optimize OOS PF" value={job.metrics?.optimize?.oos_pf ?? 0}
                  tone={(job.metrics?.optimize?.oos_pf ?? 0) >= 1.3 ? 'profit' : 'neutral'} />
                <MetricCard label="Soak PF" value={soak.pf ?? 0}
                  tone={(soak.pf ?? 0) >= 1.4 ? 'profit' : 'neutral'} />
                <MetricCard label="Soak trades" value={soak.trades ?? 0} sub={`need 40`} />
                <MetricCard label="Soak win rate" value={soak.win_rate ?? 0} suffix="%" />
                <MetricCard label="Soak days" value={soak.days ?? 0} sub={`need 5`} />
              </div>

              {/* Artifacts */}
              <div className="glass p-4">
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {ARTIFACTS.map(a => (
                    <button key={a} onClick={() => setTab(a)}
                      className={`text-xs px-3 py-1.5 rounded-lg transition ${
                        tab === a ? 'bg-accent/20 text-accent' : 'bg-tint/[0.03] text-text-muted hover:text-text-secondary'
                      } ${!job._artifacts_present?.[a] ? 'opacity-40' : ''}`}>
                      {a}
                    </button>
                  ))}
                  {job.artifacts?.audio_overview && (
                    <span className="text-xs px-3 py-1.5 rounded-lg bg-profit/10 text-profit/80">🎧 audio ready</span>
                  )}
                </div>
                <pre className="text-xs text-text-secondary whitespace-pre-wrap max-h-[40vh] overflow-y-auto font-mono leading-relaxed">
                  {artifact || (job._artifacts_present?.[tab] ? 'Loading…' : 'Not available yet.')}
                </pre>
              </div>

              {/* History */}
              <div className="glass p-4">
                <p className="eyebrow mb-2">History</p>
                <div className="space-y-1 max-h-[24vh] overflow-y-auto">
                  {[...job.history].reverse().map((h, i) => (
                    <div key={i} className="flex gap-3 text-xs">
                      <span className="text-text-muted font-mono shrink-0">{h.stage}</span>
                      <span className="text-text-secondary">{h.msg}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
