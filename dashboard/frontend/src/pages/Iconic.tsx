import { useEffect, useState } from 'react'
import { Panel } from '../components/ui/Panel'
import { Badge } from '../components/ui/Badge'
import { StatusDot } from '../components/ui/StatusDot'
import { apiFetch } from '../lib/api'
import { useWebSocket } from '../hooks/useWebSocket'

// ── Types ─────────────────────────────────────────────────────────────────────
interface IconicScore {
  klass: 'A' | 'B' | 'C'
  score: number
  side: 'BUY' | 'SELL'
  is_leader: boolean
  reasons: string[]
  flags: string[]
  ts: string
}

interface IconicSignal {
  symbol: string
  side: 'BUY' | 'SELL'
  klass: 'A' | 'B'
  type: string
  entry: number
  stop: number
  tp_final: number
  tp_scale: number[]
  risk: number
  rr_final: number
  score: number
  is_leader: boolean
  volume_dead: boolean
  reasons: string[]
  flags: string[]
  ts: string
}

interface IconicState {
  running: boolean
  updated_at: string | null
  signals_live: Record<string, IconicSignal>
  scores_all: Record<string, IconicScore>
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const KLASS_BADGE: Record<string, string> = {
  A: 'text-amber-300 bg-amber-500/15 ring-amber-500/30',
  B: 'text-sky-300 bg-sky-500/15 ring-sky-500/30',
  C: 'text-text-tertiary bg-white/[0.03] ring-border',
}

const KLASS_BAR: Record<string, string> = {
  A: 'bg-amber-400',
  B: 'bg-sky-400',
  C: 'bg-white/20',
}

function fmtPrice(p: number): string {
  if (p === 0) return '—'
  if (p < 10)   return p.toFixed(5)
  if (p < 1000) return p.toFixed(3)
  return p.toFixed(2)
}

function fmtTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}

// ── ScoreRow ──────────────────────────────────────────────────────────────────
function ScoreRow({ sym, sc }: { sym: string; sc: IconicScore }) {
  return (
    <div className="flex items-center gap-2.5 px-2 py-1.5 rounded-md bg-white/[0.02] ring-1 ring-border hover:bg-white/[0.04] transition-colors">
      <span className="font-mono text-[12px] font-semibold text-text-primary w-16 shrink-0">{sym}</span>
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ring-1 shrink-0 ${KLASS_BADGE[sc.klass] ?? KLASS_BADGE.C}`}>
        {sc.klass}
      </span>
      {/* Score bar */}
      <div className="flex-1 h-1.5 rounded-full bg-white/[0.06] min-w-0">
        <div
          className={`h-full rounded-full transition-all duration-500 ${KLASS_BAR[sc.klass] ?? KLASS_BAR.C}`}
          style={{ width: `${Math.min(100, sc.score)}%` }}
        />
      </div>
      <span className="text-[11px] font-mono text-text-secondary w-8 text-right shrink-0">
        {sc.score.toFixed(0)}
      </span>
      <Badge variant={sc.side === 'BUY' ? 'buy' : 'sell'}>{sc.side}</Badge>
      {sc.is_leader && (
        <span className="text-[9px] uppercase tracking-widest text-amber-400 font-semibold shrink-0">
          leader
        </span>
      )}
    </div>
  )
}

// ── SignalCard ────────────────────────────────────────────────────────────────
function SignalCard({ sig }: { sig: IconicSignal }) {
  return (
    <div className="p-3 rounded-lg ring-1 ring-border bg-white/[0.025] space-y-2">
      {/* Header row */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-[13px] text-text-primary">{sig.symbol}</span>
          <Badge variant={sig.side === 'BUY' ? 'buy' : 'sell'}>{sig.side}</Badge>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ring-1 ${KLASS_BADGE[sig.klass] ?? KLASS_BADGE.C}`}>
            {sig.klass}
          </span>
          <span className="text-[10px] text-text-tertiary uppercase tracking-wide">{sig.type}</span>
        </div>
        <div className="flex items-center gap-2">
          {sig.volume_dead && (
            <span className="text-[9px] text-emerald-400 font-semibold uppercase tracking-wide">
              vol dead ✓
            </span>
          )}
          {sig.is_leader && (
            <span className="text-[9px] text-amber-400 font-semibold uppercase tracking-wide">
              leader
            </span>
          )}
          <span className="text-[10px] text-text-tertiary">{fmtTime(sig.ts)}</span>
        </div>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-4 gap-2 text-[11px] font-mono">
        <div>
          <p className="text-text-tertiary text-[9px] uppercase tracking-wide mb-0.5">Entry</p>
          <p className="text-text-primary">{fmtPrice(sig.entry)}</p>
        </div>
        <div>
          <p className="text-text-tertiary text-[9px] uppercase tracking-wide mb-0.5">Stop</p>
          <p className="text-red-400">{fmtPrice(sig.stop)}</p>
        </div>
        <div>
          <p className="text-text-tertiary text-[9px] uppercase tracking-wide mb-0.5">TP</p>
          <p className="text-emerald-400">{fmtPrice(sig.tp_final)}</p>
        </div>
        <div>
          <p className="text-text-tertiary text-[9px] uppercase tracking-wide mb-0.5">R:R</p>
          <p className={sig.rr_final >= 2 ? 'text-emerald-400' : 'text-text-primary'}>
            {sig.rr_final.toFixed(1)}R
          </p>
        </div>
      </div>

      {/* Scale-out levels */}
      {sig.tp_scale.length > 0 && (
        <p className="text-[10px] font-mono text-text-tertiary">
          Scale-out: {sig.tp_scale.map(p => fmtPrice(p)).join(' → ')}
        </p>
      )}

      {/* Flags */}
      {sig.flags.length > 0 && (
        <div className="text-[10px] text-amber-300/80 space-y-0.5">
          {sig.flags.map((f, i) => <p key={i}>{f}</p>)}
        </div>
      )}

      {/* Reasons */}
      <div className="text-[10px] text-text-tertiary space-y-0.5">
        {sig.reasons.slice(0, 3).map((r, i) => <p key={i}>{r}</p>)}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export function Iconic() {
  const [state, setState]     = useState<IconicState | null>(null)
  const [history, setHistory] = useState<IconicSignal[]>([])

  useEffect(() => {
    let dead = false
    const load = async () => {
      try {
        const [r1, r2] = await Promise.all([
          apiFetch('/iconic/state').then(r => r.ok ? r.json() : null),
          apiFetch('/iconic/signals?limit=30').then(r => r.ok ? r.json() : null),
        ])
        if (dead) return
        if (r1) setState(r1 as IconicState)
        if (r2) setHistory((r2 as { signals: IconicSignal[] }).signals || [])
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 10_000)
    return () => { dead = true; clearInterval(id) }
  }, [])

  // Live WS push — new signal fires
  useWebSocket('iconic_signal', (data) => {
    const sig = data as IconicSignal
    setState(prev => prev ? {
      ...prev,
      signals_live: { ...prev.signals_live, [sig.symbol]: sig },
    } : prev)
    setHistory(prev => [sig, ...prev].slice(0, 30))
  })

  const scores  = state?.scores_all  ?? {}
  const liveSigs = Object.values(state?.signals_live ?? {})

  // Sort: A → B → C; within class by score desc
  const sortedScores = Object.entries(scores).sort(([, a], [, b]) => {
    const ord: Record<string, number> = { A: 0, B: 1, C: 2 }
    const kd = (ord[a.klass] ?? 3) - (ord[b.klass] ?? 3)
    return kd !== 0 ? kd : b.score - a.score
  })

  const aCount      = sortedScores.filter(([, s]) => s.klass === 'A').length
  const bCount      = sortedScores.filter(([, s]) => s.klass === 'B').length
  const leaderCount = sortedScores.filter(([, s]) => s.is_leader).length

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Iconic Trader</h1>
          <p className="text-text-secondary text-sm mt-1">
            Urban Forex Set 1/Set 2 · Volume + Correlation + Purpose · A/B/C confluence
          </p>
        </div>
        <div className="flex items-center gap-3">
          {state?.updated_at && (
            <span className="text-[11px] text-text-tertiary font-mono">
              {fmtTime(state.updated_at)}
            </span>
          )}
          <StatusDot status={state?.running ? 'running' : 'offline'} />
        </div>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
        {[
          { label: 'A-class',     value: aCount,                  color: 'text-amber-400' },
          { label: 'B-class',     value: bCount,                  color: 'text-sky-400'   },
          { label: 'Live signals',value: liveSigs.length,          color: 'text-emerald-400' },
          { label: 'Scanning',    value: sortedScores.length,      color: 'text-text-primary' },
          { label: 'Leaders',     value: leaderCount,              color: 'text-amber-300' },
        ].map(({ label, value, color }) => (
          <div key={label} className="p-3 rounded-lg bg-white/[0.025] ring-1 ring-border text-center">
            <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">

        {/* Left: A/B/C Scoreboard */}
        <Panel i={0} title={`Confluence Scoreboard (${sortedScores.length})`}>
          {sortedScores.length === 0 ? (
            <div className="text-text-tertiary text-sm text-center py-8">
              Waiting for first scan tick — check signal engine is running.
            </div>
          ) : (
            <div className="space-y-1 max-h-[520px] overflow-y-auto pr-0.5">
              {/* Class section headers */}
              {(['A', 'B', 'C'] as const).map(klass => {
                const rows = sortedScores.filter(([, s]) => s.klass === klass)
                if (rows.length === 0) return null
                return (
                  <div key={klass}>
                    <p className={`text-[10px] uppercase tracking-widest font-semibold py-1.5 ${
                      klass === 'A' ? 'text-amber-400/70' :
                      klass === 'B' ? 'text-sky-400/70' : 'text-text-muted'
                    }`}>
                      {klass === 'A' ? '★ Class A — strong confluence' :
                       klass === 'B' ? '◎ Class B — good confluence' :
                                       '· Class C — weak / no trade'}
                    </p>
                    {rows.map(([sym, sc]) => (
                      <ScoreRow key={sym} sym={sym} sc={sc} />
                    ))}
                  </div>
                )
              })}
            </div>
          )}
        </Panel>

        {/* Right: Live signals + history */}
        <div className="space-y-4">

          {/* Live signals */}
          <Panel i={1} title={`Live Signals (${liveSigs.length})`}>
            {liveSigs.length === 0 ? (
              <div className="text-text-tertiary text-sm text-center py-5">
                No A/B signals with valid Set 1/2 pattern right now.
              </div>
            ) : (
              <div className="space-y-3 max-h-[300px] overflow-y-auto pr-0.5">
                {liveSigs.map((sig, i) => <SignalCard key={i} sig={sig} />)}
              </div>
            )}
          </Panel>

          {/* Signal history */}
          <Panel i={2} title="Signal History">
            {history.length === 0 ? (
              <div className="text-text-tertiary text-sm text-center py-5">
                No signals fired this session yet.
              </div>
            ) : (
              <div className="space-y-1.5 max-h-[340px] overflow-y-auto pr-0.5">
                {history.map((sig, i) => (
                  <div key={i}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-white/[0.02] ring-1 ring-border">
                    <span className="font-mono text-[11px] font-semibold w-14 shrink-0 text-text-primary">
                      {sig.symbol}
                    </span>
                    <Badge variant={sig.side === 'BUY' ? 'buy' : 'sell'}>{sig.side}</Badge>
                    <span className={`text-[10px] font-bold px-1 py-0.5 rounded ring-1 shrink-0 ${KLASS_BADGE[sig.klass] ?? KLASS_BADGE.C}`}>
                      {sig.klass}
                    </span>
                    <span className="text-[10px] text-text-tertiary uppercase shrink-0">{sig.type}</span>
                    <span className="text-[10px] font-mono text-text-secondary flex-1 text-right truncate">
                      {fmtPrice(sig.entry)} → {fmtPrice(sig.tp_final)} · {sig.rr_final.toFixed(1)}R
                    </span>
                    <span className="text-[9px] text-text-tertiary shrink-0">{fmtTime(sig.ts)}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}
