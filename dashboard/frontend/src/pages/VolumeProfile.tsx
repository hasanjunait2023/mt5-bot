import { useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'
import { MetricCard } from '../components/ui/MetricCard'
import { Badge } from '../components/ui/Badge'
import { Panel } from '../components/ui/Panel'

// ── Types ──────────────────────────────────────────────────────────────────────
interface PerSym {
  trades: number
  pf: number
  wr: number
  gate_ready: boolean
  open: boolean
}

interface VpState {
  agent: string
  mode: string
  account: string
  symbols: string[]
  tf: string
  trades: number
  pf: number
  open_positions: number
  per_symbol: Record<string, PerSym>
  equity: number
  daily_loss_pct: number
  trades_today: number
  gate: { min_trades: number; min_pf: number }
  updated_at: string | null
}

interface VpTrade {
  symbol: string
  side: string
  entry: number
  sl: number
  tp: number
  lots?: number
  pnl?: number
  exit?: string
  mode?: string
  status: string
  ts_open: string
  ts_close?: string
}

const EMPTY: VpState = {
  agent: 'GS-VP', mode: 'NOT_RUNNING', account: 'demo',
  symbols: ['GBPUSD', 'EURUSD', 'XAUUSD', 'BTCUSD', 'XAGUSD'], tf: 'M15',
  trades: 0, pf: 0, open_positions: 0, per_symbol: {},
  equity: 0, daily_loss_pct: 0, trades_today: 0,
  gate: { min_trades: 20, min_pf: 1.3 }, updated_at: null,
}

const MIN_TRADES = 20
const MIN_PF = 1.3

const SYM_NOTE: Record<string, string> = {
  GBPUSD: 'robust (1.59 / both halves)',
  EURUSD: 'profitable both halves',
  XAUUSD: 'regime-dependent — cautious',
  BTCUSD: 'breakeven — proving',
  XAGUSD: 'weak — proving',
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtTime(ts: string | undefined | null): string {
  if (!ts) return '—'
  try { return new Date(ts).toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' }) }
  catch { return ts }
}
function fmtPrice(p: number): string {
  return p >= 100 ? p.toFixed(2) : p.toFixed(5)
}

// ── Per-symbol gate grid ────────────────────────────────────────────────────────
function GateGrid({ perSym }: { perSym: Record<string, PerSym> }) {
  const entries = Object.entries(perSym)
  if (!entries.length) return null
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <p className="eyebrow">Per-Symbol Promotion Gate (demo → real)</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {entries.map(([sym, s]) => {
          const tradesProg = Math.min(100, (s.trades / MIN_TRADES) * 100)
          const pfProg = Math.min(100, (s.pf / MIN_PF) * 100)
          return (
            <div key={sym} className={`rounded-lg p-3 space-y-2 ring-1 ${
              s.gate_ready ? 'bg-profit/10 ring-profit/30'
                : s.open ? 'bg-accent/10 ring-accent/30'
                : 'bg-white/[0.03] ring-white/[0.06]'
            }`}>
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-mono text-sm font-bold text-text-primary">{sym}</span>
                  <p className="text-[9px] text-text-muted mt-0.5">{SYM_NOTE[sym] ?? ''}</p>
                </div>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ring-1 uppercase ${
                  s.gate_ready ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
                    : 'text-amber-400 bg-amber-500/10 ring-amber-500/30'
                }`}>
                  {s.gate_ready ? '✓ READY' : s.open ? '● OPEN' : '◎ TEST'}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1 text-center">
                <div>
                  <p className="text-[9px] text-text-muted uppercase tracking-wide">Trades</p>
                  <p className="font-mono text-sm font-bold text-text-primary">{s.trades}</p>
                </div>
                <div>
                  <p className="text-[9px] text-text-muted uppercase tracking-wide">PF</p>
                  <p className={`font-mono text-sm font-bold ${
                    s.pf >= 1.3 ? 'text-profit' : s.pf >= 1.0 ? 'text-amber-400' : 'text-text-secondary'
                  }`}>{s.pf > 0 ? s.pf.toFixed(2) : '—'}</p>
                </div>
                <div>
                  <p className="text-[9px] text-text-muted uppercase tracking-wide">WR%</p>
                  <p className={`font-mono text-sm font-bold ${s.wr >= 50 ? 'text-profit' : 'text-text-secondary'}`}>
                    {s.wr > 0 ? `${s.wr.toFixed(0)}%` : '—'}
                  </p>
                </div>
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-1">
                  <div className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className="h-full rounded-full bg-accent/50 transition-all" style={{ width: `${tradesProg}%` }} />
                  </div>
                  <span className="text-[9px] text-text-muted font-mono w-9 text-right">{s.trades}/{MIN_TRADES}</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className={`h-full rounded-full transition-all ${s.gate_ready ? 'bg-profit' : 'bg-accent/50'}`}
                         style={{ width: `${pfProg}%` }} />
                  </div>
                  <span className={`text-[9px] font-mono w-9 text-right ${s.gate_ready ? 'text-profit' : 'text-text-muted'}`}>
                    {s.pf > 0 ? s.pf.toFixed(2) : '—'}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Trades table ────────────────────────────────────────────────────────────────
function TradesTable({ trades }: { trades: VpTrade[] }) {
  if (!trades.length) {
    return <p className="text-text-tertiary text-sm text-center py-6">No closed trades yet.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] font-mono border-collapse">
        <thead>
          <tr className="text-text-muted border-b border-white/[0.06]">
            {['Symbol', 'Side', 'Entry', 'SL', 'TP', 'PnL', 'Exit', 'Mode', 'Time'].map(h => (
              <th key={h} className="text-left px-2 py-1.5 font-medium eyebrow">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnlPos = (t.pnl ?? 0) >= 0
            return (
              <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                <td className="px-2 py-1.5 text-accent">{t.symbol}</td>
                <td className="px-2 py-1.5"><Badge variant={t.side === 'BUY' ? 'buy' : 'sell'}>{t.side}</Badge></td>
                <td className="px-2 py-1.5 text-text-secondary">{fmtPrice(t.entry)}</td>
                <td className="px-2 py-1.5 text-text-muted">{fmtPrice(t.sl)}</td>
                <td className="px-2 py-1.5 text-text-muted">{fmtPrice(t.tp)}</td>
                <td className={`px-2 py-1.5 font-bold ${pnlPos ? 'text-profit' : 'text-loss'}`}>
                  {t.pnl !== undefined ? `${pnlPos ? '+' : ''}${t.pnl.toFixed(2)}` : '—'}
                </td>
                <td className={`px-2 py-1.5 font-semibold ${t.exit === 'TP' ? 'text-profit' : 'text-loss'}`}>{t.exit ?? 'open'}</td>
                <td className="px-2 py-1.5 text-text-muted text-[10px]">{t.mode ?? '—'}</td>
                <td className="px-2 py-1.5 text-text-muted">{fmtTime(t.ts_close ?? t.ts_open)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────────
export function VolumeProfile() {
  const [state, setState] = useState<VpState>(EMPTY)
  const [trades, setTrades] = useState<VpTrade[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const [s, t] = await Promise.all([
        apiFetch('/api/vp/agent').then(r => r.ok ? r.json() : null),
        apiFetch('/api/vp/trades?limit=50').then(r => r.ok ? r.json() : null),
      ])
      if (s) setState(s as VpState)
      if (t) setTrades((t as { trades: VpTrade[] }).trades ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15_000)
    return () => clearInterval(id)
  }, [])

  const isRunning = state.mode !== 'NOT_RUNNING' && state.mode !== 'STOPPED'
  const isHalted = state.mode === 'HALTED'
  const isDemo = state.account === 'demo'

  const modeColor = isHalted
    ? 'text-loss bg-loss/10 ring-loss/30'
    : isRunning ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30'
      : 'text-text-muted bg-white/[0.03] ring-border'

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">GS-VP Volume Profile Agent</h1>
          <p className="text-text-secondary text-sm mt-0.5">
            Adaptive volume profile — breakout-retest + VA-reversion · M15 · {(state.symbols ?? []).join(' · ')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold px-2 py-1 rounded ring-1 uppercase tracking-wider ${
            isDemo ? 'text-sky-400 bg-sky-500/10 ring-sky-500/30' : 'text-loss bg-loss/10 ring-loss/30'
          }`}>{isDemo ? 'DEMO' : 'REAL'}</span>
          <span className={`text-[11px] font-bold px-2.5 py-1 rounded ring-1 uppercase tracking-wider ${modeColor}`}>
            {state.mode}
          </span>
          {state.updated_at && (
            <span className="text-[11px] text-text-muted font-mono">{fmtTime(state.updated_at)}</span>
          )}
        </div>
      </div>

      {/* Not-running notice */}
      {!isRunning && !loading && (
        <div className="glass rounded-xl p-4 text-center">
          <p className="text-text-tertiary text-sm">
            Agent not running — start with{' '}
            <code className="font-mono text-[11px] text-text-secondary">
              python -m trading_agents.scalp.gsvp_agent
            </code>
          </p>
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <MetricCard label="Closed Trades" value={state.trades} hero tone="accent"
          sub={`${state.open_positions} open`} />
        <MetricCard label="Overall PF" value={state.pf}
          tone={state.pf >= 1.3 ? 'profit' : state.pf >= 1.0 ? 'neutral' : 'loss'} sub="profit factor" />
        <MetricCard label="Equity" value={state.equity} prefix="$"
          tone="neutral" sub={`${state.trades_today} trades today`} />
        <MetricCard label="Daily DD" value={state.daily_loss_pct} suffix="%"
          tone={state.daily_loss_pct >= 4 ? 'loss' : 'neutral'} sub="halt at 6%" />
      </div>

      {/* Per-symbol gate grid */}
      <GateGrid perSym={state.per_symbol ?? {}} />

      {/* Trade log */}
      <Panel title={`Closed Trades (${trades.length})`}>
        <TradesTable trades={trades} />
      </Panel>
    </div>
  )
}
