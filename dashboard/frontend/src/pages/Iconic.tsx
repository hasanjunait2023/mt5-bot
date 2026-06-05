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

interface BoardStrength { currency: string; strength: number; scale7: number }
interface BoardGroupMember { symbol: string; klass: string; score: number; side: string }
interface BoardGroup {
  dominant: string; side: string; leader: string | null
  members: BoardGroupMember[]; rolled_over: boolean
}
interface BoardOpen { symbol: string; side: string; dom: string | null; ticket: number }
interface BoardState {
  running: boolean
  updated_at: string | null
  dry?: boolean
  n_pairs: number
  strength: BoardStrength[]
  groups: BoardGroup[]
  candidates: IconicSignal[]
  open: BoardOpen[]
  managed: Record<string, unknown>[]
}

interface IconicAgentState {
  mode: string
  live_mode: boolean
  paper_trades: number
  paper_pf: number
  paper_pending: string[]
  paper_closed: number
  paper_wins: number
  paper_win_rate: number
  equity: number
  daily_loss_pct: number
  trades_today: Record<string, number>
  updated_at: string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const KLASS_BADGE: Record<string, string> = {
  A: 'text-amber-300 bg-amber-500/15 ring-amber-500/30',
  B: 'text-sky-300 bg-sky-500/15 ring-sky-500/30',
  C: 'text-text-tertiary bg-tint/[0.03] ring-border',
}

const KLASS_BAR: Record<string, string> = {
  A: 'bg-amber-400',
  B: 'bg-sky-400',
  C: 'bg-tint/20',
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

// ── AgentPanel ───────────────────────────────────────────────────────────────
function AgentPanel({ agent }: { agent: IconicAgentState | null }) {
  const PAPER_MIN_TRADES = 20
  const PAPER_MIN_PF     = 1.3

  if (!agent || agent.mode === 'NOT_RUNNING') {
    return (
      <div className="p-4 rounded-lg ring-1 ring-border bg-tint/[0.02] text-center">
        <p className="text-text-tertiary text-sm">
          Agent not running — start <code className="font-mono text-[11px] text-text-secondary">START_ICONIC_AGENT.bat</code>
        </p>
      </div>
    )
  }

  const isLive = agent.live_mode
  const progress = Math.min(100, (agent.paper_trades / PAPER_MIN_TRADES) * 100)
  const pfProgress = Math.min(100, (agent.paper_pf / PAPER_MIN_PF) * 100)
  const modeColor = isLive
    ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
    : 'text-amber-400 bg-amber-500/10 ring-amber-500/30'

  return (
    <div className="space-y-3">
      {/* Mode banner */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold px-2 py-1 rounded ring-1 uppercase tracking-wider ${modeColor}`}>
            {isLive ? '● LIVE' : '◎ PAPER'}
          </span>
          <span className="text-[11px] text-text-tertiary">{agent.mode}</span>
        </div>
        <div className="flex items-center gap-4 text-[11px] font-mono">
          <span className="text-text-secondary">
            Equity <span className="text-text-primary">${agent.equity.toLocaleString()}</span>
          </span>
          <span className={agent.daily_loss_pct > 4 ? 'text-red-400' : 'text-text-secondary'}>
            Daily DD <span className="font-semibold">{agent.daily_loss_pct.toFixed(1)}%</span>
          </span>
        </div>
      </div>

      {/* Paper promotion progress (only in paper mode) */}
      {!isLive && (
        <div className="p-3 rounded-lg bg-tint/[0.02] ring-1 ring-border space-y-2">
          <p className="text-[10px] uppercase tracking-widest text-text-muted font-semibold">
            Paper → Live promotion gate
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="flex justify-between mb-1 text-[11px]">
                <span className="text-text-secondary">Trades</span>
                <span className="font-mono text-text-primary">
                  {agent.paper_trades} / {PAPER_MIN_TRADES}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-tint/[0.06]">
                <div
                  className="h-full rounded-full bg-sky-400 transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex justify-between mb-1 text-[11px]">
                <span className="text-text-secondary">Profit Factor</span>
                <span className={`font-mono ${agent.paper_pf >= PAPER_MIN_PF ? 'text-emerald-400' : 'text-text-primary'}`}>
                  {agent.paper_pf.toFixed(2)} / {PAPER_MIN_PF}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-tint/[0.06]">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${agent.paper_pf >= PAPER_MIN_PF ? 'bg-emerald-400' : 'bg-amber-400'}`}
                  style={{ width: `${pfProgress}%` }}
                />
              </div>
            </div>
          </div>
          <div className="flex gap-4 text-[11px] font-mono text-text-tertiary pt-0.5">
            <span>WR {agent.paper_win_rate.toFixed(1)}%</span>
            <span>{agent.paper_wins}W / {agent.paper_closed - agent.paper_wins}L</span>
            {agent.paper_pending.length > 0 && (
              <span className="text-sky-400/80">Pending: {agent.paper_pending.join(', ')}</span>
            )}
          </div>
        </div>
      )}

      {/* Today's trades */}
      {Object.keys(agent.trades_today).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(agent.trades_today).map(([sym, n]) => (
            <span key={sym}
              className="text-[11px] font-mono px-2 py-0.5 rounded bg-tint/[0.04] ring-1 ring-border text-text-secondary">
              {sym} ×{n}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── ScoreRow ──────────────────────────────────────────────────────────────────
function ScoreRow({ sym, sc }: { sym: string; sc: IconicScore }) {
  return (
    <div className="flex items-center gap-2.5 px-2 py-1.5 rounded-md bg-tint/[0.02] ring-1 ring-border hover:bg-tint/[0.04] transition-colors">
      <span className="font-mono text-[12px] font-semibold text-text-primary w-16 shrink-0">{sym}</span>
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ring-1 shrink-0 ${KLASS_BADGE[sc.klass] ?? KLASS_BADGE.C}`}>
        {sc.klass}
      </span>
      {/* Score bar */}
      <div className="flex-1 h-1.5 rounded-full bg-tint/[0.06] min-w-0">
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
    <div className="p-3 rounded-lg ring-1 ring-border bg-tint/[0.025] space-y-2">
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

// ── BoardPanel — the whole-board view (strength matrix + groups + leaders) ─────
function StrengthMeter({ rows }: { rows: BoardStrength[] }) {
  // scale7 in [-7,+7]; render a centered bar
  return (
    <div className="space-y-1.5">
      {rows.map(r => {
        const pct = Math.min(100, Math.abs(r.scale7) / 7 * 50)   // half-width max
        const strong = r.scale7 >= 0
        return (
          <div key={r.currency} className="flex items-center gap-2">
            <span className="font-mono text-xs font-semibold w-10 shrink-0">{r.currency}</span>
            <div className="relative flex-1 h-3 rounded bg-tint/[0.04] ring-1 ring-border">
              <div className="absolute top-0 bottom-0 left-1/2 w-px bg-tint/20" />
              <div
                className={`absolute top-0 bottom-0 ${strong ? 'bg-emerald-400/70' : 'bg-rose-400/70'}`}
                style={strong
                  ? { left: '50%', width: `${pct}%` }
                  : { right: '50%', width: `${pct}%` }}
              />
            </div>
            <span className={`font-mono text-[11px] w-12 text-right shrink-0 ${
              strong ? 'text-emerald-300' : 'text-rose-300'}`}>
              {r.scale7 >= 0 ? '+' : ''}{r.scale7.toFixed(1)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function BoardPanel({ board }: { board: BoardState | null }) {
  if (!board || board.n_pairs === 0) {
    return (
      <div className="text-text-tertiary text-sm text-center py-8">
        Board feed idle — board_trader not running (runs at cutover, or `--dry`).
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Strength matrix */}
      <div>
        <p className="text-[10px] uppercase tracking-widest font-semibold text-text-muted mb-2">
          Currency strength (±7) · {board.n_pairs} pairs
        </p>
        <StrengthMeter rows={board.strength} />
      </div>
      {/* Groups + leaders */}
      <div>
        <p className="text-[10px] uppercase tracking-widest font-semibold text-text-muted mb-2">
          Correlation groups · leader + roll-over
        </p>
        <div className="space-y-1.5 max-h-[260px] overflow-y-auto pr-0.5">
          {board.groups.length === 0 && (
            <p className="text-text-tertiary text-xs py-2">No A/B groups on the board now.</p>
          )}
          {board.groups.map(g => (
            <div key={g.dominant}
              className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-tint/[0.02] ring-1 ring-border">
              <span className="font-mono text-[11px] font-semibold w-9 shrink-0">{g.dominant}</span>
              <Badge variant={g.side === 'BUY' ? 'buy' : 'sell'}>{g.side}</Badge>
              <span className="text-[11px] text-text-secondary flex-1 truncate">
                leader <span className="text-amber-300 font-mono">{g.leader ?? '—'}</span>
                <span className="text-text-tertiary"> · {g.members.length} member{g.members.length !== 1 ? 's' : ''}</span>
              </span>
              <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded ring-1 shrink-0 ${
                g.rolled_over
                  ? 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/30'
                  : 'text-text-muted bg-tint/[0.03] ring-border'}`}>
                {g.rolled_over ? 'ROLLED OVER' : 'no sister'}
              </span>
            </div>
          ))}
        </div>
        {board.open.length > 0 && (
          <div className="mt-3">
            <p className="text-[10px] uppercase tracking-widest font-semibold text-text-muted mb-1.5">
              Open book ({board.open.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {board.open.map(o => (
                <span key={o.ticket}
                  className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-tint/[0.03] ring-1 ring-border">
                  {o.symbol} <span className={o.side === 'BUY' ? 'text-emerald-300' : 'text-rose-300'}>{o.side}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export function Iconic() {
  const [state, setState]       = useState<IconicState | null>(null)
  const [history, setHistory]   = useState<IconicSignal[]>([])
  const [agent, setAgent]       = useState<IconicAgentState | null>(null)
  const [board, setBoard]       = useState<BoardState | null>(null)

  useEffect(() => {
    let dead = false
    const load = async () => {
      try {
        const [r1, r2, r3, r4] = await Promise.all([
          apiFetch('/iconic/state').then(r => r.ok ? r.json() : null),
          apiFetch('/iconic/signals?limit=30').then(r => r.ok ? r.json() : null),
          apiFetch('/iconic/agent').then(r => r.ok ? r.json() : null),
          apiFetch('/iconic/board').then(r => r.ok ? r.json() : null),
        ])
        if (dead) return
        if (r1) setState(r1 as IconicState)
        if (r2) setHistory((r2 as { signals: IconicSignal[] }).signals || [])
        if (r3) setAgent(r3 as IconicAgentState)
        if (r4) setBoard(r4 as BoardState)
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
          <div key={label} className="p-3 rounded-lg bg-tint/[0.025] ring-1 ring-border text-center">
            <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
            <p className="text-[11px] text-text-tertiary mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Whole-board view — strength matrix + correlation groups + leaders */}
      <Panel i={-2} title={`Board${board?.dry ? ' · dry-observe' : ''}${board?.updated_at ? ' · ' + fmtTime(board.updated_at) : ''}`}>
        <BoardPanel board={board} />
      </Panel>

      {/* Agent status panel */}
      <Panel i={-1} title="Live Agent">
        <AgentPanel agent={agent} />
      </Panel>

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
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-tint/[0.02] ring-1 ring-border">
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
