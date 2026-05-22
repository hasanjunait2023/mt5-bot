import { useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'
import { MetricCard } from '../components/ui/MetricCard'
import { Badge } from '../components/ui/Badge'
import { Panel } from '../components/ui/Panel'

// ── Types ──────────────────────────────────────────────────────────────────────
interface StratStats {
  trades: number
  pf: number
  wr: number
  live: boolean
}

interface ScalpState {
  mode: string
  strategies: string[]
  symbol: string
  paper_trades: number
  paper_pf: number
  paper_pending: string[]
  paper_closed: number
  paper_wins: number
  paper_win_rate: number
  strat_stats: Record<string, StratStats>
  equity: number
  daily_loss_pct: number
  trades_today: number
  updated_at: string | null
}

interface PaperTrade {
  symbol: string
  strategy: string
  side: string
  entry: number
  stop: number
  tp: number
  pnl?: number
  exit?: string
  status: string
  ts_open: string
  ts_close?: string
}

const EMPTY_STATE: ScalpState = {
  mode: 'NOT_RUNNING', strategies: ['GS11', 'GS07'], symbol: 'XAUUSD',
  paper_trades: 0, paper_pf: 0, paper_pending: [],
  paper_closed: 0, paper_wins: 0, paper_win_rate: 0,
  strat_stats: {}, equity: 0, daily_loss_pct: 0, trades_today: 0, updated_at: null,
}

const PAPER_MIN_TRADES = 20
const PAPER_MIN_PF = 1.3

const STRAT_LABEL: Record<string, string> = {
  GS11: 'Opening Range',
  GS07: 'Liquidity Sweep',
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtTime(ts: string | undefined): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleTimeString('en', {
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return ts }
}

function fmtPrice(p: number): string {
  if (p >= 100) return p.toFixed(2)
  return p.toFixed(5)
}

// ── StratCard ─────────────────────────────────────────────────────────────────
function StratCard({ name, stats }: { name: string; stats: StratStats }) {
  const progress     = Math.min(100, (stats.trades / PAPER_MIN_TRADES) * 100)
  const pfProgress   = Math.min(100, (stats.pf / PAPER_MIN_PF) * 100)
  const isReady      = stats.trades >= PAPER_MIN_TRADES && stats.pf >= PAPER_MIN_PF
  const modeColor    = stats.live
    ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
    : 'text-amber-400 bg-amber-500/10 ring-amber-500/30'

  return (
    <div className="glass rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-text-primary font-semibold tracking-wide">{name}</p>
          <p className="text-[11px] text-text-tertiary mt-0.5">{STRAT_LABEL[name] ?? ''}</p>
        </div>
        <span className={`text-[11px] font-bold px-2 py-1 rounded ring-1 uppercase tracking-wider ${modeColor}`}>
          {stats.live ? '● LIVE' : '◎ PAPER'}
        </span>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="text-center">
          <p className="eyebrow">Trades</p>
          <p className="font-mono font-bold text-lg text-text-primary">{stats.trades}</p>
        </div>
        <div className="text-center">
          <p className="eyebrow">PF</p>
          <p className={`font-mono font-bold text-lg ${stats.pf >= 1.3 ? 'text-profit' : stats.pf >= 1.0 ? 'text-amber-400' : 'text-loss'}`}>
            {stats.pf > 0 ? stats.pf.toFixed(2) : '—'}
          </p>
        </div>
        <div className="text-center">
          <p className="eyebrow">WR%</p>
          <p className={`font-mono font-bold text-lg ${stats.wr >= 50 ? 'text-profit' : 'text-text-secondary'}`}>
            {stats.wr > 0 ? `${stats.wr.toFixed(1)}%` : '—'}
          </p>
        </div>
      </div>

      {/* Promotion progress */}
      {!stats.live && (
        <div className="space-y-2">
          <div>
            <div className="flex justify-between text-[10px] text-text-muted mb-1">
              <span>Trades to gate</span>
              <span>{stats.trades}/{PAPER_MIN_TRADES}</span>
            </div>
            <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
              <div className="h-full rounded-full bg-accent/60 transition-all duration-500"
                   style={{ width: `${progress}%` }} />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-[10px] text-text-muted mb-1">
              <span>PF to gate</span>
              <span>{stats.pf.toFixed(2)}/{PAPER_MIN_PF}</span>
            </div>
            <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-500 ${isReady ? 'bg-profit' : 'bg-accent/60'}`}
                   style={{ width: `${pfProgress}%` }} />
            </div>
          </div>
          {isReady && (
            <p className="text-[11px] text-profit font-semibold text-center">
              Gate passed — promote to LIVE on next restart
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── TradesTable ───────────────────────────────────────────────────────────────
function TradesTable({ trades }: { trades: PaperTrade[] }) {
  if (!trades.length) {
    return <p className="text-text-tertiary text-sm text-center py-6">No paper trades yet.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] font-mono border-collapse">
        <thead>
          <tr className="text-text-muted border-b border-white/[0.06]">
            {['Strategy', 'Side', 'Entry', 'SL', 'TP', 'PnL', 'Exit', 'Time'].map(h => (
              <th key={h} className="text-left px-2 py-1.5 font-medium eyebrow">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnlPos = (t.pnl ?? 0) >= 0
            return (
              <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                <td className="px-2 py-1.5">
                  <span className="text-accent text-[10px]">{t.strategy}</span>
                </td>
                <td className="px-2 py-1.5">
                  <Badge variant={t.side === 'BUY' ? 'buy' : 'sell'}>{t.side}</Badge>
                </td>
                <td className="px-2 py-1.5 text-text-secondary">{fmtPrice(t.entry)}</td>
                <td className="px-2 py-1.5 text-text-muted">{fmtPrice(t.stop)}</td>
                <td className="px-2 py-1.5 text-text-muted">{fmtPrice(t.tp)}</td>
                <td className={`px-2 py-1.5 font-bold ${pnlPos ? 'text-profit' : 'text-loss'}`}>
                  {t.pnl !== undefined ? `${pnlPos ? '+' : ''}${t.pnl.toFixed(4)}` : '—'}
                </td>
                <td className="px-2 py-1.5 text-text-muted">{t.exit ?? 'open'}</td>
                <td className="px-2 py-1.5 text-text-muted">{fmtTime(t.ts_close ?? t.ts_open)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Iconic Scalp types ────────────────────────────────────────────────────────
interface SymStats {
  paper_trades: number
  paper_pf: number
  paper_wr: number
  live: boolean
}

interface IconicScalpAgentState {
  mode: string
  live_mode: boolean
  paper_trades: number
  paper_pf: number
  paper_pf_live: number
  paper_pending: Array<{ symbol: string; side: string; entry: number; stop: number; tp: number; partial_done: boolean }>
  paper_closed: number
  paper_wins: number
  paper_win_rate: number
  partial_exits_taken: number
  equity: number
  daily_loss_pct: number
  trades_today: Record<string, number>
  sym_live: Record<string, boolean>
  sym_stats: Record<string, SymStats>
  updated_at: string | null
}

interface IconicScalpTrade {
  symbol: string
  side: string
  entry: number
  stop: number
  tp: number
  klass: string
  pnl?: number
  exit?: string
  partial_done?: boolean
  partial_pnl?: number
  status: string
  ts_open: string
  ts_close?: string
}

const ICONIC_EMPTY: IconicScalpAgentState = {
  mode: 'NOT_RUNNING', live_mode: false,
  paper_trades: 0, paper_pf: 0, paper_pf_live: 0,
  paper_pending: [], paper_closed: 0, paper_wins: 0, paper_win_rate: 0,
  partial_exits_taken: 0, equity: 0, daily_loss_pct: 0,
  trades_today: {}, sym_live: {}, sym_stats: {}, updated_at: null,
}

// ── SymPromotionGrid ──────────────────────────────────────────────────────────
function SymPromotionGrid({
  symStats, symLive,
}: { symStats: Record<string, SymStats>; symLive: Record<string, boolean> }) {
  const entries = Object.entries(symStats)
  if (!entries.length) return null

  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <p className="eyebrow">Symbol Gate Progress</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {entries.map(([sym, s]) => {
          const live         = symLive[sym] ?? s.live ?? false
          const tradesProg   = Math.min(100, (s.paper_trades / PAPER_MIN_TRADES) * 100)
          const pfProg       = Math.min(100, (s.paper_pf / PAPER_MIN_PF) * 100)
          const gateReady    = s.paper_trades >= PAPER_MIN_TRADES && s.paper_pf >= PAPER_MIN_PF
          const isProven     = sym === 'NZDUSD'

          return (
            <div key={sym} className={`rounded-lg p-3 space-y-2 ring-1 ${
              live
                ? 'bg-profit/10 ring-profit/30'
                : gateReady
                  ? 'bg-accent/10 ring-accent/30'
                  : 'bg-white/[0.03] ring-white/[0.06]'
            }`}>
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-mono text-sm font-bold text-text-primary">{sym}</span>
                  {isProven && (
                    <span className="ml-1.5 text-[9px] text-profit uppercase tracking-wide">proven</span>
                  )}
                </div>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ring-1 uppercase ${
                  live
                    ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
                    : 'text-amber-400 bg-amber-500/10 ring-amber-500/30'
                }`}>
                  {live ? '● LIVE' : '◎ PAPER'}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-1 text-center">
                <div>
                  <p className="text-[9px] text-text-muted uppercase tracking-wide">Trades</p>
                  <p className="font-mono text-sm font-bold text-text-primary">{s.paper_trades}</p>
                </div>
                <div>
                  <p className="text-[9px] text-text-muted uppercase tracking-wide">PF</p>
                  <p className={`font-mono text-sm font-bold ${
                    s.paper_pf >= 1.3 ? 'text-profit' : s.paper_pf >= 1.0 ? 'text-amber-400' : 'text-text-secondary'
                  }`}>
                    {s.paper_pf > 0 ? s.paper_pf.toFixed(2) : '—'}
                  </p>
                </div>
                <div>
                  <p className="text-[9px] text-text-muted uppercase tracking-wide">WR%</p>
                  <p className={`font-mono text-sm font-bold ${s.paper_wr >= 55 ? 'text-profit' : 'text-text-secondary'}`}>
                    {s.paper_wr > 0 ? `${s.paper_wr.toFixed(0)}%` : '—'}
                  </p>
                </div>
              </div>

              {!live && (
                <div className="space-y-1">
                  <div className="flex items-center gap-1">
                    <div className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                      <div className="h-full rounded-full bg-accent/50 transition-all"
                           style={{ width: `${tradesProg}%` }} />
                    </div>
                    <span className="text-[9px] text-text-muted font-mono w-8 text-right">
                      {s.paper_trades}/{PAPER_MIN_TRADES}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${gateReady ? 'bg-profit' : 'bg-accent/50'}`}
                           style={{ width: `${pfProg}%` }} />
                    </div>
                    <span className={`text-[9px] font-mono w-8 text-right ${gateReady ? 'text-profit' : 'text-text-muted'}`}>
                      {s.paper_pf > 0 ? s.paper_pf.toFixed(2) : '—'}
                    </span>
                  </div>
                  {gateReady && (
                    <p className="text-[10px] text-profit font-semibold text-center">Gate passed — promoting</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── IconicScalpPanel ──────────────────────────────────────────────────────────
function IconicScalpPanel({ state, trades }: { state: IconicScalpAgentState; trades: IconicScalpTrade[] }) {
  const isRunning  = state.mode !== 'NOT_RUNNING' && state.mode !== 'STOPPED'
  const isHalted   = state.mode === 'HALTED'

  const modeColor = state.live_mode
    ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
    : isHalted
      ? 'text-loss bg-loss/10 ring-loss/30'
      : isRunning
        ? 'text-amber-400 bg-amber-500/10 ring-amber-500/30'
        : 'text-text-muted bg-white/[0.03] ring-border'

  return (
    <div className="space-y-4">
      {/* Title row */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-text-primary tracking-tight">Iconic Scalp Agent</h2>
          <p className="text-text-tertiary text-xs mt-0.5">M15 · 5-symbol scan · NZDUSD execute + EUR/GBP/CHF/AUD paper</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold px-2.5 py-1 rounded ring-1 uppercase tracking-wider ${modeColor}`}>
            {state.live_mode ? '● LIVE' : state.mode}
          </span>
          {state.updated_at && (
            <span className="text-[11px] text-text-muted font-mono">{fmtTime(state.updated_at)}</span>
          )}
        </div>
      </div>

      {!isRunning && (
        <p className="text-text-tertiary text-xs">
          Start: <code className="font-mono text-[11px] text-text-secondary">python -m trading_agents.iconic.agent_scalp --paper</code>
        </p>
      )}

      {/* Metric row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard label="Paper Trades" value={state.paper_closed} hero tone="accent"
          sub={`${state.paper_pending.length} pending`} />
        <MetricCard label="PF (live)" value={state.paper_pf_live > 0 ? state.paper_pf_live : state.paper_pf}
          tone={state.paper_pf_live >= 1.3 ? 'profit' : state.paper_pf_live >= 1.0 ? 'neutral' : 'loss'}
          sub="profit factor" />
        <MetricCard label="Win Rate" value={state.paper_win_rate} suffix="%"
          tone={state.paper_win_rate >= 55 ? 'profit' : 'neutral'}
          sub={`${state.paper_wins}W · ${state.partial_exits_taken} partial`} />
        <MetricCard label="Daily DD" value={state.daily_loss_pct} suffix="%"
          tone={state.daily_loss_pct >= 4 ? 'loss' : 'neutral'}
          sub={`${Object.values(state.trades_today).reduce((a, b) => a + b, 0)} trades today`} />
      </div>

      {/* Per-symbol promotion grid */}
      <SymPromotionGrid symStats={state.sym_stats ?? {}} symLive={state.sym_live ?? {}} />

      {/* Open positions */}
      {state.paper_pending.length > 0 && (
        <div className="glass rounded-xl p-4 space-y-2">
          <p className="eyebrow mb-2">Open Positions</p>
          {state.paper_pending.map((pos, i) => (
            <div key={i} className="flex items-center justify-between text-[11px] font-mono
                                    bg-white/[0.03] rounded-lg px-3 py-2">
              <div className="flex items-center gap-2">
                <Badge variant={pos.side === 'BUY' ? 'buy' : 'sell'}>{pos.side}</Badge>
                <span className="text-text-primary">{pos.symbol}</span>
                <span className="text-text-tertiary">@ {fmtPrice(pos.entry)}</span>
              </div>
              <div className="flex items-center gap-3 text-text-muted">
                <span>SL {fmtPrice(pos.stop)}</span>
                <span>TP {fmtPrice(pos.tp)}</span>
                {pos.partial_done && (
                  <span className="text-profit text-[10px] px-1.5 py-0.5 rounded
                                   bg-profit/10 ring-1 ring-profit/30">1R PARTIAL</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Trade history */}
      <div className="glass rounded-xl p-4">
        <p className="eyebrow mb-3">Trade History ({trades.length})</p>
        {trades.length === 0
          ? <p className="text-text-tertiary text-sm text-center py-4">No trades yet.</p>
          : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] font-mono border-collapse">
              <thead>
                <tr className="text-text-muted border-b border-white/[0.06]">
                  {['Side', 'Entry', 'SL', 'TP', 'PnL', 'Exit', 'Partial', 'Time'].map(h => (
                    <th key={h} className="text-left px-2 py-1.5 font-medium eyebrow">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const pnlPos = (t.pnl ?? 0) >= 0
                  const exitColor = t.exit === 'TP' ? 'text-profit' : t.exit === 'BE_SL' ? 'text-amber-400' : 'text-loss'
                  return (
                    <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                      <td className="px-2 py-1.5">
                        <Badge variant={t.side === 'BUY' ? 'buy' : 'sell'}>{t.side}</Badge>
                      </td>
                      <td className="px-2 py-1.5 text-text-secondary">{fmtPrice(t.entry)}</td>
                      <td className="px-2 py-1.5 text-text-muted">{fmtPrice(t.stop)}</td>
                      <td className="px-2 py-1.5 text-text-muted">{fmtPrice(t.tp)}</td>
                      <td className={`px-2 py-1.5 font-bold ${pnlPos ? 'text-profit' : 'text-loss'}`}>
                        {t.pnl !== undefined ? `${pnlPos ? '+' : ''}${t.pnl.toFixed(5)}` : '—'}
                      </td>
                      <td className={`px-2 py-1.5 font-semibold ${exitColor}`}>{t.exit ?? 'open'}</td>
                      <td className="px-2 py-1.5">
                        {t.partial_done
                          ? <span className="text-profit text-[10px]">✓ 1R</span>
                          : <span className="text-text-muted">—</span>}
                      </td>
                      <td className="px-2 py-1.5 text-text-muted">{fmtTime(t.ts_close ?? t.ts_open)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export function Scalp() {
  const [state, setState]   = useState<ScalpState>(EMPTY_STATE)
  const [trades, setTrades] = useState<PaperTrade[]>([])
  const [iconicState, setIconicState] = useState<IconicScalpAgentState>(ICONIC_EMPTY)
  const [iconicTrades, setIconicTrades] = useState<IconicScalpTrade[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const [s, t, is, it] = await Promise.all([
        apiFetch('/api/scalp/agent').then(r => r.ok ? r.json() : null),
        apiFetch('/api/scalp/trades?limit=40').then(r => r.ok ? r.json() : null),
        apiFetch('/api/iconic/scalp/agent').then(r => r.ok ? r.json() : null),
        apiFetch('/api/iconic/scalp/trades?limit=40').then(r => r.ok ? r.json() : null),
      ])
      if (s) setState(s as ScalpState)
      if (t) setTrades((t as { trades: PaperTrade[] }).trades ?? [])
      if (is) setIconicState(is as IconicScalpAgentState)
      if (it) setIconicTrades((it as { trades: IconicScalpTrade[] }).trades ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15_000)
    return () => clearInterval(id)
  }, [])

  const isRunning   = state.mode !== 'NOT_RUNNING' && state.mode !== 'STOPPED'
  const isHalted    = state.mode === 'HALTED'
  const pendingKeys = state.paper_pending ?? []

  const modeColor = isHalted
    ? 'text-loss bg-loss/10 ring-loss/30'
    : isRunning
      ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
      : 'text-text-muted bg-white/[0.03] ring-border'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">Gold Scalp Agent</h1>
          <p className="text-text-secondary text-sm mt-0.5">
            GS11 Opening Range + GS07 Liquidity Sweep — XAUUSD M1
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold px-2.5 py-1 rounded ring-1 uppercase tracking-wider ${modeColor}`}>
            {state.mode}
          </span>
          {state.updated_at && (
            <span className="text-[11px] text-text-muted font-mono">
              {fmtTime(state.updated_at)}
            </span>
          )}
        </div>
      </div>

      {/* Not running notice */}
      {!isRunning && !loading && (
        <div className="glass rounded-xl p-4 text-center">
          <p className="text-text-tertiary text-sm">
            Agent not running — start with{' '}
            <code className="font-mono text-[11px] text-text-secondary">
              python -m trading_agents.scalp.agent --paper
            </code>
          </p>
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <MetricCard
          label="Paper Trades"
          value={state.paper_closed}
          hero
          tone="accent"
          sub={`${pendingKeys.length} pending`}
        />
        <MetricCard
          label="Total PF"
          value={state.paper_pf}
          tone={state.paper_pf >= 1.3 ? 'profit' : state.paper_pf >= 1.0 ? 'neutral' : 'loss'}
          sub="profit factor"
        />
        <MetricCard
          label="Win Rate"
          value={state.paper_win_rate}
          suffix="%"
          tone={state.paper_win_rate >= 55 ? 'profit' : 'neutral'}
          sub={`${state.paper_wins} wins`}
        />
        <MetricCard
          label="Daily DD"
          value={state.daily_loss_pct}
          suffix="%"
          tone={state.daily_loss_pct >= 4 ? 'loss' : 'neutral'}
          sub={`${state.trades_today} trades today`}
        />
      </div>

      {/* Strategy cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {(state.strategies ?? ['GS11', 'GS07']).map(s => (
          <StratCard
            key={s}
            name={s}
            stats={state.strat_stats[s] ?? { trades: 0, pf: 0, wr: 0, live: false }}
          />
        ))}
      </div>

      {/* Pending positions */}
      {pendingKeys.length > 0 && (
        <Panel title="Open Paper Positions">
          <div className="flex flex-wrap gap-2">
            {pendingKeys.map(k => (
              <span key={k}
                className="text-[11px] font-mono px-2 py-1 rounded bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/30">
                {k}
              </span>
            ))}
          </div>
        </Panel>
      )}

      {/* Trade log */}
      <Panel title={`Paper Trade Log (${trades.length})`}>
        <TradesTable trades={trades} />
      </Panel>

      {/* Divider */}
      <div className="border-t border-white/[0.06] pt-2" />

      {/* Iconic Scalp section */}
      <IconicScalpPanel state={iconicState} trades={iconicTrades} />
    </div>
  )
}
