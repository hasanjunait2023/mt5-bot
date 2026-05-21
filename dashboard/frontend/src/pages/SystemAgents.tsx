import { useState, useEffect } from 'react'
import { Panel } from '../components/ui/Panel'
import { StatusDot } from '../components/ui/StatusDot'
import { Table } from '../components/ui/Table'
import { PageHeader } from '../components/ui/PageHeader'
import { apiFetch } from '../lib/api'

type AgentStatus = 'running' | 'warning' | 'offline'

interface Overview {
  dev: {
    status: AgentStatus
    last_run_minutes_ago: number | null
    monitor_summary: string
    monitor_anomaly: boolean
    monitor_level: string
    recent_reviews: { name: string; modified: number }[]
    recent_debug_reports: { name: string; modified: number }[]
  }
  ea: {
    guardian: {
      status: AgentStatus
      last_check_minutes_ago: number | null
      anomalies_found: number
      account: Record<string, number | null>
    }
    coach: {
      ea_stages: Record<string, string>
      pending_decisions: { ea: string; question: string; asked_at: string }[]
      last_updated: string | null
    }
    validator: {
      ea: string | null
      overall_verdict: string | null
      compatible_pairs: string[]
      incompatible_pairs: string[]
      recommendation: string
      tested_at: string | null
    }
  }
  supervisor: {
    status: AgentStatus
    last_audit_minutes_ago: number | null
    overall_status: string
    summary: string
    issues_found: number
    issues: { component: string; severity: string; description: string }[]
    resolved: string[]
    unresolved: string[]
    next_action: string
    history: { timestamp: string; overall_status: string; issues_found: number }[]
  }
  scout: {
    status: AgentStatus
    last_cycle_minutes_ago: number | null
    cycles: number
    scorecard: Record<string, number>
    stage_counts: Record<string, number>
    total_ideas: number
    recent_ideas: { description: string; stage: string; source: string; score?: Record<string, number> }[]
  }
}

interface LLMStat {
  agent: string
  calls: number
  last_model: string | null
  last_backend: string | null
  fallback_pct: number
  error_pct: number
  avg_latency_ms: number
  last_run_minutes_ago: number | null
}

interface IncidentRow {
  id: string; source_agent: string; component: string; symptom: string
  severity: string; status: string; resolution: string
  opened_at: string; closed_at: string
}
interface IncidentsData {
  kill_switch: { halted: boolean; reason: string | null; ts: string | null }
  summary: { total: number; by_status: Record<string, number>; open_or_failed: number }
  incidents: IncidentRow[]
}

const INC_TONE: Record<string, string> = {
  resolved: 'text-profit', failed: 'text-loss', halted: 'text-loss',
  fixing: 'text-warning', open: 'text-warning', deferred: 'text-text-muted',
}

const ago = (m: number | null) =>
  m == null ? 'never' : m < 60 ? `${Math.round(m)}m ago` : `${(m / 60).toFixed(1)}h ago`

function HeadStatus({ status, sub }: { status: AgentStatus; sub: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <StatusDot status={status} />
      <span className="text-text-muted text-xs">{sub}</span>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'profit' | 'loss' | 'accent' }) {
  const color =
    tone === 'profit' ? 'text-profit' : tone === 'loss' ? 'text-loss' : tone === 'accent' ? 'text-accent' : 'text-text-primary'
  return (
    <div className="glass p-4 flex flex-col gap-1.5 min-w-0">
      <p className="eyebrow truncate">{label}</p>
      <p className={`font-mono font-bold text-2xl leading-none ${color}`}>{value}</p>
    </div>
  )
}

const SUP_TONE: Record<string, AgentStatus> = {
  HEALTHY: 'running', DEGRADED: 'warning', CRITICAL: 'offline', UNKNOWN: 'offline',
}
const SEV_COLOR: Record<string, string> = {
  CRITICAL: 'text-loss', WARNING: 'text-warning', INFO: 'text-accent',
}

export function SystemAgents() {
  const [d, setD] = useState<Overview | null>(null)
  const [llm, setLlm] = useState<{ agents: LLMStat[]; total_calls: number } | null>(null)
  const [inc, setInc] = useState<IncidentsData | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    const load = () => {
      apiFetch('/api/system-agents/overview')
        .then(r => r.json())
        .then(j => { setD(j); setErr(false) })
        .catch(() => setErr(true))
      apiFetch('/api/system-agents/llm')
        .then(r => r.json())
        .then(setLlm)
        .catch(() => {})  // telemetry is non-critical — never break the page
      apiFetch('/api/system-agents/incidents')
        .then(r => r.json())
        .then(setInc)
        .catch(() => {})  // incident pipeline non-critical to page render
    }
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [])

  if (err) return <div className="text-loss text-sm">Failed to load system agents — is the backend running?</div>
  if (!d) return <div className="text-text-muted text-sm">Loading system agents…</div>

  const sc = d.scout.scorecard

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Agents"
        subtitle="Live activity & reports from every autonomous agent"
      />

      {/* Kill-switch banner — only when tripped (survival rail) */}
      {inc?.kill_switch?.halted && (
        <div className="glass p-4 border border-loss/40 bg-loss/5">
          <p className="eyebrow text-loss">🚨 Auto Kill-Switch ACTIVE — trading halted</p>
          <p className="text-sm text-text-primary mt-1">{inc.kill_switch.reason}</p>
          {inc.kill_switch.ts && (
            <p className="text-xs text-text-muted mt-1 font-mono">{inc.kill_switch.ts}</p>
          )}
        </div>
      )}

      {/* Autonomous Incident Pipeline (CEO-routed) */}
      {inc && (
        <Panel title="Autonomous Incident Pipeline — CEO-routed" i={0}
          right={<StatusDot
            status={inc.summary.open_or_failed ? 'warning' : 'running'}
            label={`${inc.summary.total} total`} />}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <Stat label="Open / Fixing / Failed" value={inc.summary.open_or_failed}
              tone={inc.summary.open_or_failed ? 'loss' : 'profit'} />
            <Stat label="Resolved" value={inc.summary.by_status['resolved'] ?? 0} tone="profit" />
            <Stat label="Halted" value={inc.summary.by_status['halted'] ?? 0}
              tone={(inc.summary.by_status['halted'] ?? 0) ? 'loss' : undefined} />
            <Stat label="Total" value={inc.summary.total} tone="accent" />
          </div>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {inc.incidents.length === 0 && (
              <p className="text-text-muted text-sm">No incidents — system clean.</p>
            )}
            {inc.incidents.map(it => (
              <div key={it.id} className="glass !bg-white/[0.02] p-3 text-sm">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="font-medium text-text-primary">
                    {it.component}
                    <span className="text-text-muted text-xs ml-2">
                      via {it.source_agent}
                    </span>
                  </span>
                  <span className={`text-xs font-mono uppercase ${INC_TONE[it.status] ?? 'text-text-muted'}`}>
                    {it.status}
                  </span>
                </div>
                <p className="text-text-secondary text-xs mt-1">{it.symptom}</p>
                {it.resolution && (
                  <p className="text-text-muted text-xs mt-1 line-clamp-2">
                    → {it.resolution}
                  </p>
                )}
                <p className="text-text-muted text-[10px] mt-1 font-mono">
                  {it.opened_at}
                </p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* Top status row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Panel i={0} className="!p-4">
          <p className="eyebrow mb-2">Dev Team</p>
          <HeadStatus status={d.dev.status} sub={ago(d.dev.last_run_minutes_ago)} />
        </Panel>
        <Panel i={1} className="!p-4">
          <p className="eyebrow mb-2">EA Guardian</p>
          <HeadStatus status={d.ea.guardian.status} sub={ago(d.ea.guardian.last_check_minutes_ago)} />
        </Panel>
        <Panel i={2} className="!p-4">
          <p className="eyebrow mb-2">Supervisor</p>
          <HeadStatus status={SUP_TONE[d.supervisor.overall_status] ?? d.supervisor.status} sub={ago(d.supervisor.last_audit_minutes_ago)} />
        </Panel>
        <Panel i={3} className="!p-4">
          <p className="eyebrow mb-2">Strategy Scout</p>
          <HeadStatus status={d.scout.status} sub={ago(d.scout.last_cycle_minutes_ago)} />
        </Panel>
      </div>

      {/* Supervisor */}
      <Panel title="Supervisor — System Heartbeat" i={4}
        right={<StatusDot status={SUP_TONE[d.supervisor.overall_status] ?? 'offline'} label={d.supervisor.overall_status} />}>
        <p className="text-text-secondary text-sm mb-3">{d.supervisor.summary}</p>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <Stat label="Issues Found" value={d.supervisor.issues_found} tone={d.supervisor.issues_found ? 'loss' : 'profit'} />
          <Stat label="Resolved" value={d.supervisor.resolved.length} tone="profit" />
          <Stat label="Unresolved" value={d.supervisor.unresolved.length} tone={d.supervisor.unresolved.length ? 'loss' : undefined} />
        </div>
        {d.supervisor.issues.length > 0 && (
          <div className="space-y-1.5">
            {d.supervisor.issues.map((iss, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className={`font-semibold ${SEV_COLOR[iss.severity] ?? 'text-text-muted'}`}>[{iss.severity}]</span>
                <span className="text-text-secondary">{iss.component}: {iss.description}</span>
              </div>
            ))}
          </div>
        )}
        {d.supervisor.next_action && (
          <p className="text-text-muted text-xs mt-3">Next action: {d.supervisor.next_action}</p>
        )}
      </Panel>

      {/* Strategy Scout funnel */}
      <Panel title="Strategy Scout — Discovery Funnel" i={5}
        right={<span className="text-text-muted text-xs">Cycle #{d.scout.cycles}</span>}>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-4">
          <Stat label="Collected" value={sc.collected ?? 0} />
          <Stat label="Backtested" value={sc.backtested ?? 0} />
          <Stat label="Passed" value={sc.passed ?? 0} tone="accent" />
          <Stat label="Pitched" value={sc.pitched ?? 0} tone="accent" />
          <Stat label="Live" value={sc.live ?? 0} tone="profit" />
          <Stat label="In Pipeline" value={d.scout.total_ideas} />
        </div>
        {d.scout.recent_ideas.length > 0 ? (
          <Table
            columns={[
              { key: 'desc', header: 'Strategy', render: (r: { description: string }) => <span className="text-text-primary">{r.description || '—'}</span> },
              { key: 'src', header: 'Source', render: (r: { source: string }) => <span className="text-text-muted">{r.source || '—'}</span> },
              { key: 'pf', header: 'PF', align: 'right' as const,
                render: (r: { score?: Record<string, number> }) => <span className="font-mono">{r.score?.profit_factor ?? '—'}</span> },
              { key: 'stage', header: 'Stage',
                render: (r: { stage: string }) => <span className="text-accent text-xs font-semibold">{r.stage}</span> },
            ]}
            data={d.scout.recent_ideas}
            keyFn={r => r.description + r.stage}
            emptyText="No ideas yet"
          />
        ) : (
          <p className="text-text-muted text-sm">No strategy ideas collected yet — Scout runs every 8h.</p>
        )}
      </Panel>

      {/* EA Lifecycle */}
      <Panel title="EA Lifecycle Team" i={6}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <p className="eyebrow mb-2">Guardian</p>
            <StatusDot status={d.ea.guardian.status} label={`${d.ea.guardian.anomalies_found} anomalies`} />
            <p className="text-text-muted text-xs mt-2">
              Equity: {d.ea.guardian.account?.equity ?? '—'} · DD {d.ea.guardian.account?.total_dd_pct ?? '—'}%
            </p>
          </div>
          <div>
            <p className="eyebrow mb-2">Coach — EA Stages</p>
            {Object.keys(d.ea.coach.ea_stages).length ? (
              <div className="space-y-1">
                {Object.entries(d.ea.coach.ea_stages).map(([ea, st]) => (
                  <div key={ea} className="flex justify-between text-xs">
                    <span className="text-text-secondary">{ea}</span>
                    <span className="text-accent font-semibold">{st}</span>
                  </div>
                ))}
              </div>
            ) : <p className="text-text-muted text-xs">No EAs tracked yet</p>}
          </div>
          <div>
            <p className="eyebrow mb-2">Validator</p>
            {d.ea.validator.overall_verdict ? (
              <>
                <p className="text-text-primary text-sm font-semibold">{d.ea.validator.ea}: {d.ea.validator.overall_verdict}</p>
                <p className="text-profit text-xs mt-1">✓ {d.ea.validator.compatible_pairs.join(', ') || 'none'}</p>
                <p className="text-loss text-xs">✗ {d.ea.validator.incompatible_pairs.join(', ') || 'none'}</p>
              </>
            ) : <p className="text-text-muted text-xs">No validation run yet</p>}
          </div>
        </div>
        {d.ea.coach.pending_decisions.length > 0 && (
          <div className="mt-4 p-3 rounded-lg bg-warning/[0.06] ring-1 ring-warning/25">
            <p className="eyebrow text-warning mb-2">Awaiting your decision (reply to Maic)</p>
            {d.ea.coach.pending_decisions.map((p, i) => (
              <p key={i} className="text-text-secondary text-xs">• [{p.ea}] {p.question}</p>
            ))}
          </div>
        )}
      </Panel>

      {/* Dev Team */}
      <Panel title="Dev Team" i={7}
        right={<StatusDot status={d.dev.status} label={d.dev.monitor_anomaly ? d.dev.monitor_level : 'nominal'} />}>
        <p className="text-text-secondary text-sm mb-3">{d.dev.monitor_summary}</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="eyebrow mb-2">Recent Code Reviews</p>
            {d.dev.recent_reviews.length ? (
              <ul className="space-y-1">
                {d.dev.recent_reviews.map(r => (
                  <li key={r.name} className="text-text-muted text-xs font-mono truncate">{r.name}</li>
                ))}
              </ul>
            ) : <p className="text-text-muted text-xs">No reviews yet</p>}
          </div>
          <div>
            <p className="eyebrow mb-2">Recent Debug Reports</p>
            {d.dev.recent_debug_reports.length ? (
              <ul className="space-y-1">
                {d.dev.recent_debug_reports.map(r => (
                  <li key={r.name} className="text-text-muted text-xs font-mono truncate">{r.name}</li>
                ))}
              </ul>
            ) : <p className="text-text-muted text-xs">No debug reports yet</p>}
          </div>
        </div>
      </Panel>

      {/* LLM Backends — resilience & fallback telemetry */}
      {llm && llm.agents.length > 0 && (
        <Panel title="LLM Backends — Resilience & Fallback" i={8}
          right={<span className="text-text-muted text-xs">{llm.total_calls} calls tracked</span>}>
          <Table
            columns={[
              { key: 'agent', header: 'Agent', render: (r: LLMStat) => <span className="text-text-primary">{r.agent}</span> },
              { key: 'model', header: 'Last Model', render: (r: LLMStat) => <span className="text-text-muted font-mono text-xs">{r.last_model ?? '—'}</span> },
              { key: 'backend', header: 'Backend',
                render: (r: LLMStat) => <span className={r.last_backend === 'nvidia' ? 'text-warning font-semibold' : 'text-accent'}>{r.last_backend ?? '—'}</span> },
              { key: 'calls', header: 'Calls', align: 'right' as const, render: (r: LLMStat) => <span className="font-mono">{r.calls}</span> },
              { key: 'fb', header: 'Fallback', align: 'right' as const,
                render: (r: LLMStat) => <span className={`font-mono ${r.fallback_pct > 0 ? 'text-warning' : 'text-profit'}`}>{r.fallback_pct}%</span> },
              { key: 'err', header: 'Errors', align: 'right' as const,
                render: (r: LLMStat) => <span className={`font-mono ${r.error_pct > 0 ? 'text-loss' : 'text-text-muted'}`}>{r.error_pct}%</span> },
              { key: 'lat', header: 'Avg ms', align: 'right' as const, render: (r: LLMStat) => <span className="font-mono">{r.avg_latency_ms}</span> },
              { key: 'last', header: 'Last', align: 'right' as const, render: (r: LLMStat) => <span className="text-text-muted text-xs">{ago(r.last_run_minutes_ago)}</span> },
            ]}
            data={llm.agents}
            keyFn={r => r.agent}
            emptyText="No agent LLM calls recorded yet"
          />
          <p className="text-text-muted text-xs mt-3">
            Fallback &gt; 0% means Claude was unavailable and NVIDIA NIM served the call. Sustained fallback ⇒ check Claude API/key.
          </p>
        </Panel>
      )}
    </div>
  )
}
