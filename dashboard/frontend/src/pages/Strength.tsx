import { useEffect, useState } from 'react'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { Badge } from '../components/ui/Badge'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { StrengthMeter, type StrengthRow } from '../components/StrengthMeter'
import { StrengthHeatmap } from '../components/charts/StrengthHeatmap'
import { apiFetch } from '../lib/api'

interface Suggestion { symbol: string; base?: string; quote?: string; diff: number; side: 'BUY' | 'SELL' }
interface SessionData {
  score: Record<string, number>
  tiers: Record<string, string>
  suggestions: Suggestion[]
}
interface StrengthState {
  updated_at: string | null
  tf: string
  pairs_loaded: number
  majors: string[]
  sessions: Record<string, SessionData>
  trade_of_the_day: { symbol: string; side: 'BUY' | 'SELL'; diff: number; session: string } | null
}
interface AgentState {
  mode: string
  active_session: string | null
  open_positions: Record<string, number>
  trades_today: number
  paper_pf: number | null
  paper_trades: number | null
  daily_dd_usd?: number
  dd_limit_usd?: number
  equity?: number
}

const SESSIONS: { key: string; label: string }[] = [
  { key: 'asian', label: 'Asian' },
  { key: 'london_1h', label: 'London' },
  { key: 'newyork', label: 'New York' },
]

function rowsFor(sess: SessionData | undefined, majors: string[]): StrengthRow[] {
  if (!sess) return []
  return majors.map(c => ({ currency: c, score: sess.score?.[c] ?? 0 }))
}

function fmtTime(ts: string | null): string {
  if (!ts) return '—'
  try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch { return ts }
}

export function Strength() {
  const [state, setState] = useState<StrengthState | null>(null)
  const [agent, setAgent] = useState<AgentState | null>(null)
  const [tab, setTab] = useState<string>('newyork')

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [rs, ra] = await Promise.all([
          apiFetch('/strength/state'),
          apiFetch('/strength/agent'),
        ])
        if (rs.ok) { const d = await rs.json(); if (!cancelled) setState(d) }
        if (ra.ok) { const d = await ra.json(); if (!cancelled) setAgent(d) }
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const majors = state?.majors ?? []
  const totd = state?.trade_of_the_day
  const agentLive = agent && agent.mode !== 'OFFLINE'
  const tabSugg = state?.sessions?.[tab]?.suggestions ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Currency Strength & Correlation"
        subtitle="8-major net-pair-win strength (−7…+7) across the Asian, London & New York sessions"
        right={
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <Badge variant="neutral">{state?.tf ?? 'H1'}</Badge>
            <span className="font-mono">{state?.pairs_loaded ?? 0} pairs</span>
            <span className="text-text-muted">·</span>
            <span>updated {fmtTime(state?.updated_at ?? null)}</span>
          </div>
        }
      />

      {/* Top strip — trade of the day + agent status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          label="Trade of the Day"
          value={totd ? totd.symbol : '—'}
          tone={totd?.side === 'SELL' ? 'loss' : 'profit'}
          hero
          sub={totd ? <span>{totd.side} · diff {totd.diff > 0 ? '+' : ''}{totd.diff} · {totd.session}</span> : 'no strong setup'}
        />
        <MetricCard
          label="Active Session"
          value={(agent?.active_session ?? '—').replace('_1h', '')}
          sub={<span className="flex items-center gap-1.5"><StatusDot status={agentLive ? 'running' : 'offline'} /> M3 Strength-Scalp</span>}
        />
        <MetricCard
          label="Agent Mode"
          value={agent?.mode ?? 'OFFLINE'}
          tone={agent?.mode === 'HALTED' ? 'loss' : agentLive ? 'accent' : 'neutral'}
          sub={agent ? `${Object.values(agent.open_positions ?? {}).reduce((a, b) => a + b, 0)} open · ${agent.trades_today ?? 0} today` : ''}
        />
        <MetricCard
          label="Paper PF"
          value={agent?.paper_pf != null ? agent.paper_pf : '—'}
          tone={(agent?.paper_pf ?? 0) >= 1.3 ? 'profit' : 'neutral'}
          sub={agent?.paper_trades != null ? `${agent.paper_trades} trades` : 'live on demo'}
        />
      </div>

      {/* 3-session strength meters */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {SESSIONS.map((s, i) => (
          <Panel key={s.key} title={s.label} i={i}>
            <StrengthMeter rows={rowsFor(state?.sessions?.[s.key], majors)} />
          </Panel>
        ))}
      </div>

      {/* Heatmap + suggestions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel title="Strength Matrix · currency × session">
          <StrengthHeatmap majors={majors} sessions={state?.sessions ?? {}} />
        </Panel>

        <Panel
          title="Pair Suggestions"
          right={
            <div className="flex items-center gap-1">
              {SESSIONS.map(s => (
                <button
                  key={s.key}
                  onClick={() => setTab(s.key)}
                  className={`px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors ${
                    tab === s.key ? 'bg-tint/10 text-text-primary' : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          }
        >
          {tabSugg.length === 0 ? (
            <div className="h-24 grid place-items-center text-text-muted text-xs">
              No qualifying pairs (|diff| ≥ 3) this session
            </div>
          ) : (
            <div className="space-y-1">
              {tabSugg.map((s, idx) => (
                <div key={s.symbol} className="flex items-center gap-3 py-1.5 px-2 rounded-lg hover:bg-tint/[0.03]">
                  <span className="text-text-muted font-mono text-[11px] w-5 shrink-0">{idx + 1}</span>
                  <span className="font-mono text-sm font-semibold w-20">{s.symbol}</span>
                  <Badge variant={s.side === 'BUY' ? 'buy' : 'sell'}>{s.side}</Badge>
                  <div className="flex-1" />
                  <span className="font-mono text-xs text-text-secondary">
                    diff <span className={s.diff > 0 ? 'text-emerald-300' : 'text-rose-300'}>
                      {s.diff > 0 ? '+' : ''}{s.diff}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
