import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import { apiFetch } from '../lib/api'
import { useWebSocket } from '../hooks/useWebSocket'
import { PageHeader } from '../components/ui/PageHeader'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { Badge } from '../components/ui/Badge'
import { AgentAvatar } from '../components/ui/AgentAvatar'
import { WinLossDonut } from '../components/charts/WinLossDonut'
import { PnLBarChart } from '../components/charts/PnLBarChart'

// ── Types (mirror dashboard/backend/api/fleet.py) ─────────────────────────────
interface Position { symbol: string; type: string; volume: number; profit: number }
interface StratStat { name: string; trades: number; pf: number | null; wr: number | null; live: boolean }
interface Stats { opened: number; closed: number; realized_pnl: number; wins: number; losses: number; win_rate: number | null }
interface Agent {
  id: string; name: string; avatar?: string | null; strategy: string; magic: number
  health: 'live' | 'warning' | 'offline'; orch_status: string
  restarts: number; pid: number | null; mode: string; pairs: string[]
  open_count: number; open_pnl: number; positions: Position[]
  stats: Stats; strategies: StratStat[]
  daily_dd_pct: number | null; equity: number | null; state_age_sec: number | null
}
interface FleetData {
  ts: string; period: string; period_label: string; since: number; until: number
  bridge_up: boolean
  account: { login?: number; server?: string; balance?: number; equity?: number }
  totals: { agents: number; live: number; open_positions: number; open_pnl: number; opened: number; closed: number; realized_pnl: number; win_rate: number | null }
  agents: Agent[]
}

type Period = 'today' | 'yesterday' | '7d' | '30d' | 'all'
type StatusF = 'all' | 'live' | 'traded' | 'open'
type ResultF = 'all' | 'win' | 'loss'
type SortF = 'pnl' | 'trades' | 'wr' | 'name'

const PERIODS: { k: Period; label: string }[] = [
  { k: 'today', label: 'Today' }, { k: 'yesterday', label: 'Yesterday' },
  { k: '7d', label: '7D' }, { k: '30d', label: '30D' }, { k: 'all', label: 'All' },
]
const HEALTH_DOT: Record<Agent['health'], 'running' | 'warning' | 'offline'> = { live: 'running', warning: 'warning', offline: 'offline' }
function modeTone(m: string): 'green' | 'red' | 'yellow' | 'blue' | 'gray' {
  if (m === 'IN TRADE') return 'blue'; if (m === 'HALTED') return 'red'
  if (m === 'RUNNING' || m === 'SCANNING') return 'green'; return 'gray'
}
function ago(s: number | null): string {
  if (s == null) return '—'; if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`; return `${Math.round(s / 3600)}h ago`
}
const money = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
const pnlCls = (n: number) => (n > 0 ? 'text-profit' : n < 0 ? 'text-loss' : 'text-text-secondary')

function Seg({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={clsx('px-3 h-8 rounded-md text-xs font-semibold tracking-wide transition-all',
        active ? 'bg-accent/15 text-accent ring-1 ring-accent/40' : 'text-text-secondary hover:text-text-primary hover:bg-tint/[0.04]')}>
      {children}
    </button>
  )
}

function StrategyChip({ s }: { s: StratStat }) {
  const pfCol = s.pf == null ? '' : s.pf >= 1.3 ? 'text-profit' : s.pf < 1 ? 'text-loss' : 'text-warning'
  return (
    <div className="flex items-center justify-between gap-2 rounded-md bg-tint/[0.025] ring-1 ring-border px-2.5 py-1.5">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-mono text-xs font-semibold text-text-primary">{s.name}</span>
        <Badge tone={s.live ? 'green' : 'gray'}>{s.live ? 'LIVE' : 'PAPER'}</Badge>
      </div>
      <div className="flex items-center gap-3 font-mono text-[11px] text-text-muted shrink-0">
        <span>{s.trades}t</span>
        {s.pf != null && <span className={pfCol}>PF {s.pf.toFixed(2)}</span>}
        {s.wr != null && <span>{s.wr.toFixed(0)}%</span>}
      </div>
    </div>
  )
}

type TradeTone = 'profit' | 'loss' | 'accent'
const TRADE_GLOW: Record<TradeTone, string> = { profit: 'trade-glow-profit', loss: 'trade-glow-loss', accent: 'trade-glow-accent' }
const TRADE_TAG: Record<TradeTone, string> = {
  profit: 'bg-profit/10 ring-profit/40 text-profit',
  loss: 'bg-loss/10 ring-loss/40 text-loss',
  accent: 'bg-accent/10 ring-accent/40 text-accent',
}
const TRADE_DOT: Record<TradeTone, string> = { profit: 'bg-profit', loss: 'bg-loss', accent: 'bg-accent' }
const TRADE_BAR: Record<TradeTone, string> = {
  profit: 'bg-gradient-to-r from-transparent via-profit/70 to-transparent',
  loss: 'bg-gradient-to-r from-transparent via-loss/70 to-transparent',
  accent: 'bg-gradient-to-r from-transparent via-accent/70 to-transparent',
}

function LiveTradeTag({ tone }: { tone: TradeTone }) {
  return (
    <span className={clsx('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full ring-1 text-[10px] font-bold uppercase tracking-wider', TRADE_TAG[tone])}>
      <span className="relative flex w-1.5 h-1.5">
        <span className={clsx('absolute inline-flex w-full h-full rounded-full opacity-70 animate-glow-ring', TRADE_DOT[tone])} />
        <span className={clsx('relative w-1.5 h-1.5 rounded-full', TRADE_DOT[tone])} />
      </span>
      Live Trade
    </span>
  )
}

function AgentCardBase({ a, i, periodLabel }: { a: Agent; i: number; periodLabel: string }) {
  const r = a.stats.realized_pnl
  const stale = a.health !== 'live'
  const inTrade = a.open_count > 0
  const tone: TradeTone = a.open_pnl > 0 ? 'profit' : a.open_pnl < 0 ? 'loss' : 'accent'
  // Live open positions split by current floating result.
  const openWin = a.positions.filter(p => p.profit > 0).length
  const openLoss = a.positions.filter(p => p.profit < 0).length
  return (
    <div
      className={clsx('glass glass-hover reveal relative overflow-hidden p-5 flex flex-col gap-4 transition-all',
        inTrade
          ? TRADE_GLOW[tone]
          : clsx('ring-1', a.health === 'live' ? 'ring-profit/15' : a.health === 'warning' ? 'ring-warning/25' : 'ring-border'))}
      style={{ '--i': i } as React.CSSProperties}>
      <div className={clsx('absolute inset-x-0 top-0 h-px', inTrade ? clsx(TRADE_BAR[tone], 'animate-pulse2') : 'bg-gradient-to-r from-transparent via-sheen/15 to-transparent')} />

      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <AgentAvatar name={a.name} avatar={a.avatar} size={52} tone={inTrade ? tone : undefined} />
          <div className="min-w-0">
            <p className="eyebrow truncate">{a.strategy}</p>
            <h3 className="text-text-primary text-lg font-bold tracking-tight truncate">{a.name}</h3>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <StatusDot status={HEALTH_DOT[a.health]} label={a.health === 'live' ? 'live' : a.health} />
          {inTrade ? <LiveTradeTag tone={tone} /> : <Badge tone={modeTone(a.mode)}>{a.mode}</Badge>}
        </div>
      </div>

      {/* realized P&L over the selected period */}
      <div className="rounded-lg bg-tint/[0.02] ring-1 ring-border px-4 py-3 flex items-end justify-between">
        <div>
          <p className="eyebrow">P&L · {periodLabel}</p>
          <p className={clsx('font-mono font-bold text-3xl leading-none tracking-tight mt-1 font-tabular', pnlCls(r))}>
            {a.stats.closed === 0 && r === 0 ? '—' : `$${money(r)}`}
          </p>
        </div>
        <div className="text-right text-[11px] font-mono text-text-muted leading-tight">
          <p><span className="text-text-secondary">{a.stats.opened}</span> opened</p>
          <p><span className="text-text-secondary">{a.stats.closed}</span> closed</p>
          <p>{a.stats.win_rate != null ? <span className={a.stats.win_rate >= 50 ? 'text-profit' : 'text-loss'}>{a.stats.win_rate.toFixed(0)}% WR</span> : 'no closes'}</p>
        </div>
      </div>

      {/* Won / Lost split for the period — the quickest read of behaviour */}
      <div className="grid grid-cols-2 gap-2 -mt-1">
        <div className="flex items-center justify-between rounded-lg bg-profit/[0.06] ring-1 ring-profit/25 px-3 py-2">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-profit/90">
            <span className="text-[12px] leading-none">▲</span> Won
          </span>
          <span className="font-mono font-bold text-lg leading-none text-profit font-tabular">{a.stats.wins}</span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-loss/[0.06] ring-1 ring-loss/25 px-3 py-2">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-loss/90">
            <span className="text-[12px] leading-none">▼</span> Lost
          </span>
          <span className="font-mono font-bold text-lg leading-none text-loss font-tabular">{a.stats.losses}</span>
        </div>
      </div>

      {a.strategies.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="eyebrow">Strategies ({a.strategies.length})</p>
          {a.strategies.map(s => <StrategyChip key={s.name} s={s} />)}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {a.pairs.length === 0 && <span className="text-text-muted text-xs">no pairs reported</span>}
        {a.pairs.map(p => <Badge key={p} tone="blue">{p}</Badge>)}
      </div>

      {a.open_count > 0 && (
        <div className="rounded-lg bg-tint/[0.025] ring-1 ring-border p-3 flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <p className="eyebrow">Open now</p>
              <span className="font-mono text-[10px] tracking-tight">
                <span className="text-profit">{openWin}↑</span>
                <span className="text-text-muted"> · </span>
                <span className="text-loss">{openLoss}↓</span>
              </span>
            </div>
            <span className={clsx('font-mono text-sm font-semibold', pnlCls(a.open_pnl))}>${money(a.open_pnl)}</span>
          </div>
          {a.positions.map((p, idx) => (
            <div key={idx} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Badge variant={p.type === 'BUY' ? 'buy' : 'sell'}>{p.type}</Badge>
                <span className="text-text-secondary font-mono">{p.symbol}</span>
                <span className="text-text-muted font-mono text-xs">{p.volume}</span>
              </div>
              <span className={clsx('font-mono text-xs', pnlCls(p.profit))}>${money(p.profit)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between text-[11px] text-text-muted mt-auto pt-1 border-t border-line/60">
        <span>updated {ago(a.state_age_sec)}{stale ? ' · stale' : ''}
          {a.daily_dd_pct != null && a.daily_dd_pct > 0 && <span className={a.daily_dd_pct >= 3 ? 'text-loss' : ''}> · DD {a.daily_dd_pct.toFixed(1)}%</span>}
        </span>
        <span className="flex items-center gap-2 font-mono">
          {a.restarts > 0 && <span className="text-warning">↻{a.restarts}</span>}
          <span>#{a.magic}</span>
        </span>
      </div>
    </div>
  )
}

// Skip re-render on the 5s poll unless this agent's data actually changed — keeps
// scrolling smooth (idle polls re-render nothing).
const AgentCard = memo(AgentCardBase, (p, n) =>
  p.i === n.i && p.periodLabel === n.periodLabel && JSON.stringify(p.a) === JSON.stringify(n.a))

export function Fleet() {
  const [data, setData] = useState<FleetData | null>(null)
  const [err, setErr] = useState(false)
  const [period, setPeriod] = useState<Period>('today')
  const [statusF, setStatusF] = useState<StatusF>('all')
  const [resultF, setResultF] = useState<ResultF>('all')
  const [sortF, setSortF] = useState<SortF>('pnl')
  const inFlight = useRef(false)
  const periodRef = useRef(period)
  periodRef.current = period

  const load = useCallback(async (p: Period) => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const res = await apiFetch(`/api/fleet/overview?period=${p}`)
      if (!res.ok) throw new Error(String(res.status))
      setData(await res.json())
      setErr(false)
    } catch { setErr(true) } finally { inFlight.current = false }
  }, [])

  useEffect(() => {
    load(period)
    const id = setInterval(() => load(periodRef.current), 5000)
    return () => clearInterval(id)
  }, [load, period])

  useWebSocket('state', () => { load(periodRef.current) })

  // client-side filter + sort
  const view = useMemo(() => {
    let list = data?.agents ?? []
    if (statusF === 'live') list = list.filter(a => a.health === 'live')
    else if (statusF === 'traded') list = list.filter(a => a.stats.opened + a.stats.closed > 0)
    else if (statusF === 'open') list = list.filter(a => a.open_count > 0)
    if (resultF === 'win') list = list.filter(a => a.stats.realized_pnl > 0)
    else if (resultF === 'loss') list = list.filter(a => a.stats.realized_pnl < 0)
    const s = [...list]
    s.sort((a, b) => {
      const at = a.open_count > 0 ? 1 : 0, bt = b.open_count > 0 ? 1 : 0
      if (at !== bt) return bt - at          // agents with a live trade always float to the top
      if (sortF === 'pnl') return b.stats.realized_pnl - a.stats.realized_pnl
      if (sortF === 'trades') return (b.stats.opened + b.stats.closed) - (a.stats.opened + a.stats.closed)
      if (sortF === 'wr') return (b.stats.win_rate ?? -1) - (a.stats.win_rate ?? -1)
      return a.name.localeCompare(b.name)
    })
    return s
  }, [data, statusF, resultF, sortF])

  // totals recomputed for the filtered set
  const t = useMemo(() => {
    const closed = view.reduce((s, a) => s + a.stats.closed, 0)
    const wins = view.reduce((s, a) => s + a.stats.wins, 0)
    const losses = view.reduce((s, a) => s + a.stats.losses, 0)
    return {
      live: view.filter(a => a.health === 'live').length,
      agents: view.length,
      realized: view.reduce((s, a) => s + a.stats.realized_pnl, 0),
      floating: view.reduce((s, a) => s + a.open_pnl, 0),
      open: view.reduce((s, a) => s + a.open_count, 0),
      opened: view.reduce((s, a) => s + a.stats.opened, 0),
      wins, losses,
      closed, winRate: closed ? Math.round(wins / closed * 100) : null,
    }
  }, [view])

  // Per-agent realized P&L for the period (chart) — only agents that traded.
  const pnlByAgent = useMemo(
    () => view
      .filter(a => a.stats.closed > 0 || a.stats.realized_pnl !== 0)
      .map(a => ({ label: a.name, value: Number(a.stats.realized_pnl.toFixed(2)) }))
      .sort((a, b) => b.value - a.value),
    [view],
  )

  const pLabel = data?.period_label ?? 'Today'

  return (
    <div className="space-y-5">
      <PageHeader
        title="Agent Fleet"
        subtitle="Live trading desk — filter by period, status, and result to read it your way"
        right={
          <div className="flex items-center gap-3">
            {data && <Badge tone={data.bridge_up ? 'green' : 'red'}>{data.bridge_up ? 'bridge up' : 'bridge down'}</Badge>}
            <StatusDot status={err ? 'warning' : 'running'} label={err ? 'reconnecting' : 'live'} />
          </div>
        }
      />

      {/* ── filter bar ── */}
      <div className="glass p-3 flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex items-center gap-1.5">
          <span className="eyebrow mr-1">Period</span>
          {PERIODS.map(p => <Seg key={p.k} active={period === p.k} onClick={() => setPeriod(p.k)}>{p.label}</Seg>)}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="eyebrow mr-1">Show</span>
          {(['all', 'live', 'traded', 'open'] as StatusF[]).map(s =>
            <Seg key={s} active={statusF === s} onClick={() => setStatusF(s)}>{s === 'all' ? 'All' : s === 'live' ? 'Live' : s === 'traded' ? 'Traded' : 'Open pos'}</Seg>)}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="eyebrow mr-1">Result</span>
          {(['all', 'win', 'loss'] as ResultF[]).map(s =>
            <Seg key={s} active={resultF === s} onClick={() => setResultF(s)}>{s === 'all' ? 'All' : s === 'win' ? 'Winners' : 'Losers'}</Seg>)}
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="eyebrow mr-1">Sort</span>
          {(['pnl', 'trades', 'wr', 'name'] as SortF[]).map(s =>
            <Seg key={s} active={sortF === s} onClick={() => setSortF(s)}>{s === 'pnl' ? 'P&L' : s === 'trades' ? 'Trades' : s === 'wr' ? 'Win%' : 'Name'}</Seg>)}
        </div>
      </div>

      {/* totals (for the filtered set + period) */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <MetricCard hero label={`Realized · ${pLabel}`} value={t.realized} prefix="$"
          tone={t.realized >= 0 ? 'profit' : 'loss'} positive={t.realized >= 0} sub={`${t.closed} closed`} />
        <MetricCard label="Floating P&L" value={t.floating} prefix="$"
          tone={t.floating >= 0 ? 'profit' : 'loss'} positive={t.floating >= 0} sub={`${t.open} open`} />
        <MetricCard label={`Win Rate · ${pLabel}`} value={t.winRate != null ? `${t.winRate}%` : '—'}
          tone={t.winRate != null && t.winRate >= 50 ? 'profit' : 'warning'} />
        <MetricCard label="Opened" value={t.opened} tone="accent" sub={pLabel} />
        <MetricCard label="Agents" value={`${t.live} / ${t.agents}`}
          tone={t.live === t.agents && t.agents > 0 ? 'profit' : t.live === 0 ? 'loss' : 'warning'} sub="live / shown" />
        <MetricCard label="Equity" value={data?.account.equity ?? 0} prefix="$" tone="neutral" sub={data?.account.server} />
      </div>

      {/* fleet analytics — win/loss split + per-agent P&L contribution */}
      {(t.closed > 0 || pnlByAgent.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="glass p-4 flex flex-col">
            <p className="eyebrow mb-2">Win / Loss · {pLabel}</p>
            <div className="flex-1 grid place-items-center">
              <WinLossDonut wins={t.wins} losses={t.losses} />
            </div>
          </div>
          <div className="glass p-4 lg:col-span-2 flex flex-col">
            <div className="flex items-center justify-between mb-2">
              <p className="eyebrow">P&amp;L by Agent · {pLabel}</p>
              <span className={clsx('text-[11px] font-mono', pnlCls(t.realized))}>${money(t.realized)} total</span>
            </div>
            <div className="flex-1">
              {pnlByAgent.length > 0
                ? <PnLBarChart data={pnlByAgent} height={200} />
                : <div className="h-[200px] grid place-items-center text-text-muted text-sm">No closed trades in this window</div>}
            </div>
          </div>
        </div>
      )}

      {/* agent grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {view.map((a, i) => <AgentCard key={a.id} a={a} i={i} periodLabel={pLabel} />)}
        {data && view.length === 0 && <div className="col-span-full text-text-muted text-sm py-12 text-center">No agents match these filters.</div>}
        {!data && !err && <div className="col-span-full text-text-muted text-sm animate-pulse py-12 text-center">Loading fleet…</div>}
        {err && !data && <div className="col-span-full text-loss text-sm py-12 text-center">Couldn't reach the fleet API.</div>}
      </div>
    </div>
  )
}
