import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { MetricCard } from '../components/ui/MetricCard'

// ── Types ────────────────────────────────────────────────────────────────────

interface HubAccount {
  balance: number | null
  equity: number | null
  daily_pnl: number | null
  daily_dd_pct: number | null
}

interface HubPerformance {
  total_trades: number
  win_rate_pct: number | null
  profit_factor: number | null
  total_pnl: number | null
}

interface PaperGate {
  trades_done: number
  trades_needed: number
  pf_current: number
  pf_needed: number
  ready: boolean
}

interface HubSystem {
  name: string
  id: string
  mode: string
  status: string
  color: string
  group: string
  description: string
  dashboard_page: string
  symbols: string[]
  account: HubAccount
  performance: HubPerformance
  health: {
    stale: boolean
    mt5_connected: boolean
    open_positions: number
    issues: { severity: string; msg: string }[]
    last_heartbeat: string | null
  }
  paper_gate: PaperGate | null
  risk: Record<string, number | boolean>
}

interface HubSummary {
  total_systems: number
  running_count: number
  live_count: number
  paper_count: number
  halted_count: number
  stale_count: number
  combined_daily_pnl: number
  max_daily_dd_pct: number
  any_critical: boolean
}

interface HubData {
  systems: HubSystem[]
  summary: HubSummary
  global_rules: Record<string, number | boolean>
}

interface OrchService {
  id: string
  name: string
  pid: number | null
  status: string
  fails: number
  restarts: number
  health_type: string
}

interface OrchData {
  running: boolean
  reason?: string
  orchestrator_pid?: number
  state_age_seconds?: number
  services: OrchService[]
  summary: {
    total?: number
    running?: number
    starting?: number
    restarting?: number
    failed?: number
    total_restarts?: number
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function statusDot(status: string) {
  const map: Record<string, string> = {
    running: 'bg-profit animate-pulse2',
    idle:    'bg-profit/50',
    halted:  'bg-loss animate-pulse2',
    stopped: 'bg-text-muted',
    stale:   'bg-amber-400/80 animate-pulse2',
    error:   'bg-loss',
  }
  return map[status] ?? 'bg-text-muted'
}

function modeBadge(mode: string) {
  const map: Record<string, string> = {
    live:      'bg-profit/15 text-profit border border-profit/25',
    paper:     'bg-accent/15 text-accent border border-accent/25',
    'dry-run': 'bg-text-muted/15 text-text-muted border border-border',
  }
  return map[mode] ?? 'bg-text-muted/15 text-text-muted border border-border'
}

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null) return '—'
  return v.toFixed(digits)
}

function pct(done: number, needed: number): number {
  return Math.min(100, Math.round((done / needed) * 100))
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PaperGateBar({ gate }: { gate: PaperGate }) {
  const tradePct = pct(gate.trades_done, gate.trades_needed)
  const pfOk = gate.pf_current >= gate.pf_needed

  return (
    <div className="mt-3 space-y-2">
      <p className="eyebrow">Paper Gate</p>
      <div className="space-y-1.5">
        <div className="flex justify-between text-[11px] text-text-muted">
          <span>Trades {gate.trades_done}/{gate.trades_needed}</span>
          <span>{tradePct}%</span>
        </div>
        <div className="h-1 rounded-full bg-white/[0.06] overflow-hidden">
          <div
            className="h-full rounded-full bg-accent transition-all duration-700"
            style={{ width: `${tradePct}%` }}
          />
        </div>
        <div className="flex justify-between text-[11px]">
          <span className="text-text-muted">PF {fmt(gate.pf_current)} / {gate.pf_needed}</span>
          <span className={pfOk ? 'text-profit' : 'text-text-muted'}>{pfOk ? '✓ PF OK' : 'need ≥1.3'}</span>
        </div>
      </div>
      {gate.ready && (
        <div className="mt-1 text-[11px] font-semibold text-profit text-center">
          ✓ Ready for live
        </div>
      )}
    </div>
  )
}

function SystemCard({ sys }: { sys: HubSystem }) {
  const isLive   = sys.mode === 'live'
  const isHalted = sys.status === 'halted'
  const isStale  = sys.status === 'stale'

  const ddPct  = sys.account.daily_dd_pct ?? 0
  const ddTone = ddPct >= 16 ? 'loss' : ddPct >= 10 ? 'loss' : 'neutral'

  const pnlTone = (sys.account.daily_pnl ?? 0) >= 0 ? 'profit' : 'loss'

  return (
    <div className={`glass relative overflow-hidden flex flex-col gap-4 p-5 ring-1 transition-all duration-200 ${
      isHalted ? 'ring-loss/30' : isStale ? 'ring-amber-400/20' : 'ring-border'
    }`}>
      {/* top sheen */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/12 to-transparent" />

      {/* header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 ${statusDot(sys.status)}`} />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-text-primary truncate">{sys.name}</p>
            <p className="text-[11px] text-text-muted truncate mt-0.5">{sys.description}</p>
          </div>
        </div>
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full shrink-0 ${modeBadge(sys.mode)}`}>
          {sys.mode}
        </span>
      </div>

      {/* metrics row */}
      <div className="grid grid-cols-2 gap-2">
        {isLive ? (
          <>
            <MetricCard
              label="Daily PnL"
              value={sys.account.daily_pnl ?? 0}
              prefix="$"
              tone={pnlTone}
              positive={(sys.account.daily_pnl ?? 0) >= 0}
            />
            <MetricCard
              label="Daily DD"
              value={ddPct}
              suffix="%"
              tone={ddTone}
              positive={false}
            />
          </>
        ) : (
          <>
            <MetricCard
              label="Paper Trades"
              value={sys.performance.total_trades}
              tone="neutral"
            />
            <MetricCard
              label="Profit Factor"
              value={sys.performance.profit_factor ?? 0}
              tone={(sys.performance.profit_factor ?? 0) >= 1.3 ? 'profit' : 'neutral'}
            />
          </>
        )}
      </div>

      {/* secondary stats */}
      <div className="flex gap-4 text-[11px] text-text-muted">
        {sys.performance.win_rate_pct != null && (
          <span>WR <span className="text-text-secondary font-mono">{fmt(sys.performance.win_rate_pct)}%</span></span>
        )}
        <span>Pos <span className="text-text-secondary font-mono">{sys.health.open_positions}</span></span>
        <span className="truncate">{sys.symbols.slice(0, 3).join(' · ')}{sys.symbols.length > 3 ? ` +${sys.symbols.length - 3}` : ''}</span>
      </div>

      {/* paper gate progress */}
      {sys.paper_gate && !isLive && (
        <PaperGateBar gate={sys.paper_gate} />
      )}

      {/* issues */}
      {sys.health.issues.length > 0 && (
        <div className="space-y-1">
          {sys.health.issues.map((iss, i) => (
            <div key={i} className="flex gap-2 text-[11px] text-loss bg-loss/5 rounded px-2 py-1">
              <span>⚠</span><span>{iss.msg}</span>
            </div>
          ))}
        </div>
      )}

      {/* footer link */}
      <Link
        to={sys.dashboard_page}
        className="mt-auto text-[11px] text-accent/70 hover:text-accent transition-colors"
      >
        View details →
      </Link>
    </div>
  )
}

function ControlPlane({ orch }: { orch: OrchData }) {
  const s = orch.summary || {}
  const down = !orch.running

  return (
    <div className={`glass ring-1 p-4 ${down ? 'ring-loss/40' : 'ring-border'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span className={`w-2 h-2 rounded-full ${down ? 'bg-loss animate-pulse2' : 'bg-profit animate-pulse2'}`} />
          <div>
            <p className="eyebrow">Control Plane · Orchestrator</p>
            <p className="text-sm font-semibold text-text-primary">
              {down ? 'Supervisor DOWN' : `Supervising ${s.total ?? 0} processes`}
            </p>
          </div>
        </div>
        <div className="flex gap-4 text-[11px] text-text-muted">
          <span>Up <span className="text-profit font-mono">{s.running ?? 0}/{s.total ?? 0}</span></span>
          {(s.failed ?? 0) > 0 && <span className="text-loss">Failed <span className="font-mono">{s.failed}</span></span>}
          <span>Restarts <span className="text-text-secondary font-mono">{s.total_restarts ?? 0}</span></span>
        </div>
      </div>

      {down && (
        <p className="text-[11px] text-loss mb-2">{orch.reason ?? 'orchestrator not reporting'}</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 gap-1.5">
        {orch.services.map(svc => {
          const ok = svc.status === 'running'
          const bad = svc.status === 'failed' || svc.status === 'dead'
          return (
            <div key={svc.id} className="flex items-center gap-2 text-[11px] bg-white/[0.03] rounded px-2 py-1.5">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                ok ? 'bg-profit' : bad ? 'bg-loss animate-pulse2' : 'bg-amber-400/80'
              }`} />
              <span className="text-text-secondary truncate flex-1">{svc.name}</span>
              {svc.restarts > 0 && (
                <span className="text-text-muted font-mono shrink-0" title="auto-restarts">↻{svc.restarts}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export function Hub() {
  const [data, setData] = useState<HubData | null>(null)
  const [orch, setOrch] = useState<OrchData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    apiFetch('/api/hub')
      .then(r => r.json())
      .then(setData)
      .catch(e => setError(String(e)))
    apiFetch('/api/orchestrator')
      .then(r => r.json())
      .then(setOrch)
      .catch(() => { /* control plane optional */ })
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [])

  if (error) return (
    <div className="p-8 text-loss text-sm">Registry error: {error}</div>
  )
  if (!data) return (
    <div className="p-8 text-text-muted text-sm animate-pulse">Loading Command Hub…</div>
  )

  const { systems, summary, global_rules } = data
  const criticalDd = summary.any_critical

  return (
    <div className="p-6 space-y-4 md:space-y-6 max-w-6xl mx-auto">

      {/* page header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow mb-1">Trading Operations</p>
          <h1 className="text-xl font-bold text-text-primary tracking-tight">Command Hub</h1>
        </div>
        <span className="text-[11px] text-text-muted font-mono">
          {systems.length} systems · auto-refresh 10s
        </span>
      </div>

      {/* critical alert */}
      {criticalDd && (
        <div className="glass ring-1 ring-loss/40 p-4 flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-loss animate-pulse2 shrink-0" />
          <p className="text-sm text-loss font-semibold">
            Daily drawdown approaching limit — {fmt(summary.max_daily_dd_pct)}% of {String(global_rules.max_daily_dd_pct ?? 20)}% max
          </p>
        </div>
      )}

      {/* control plane (orchestrator supervision) */}
      {orch && <ControlPlane orch={orch} />}

      {/* summary bar */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Systems"  value={summary.total_systems}  tone="neutral" />
        <MetricCard label="Running"  value={summary.running_count}   tone="profit"  />
        <MetricCard label="Live"     value={summary.live_count}      tone="profit"  />
        <MetricCard label="Paper"    value={summary.paper_count}     tone="accent"  />
        <MetricCard label="Halted"   value={summary.halted_count}    tone={summary.halted_count > 0 ? 'loss' : 'neutral'} />
        <MetricCard
          label="Daily PnL"
          value={summary.combined_daily_pnl}
          prefix="$"
          tone={summary.combined_daily_pnl >= 0 ? 'profit' : 'loss'}
          positive={summary.combined_daily_pnl >= 0}
          hero
        />
      </div>

      {/* global rules bar */}
      <div className="glass ring-1 ring-border p-3 flex flex-wrap gap-4 text-[11px] text-text-muted">
        <span className="font-semibold text-text-secondary uppercase tracking-widest mr-1">Global Rules:</span>
        <span>Max DD <span className="text-text-secondary font-mono">{String(global_rules.max_daily_dd_pct ?? 20)}%</span></span>
        <span>Paper Gate <span className="text-text-secondary font-mono">{String(global_rules.min_paper_trades ?? 20)} trades / PF {String(global_rules.min_paper_pf ?? 1.3)}</span></span>
        <span>Max Risk <span className="text-text-secondary font-mono">{String(global_rules.max_risk_pct_per_trade ?? 2)}% / trade</span></span>
        <span>News Block <span className="text-text-secondary font-mono">{global_rules.no_trade_during_news ? 'ON' : 'OFF'}</span></span>
      </div>

      {/* system cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-2 gap-4">
        {systems.map(sys => (
          <SystemCard key={sys.id} sys={sys} />
        ))}
        {systems.length === 0 && (
          <div className="col-span-2 glass ring-1 ring-border p-10 text-center text-text-muted text-sm">
            No strategies registered. Drop a YAML into <code className="font-mono text-accent">trading_agents/registry/strategies/</code>
          </div>
        )}
      </div>

    </div>
  )
}
