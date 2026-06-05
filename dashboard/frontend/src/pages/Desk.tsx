import { useEffect, useMemo, useRef, useState } from 'react'
import { Panel } from '../components/ui/Panel'
import { Badge } from '../components/ui/Badge'
import { StatusDot } from '../components/ui/StatusDot'
import { apiFetch } from '../lib/api'
import { useWebSocket } from '../hooks/useWebSocket'

type SymbolKey = string

interface Zone {
  symbol: string
  timeframe: string
  side: 'supply' | 'demand'
  top: number
  bottom: number
  state: 'fresh' | 'tested' | 'broken'
  test_count: number
  strength: number
  created_bar: number
}

interface Pool {
  symbol: string
  side: 'bsl' | 'ssl'
  kind: string
  price: number
  swept: boolean
  swept_ts: number | null
  label: string
}

interface OrderBlock {
  symbol: string
  timeframe: string
  side: 'bull' | 'bear'
  top: number
  bottom: number
  mitigated: boolean
}

interface AlphaSignal {
  type: string
  symbol: string
  side: 'BUY' | 'SELL'
  timeframe: string
  price: number
  score: number
  tier: string
  session: string
  reasons: string[]
}

interface DeskState {
  running: boolean
  session: string
  zones_snapshot: Record<SymbolKey, Record<string, Zone[]>>
  liquidity_snapshot: Record<SymbolKey, Pool[]>
  orderflow_snapshot: Record<SymbolKey, Record<string, OrderBlock[]>>
  updated_at: string | null
}

const POPULAR_SYMBOLS = [
  'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'NZDUSD',
  'EURJPY', 'GBPJPY', 'AUDJPY', 'EURGBP',
  'XAUUSD', 'XAGUSD', 'BTCUSD', 'USOIL',
]

const TV_SYMBOL_MAP: Record<string, string> = {
  XAUUSD: 'OANDA:XAUUSD',
  XAGUSD: 'OANDA:XAGUSD',
  BTCUSD: 'BITSTAMP:BTCUSD',
  USOIL:  'TVC:USOIL',
}

function tvSymbol(s: string): string {
  if (TV_SYMBOL_MAP[s]) return TV_SYMBOL_MAP[s]
  // Default FX → OANDA prefix
  return `OANDA:${s}`
}

function sessionStyles(session: string) {
  if (session === 'london') return 'bg-amber-500/20 text-amber-300 ring-amber-500/30'
  if (session === 'ny')     return 'bg-sky-500/20    text-sky-300    ring-sky-500/30'
  if (session === 'asia')   return 'bg-violet-500/20 text-violet-300 ring-violet-500/30'
  return 'bg-tint/[0.05] text-text-secondary ring-border'
}

function sessionLabel(s: string) {
  return ({ asia: '🌏 Asia', london: '🌅 London', ny: '🗽 New York', off: '💤 Off-session' } as any)[s] ?? s
}

/* -------- TradingView widget embed -------- */
function TVChart({ symbol }: { symbol: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    ref.current.innerHTML = ''
    const container = document.createElement('div')
    container.className = 'tradingview-widget-container'
    container.style.height = '100%'
    container.style.width = '100%'
    const inner = document.createElement('div')
    inner.className = 'tradingview-widget-container__widget'
    inner.style.height = '100%'
    container.appendChild(inner)
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.innerHTML = JSON.stringify({
      symbol: tvSymbol(symbol),
      interval: '15',
      timezone: 'Etc/UTC',
      theme: 'dark',
      style: '1',
      locale: 'en',
      withdateranges: true,
      hide_side_toolbar: false,
      allow_symbol_change: true,
      studies: ['MAExp@tv-basicstudies', 'MAExp@tv-basicstudies', 'MAExp@tv-basicstudies'],
      studies_overrides: {
        'moving average exponential.length': 9,
      },
      autosize: true,
      support_host: 'https://www.tradingview.com',
    })
    container.appendChild(script)
    ref.current.appendChild(container)
  }, [symbol])
  return <div ref={ref} className="w-full h-full min-h-[520px]" />
}

/* -------- Side panel sub-components -------- */
function ZoneRow({ z, currentPrice }: { z: Zone; currentPrice?: number }) {
  const inside = currentPrice !== undefined && currentPrice >= z.bottom && currentPrice <= z.top
  return (
    <div className={`p-2 rounded-md ring-1 transition-all ${
      inside ? 'bg-amber-500/10 ring-amber-500/40' : 'bg-tint/[0.025] ring-border'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant={z.side === 'supply' ? 'sell' : 'buy'}>{z.side.toUpperCase()}</Badge>
          <span className="text-xs text-text-secondary font-mono">{z.timeframe}</span>
          <span className="text-[10px] uppercase tracking-wider text-text-tertiary">{z.state}</span>
        </div>
        <span className="font-mono text-[10px] text-text-tertiary">{z.strength}× ATR</span>
      </div>
      <div className="mt-1 text-xs font-mono text-text-secondary">
        {z.bottom.toFixed(5)} → {z.top.toFixed(5)}
        {z.test_count > 0 && <span className="ml-2 text-amber-400">·  tests {z.test_count}</span>}
      </div>
    </div>
  )
}

function PoolRow({ p, currentPrice }: { p: Pool; currentPrice?: number }) {
  const dist = currentPrice ? Math.abs(p.price - currentPrice) : 0
  return (
    <div className={`p-2 rounded-md ring-1 ring-border transition-all ${
      p.swept ? 'bg-tint/[0.01] opacity-60' : 'bg-tint/[0.025]'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant={p.side === 'bsl' ? 'buy' : 'sell'}>{p.side.toUpperCase()}</Badge>
          <span className="text-[11px] text-text-secondary">{p.label}</span>
        </div>
        {p.swept && <span className="text-[10px] text-text-tertiary">SWEPT</span>}
      </div>
      <div className="mt-1 text-xs font-mono text-text-secondary">
        {p.price.toFixed(5)}
        {currentPrice && <span className="ml-2 text-text-tertiary">·  {dist > 0 ? `${dist.toFixed(5)} away` : ''}</span>}
      </div>
    </div>
  )
}

/* -------- Main page -------- */
export function Desk() {
  const [symbol, setSymbol] = useState<string>('EURUSD')
  const [state, setState]   = useState<DeskState | null>(null)
  const [signals, setSignals] = useState<AlphaSignal[]>([])
  const [latestPrice, setLatestPrice] = useState<number | undefined>(undefined)

  // Initial + periodic refetch
  useEffect(() => {
    let dead = false
    const load = async () => {
      try {
        const [r1, r2] = await Promise.all([
          apiFetch('/desk/state').then(r => r.ok ? r.json() : null),
          apiFetch('/desk/signals?limit=30').then(r => r.ok ? r.json() : null),
        ])
        if (dead) return
        if (r1) setState(r1)
        if (r2) setSignals(r2.signals || [])
      } catch {}
    }
    load()
    const id = setInterval(load, 8_000)
    return () => { dead = true; clearInterval(id) }
  }, [])

  // Live alpha signal push
  useWebSocket('alpha_signal', (data) => {
    const ev = data as AlphaSignal
    setSignals(prev => [ev, ...prev].slice(0, 30))
  })

  // Pull current price from the latest signal for this symbol (rough proxy)
  useEffect(() => {
    const last = signals.find(s => s.symbol === symbol)
    if (last) setLatestPrice(last.price)
  }, [signals, symbol])

  const symZones = useMemo(() => {
    const m = state?.zones_snapshot?.[symbol] ?? {}
    return ([] as Zone[]).concat(...Object.values(m))
  }, [state, symbol])
  const symPools = useMemo(() => state?.liquidity_snapshot?.[symbol] ?? [], [state, symbol])
  const symOBs   = useMemo(() => {
    const m = state?.orderflow_snapshot?.[symbol] ?? {}
    return ([] as OrderBlock[]).concat(...Object.values(m))
  }, [state, symbol])

  const symSignals = signals.filter(s => s.symbol === symbol).slice(0, 8)
  const session    = state?.session ?? 'off'

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Alpha Desk · {symbol}</h1>
          <p className="text-text-secondary text-sm mt-1">
            Institutional confluence view — zones, liquidity, order-flow alongside live TradingView.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`px-2.5 py-1 rounded-md ring-1 text-xs font-semibold ${sessionStyles(session)}`}>
            {sessionLabel(session)}
          </span>
          <StatusDot status={state?.running ? 'running' : 'offline'} />
        </div>
      </div>

      {/* symbol picker */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {POPULAR_SYMBOLS.map(s => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className={`px-3 h-8 rounded-md text-[12px] font-mono font-semibold whitespace-nowrap transition-all ring-1 ${
              s === symbol
                ? 'bg-accent/15 text-text-primary ring-accent/40'
                : 'bg-tint/[0.025] text-text-secondary ring-border hover:text-text-primary hover:bg-tint/[0.05]'
            }`}
          >
            {s.length === 6 ? `${s.slice(0,3)}/${s.slice(3)}` : s}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* TradingView chart — spans 2/3 */}
        <Panel i={0} className="xl:col-span-2" title="TradingView">
          <div className="rounded-lg overflow-hidden h-[560px]">
            <TVChart symbol={symbol} />
          </div>
        </Panel>

        {/* Side panel — context */}
        <div className="space-y-4">
          {/* Live alpha signals for this symbol */}
          <Panel i={1} title="Alpha Signals (this symbol)">
            {symSignals.length === 0 ? (
              <div className="text-text-tertiary text-sm text-center py-3">No alpha signal yet — waiting for confluence.</div>
            ) : (
              <div className="space-y-2 max-h-[200px] overflow-y-auto">
                {symSignals.map((s, i) => (
                  <div key={i} className="p-2 rounded-md bg-tint/[0.025] ring-1 ring-border">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant={s.side === 'BUY' ? 'buy' : 'sell'}>{s.side}</Badge>
                        <span className="text-[11px] uppercase font-semibold tracking-wider">{s.type}</span>
                      </div>
                      <span className="text-[10px] font-mono text-text-tertiary">{s.score.toFixed(0)}/100 · {s.tier}</span>
                    </div>
                    <ul className="mt-1 text-[11px] text-text-secondary space-y-0.5">
                      {(s.reasons || []).slice(0, 3).map((r, j) => <li key={j}>{r}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {/* Zones */}
          <Panel i={2} title={`Supply / Demand Zones (${symZones.length})`}>
            {symZones.length === 0 ? (
              <div className="text-text-tertiary text-sm text-center py-3">No active zones detected.</div>
            ) : (
              <div className="space-y-1.5 max-h-[240px] overflow-y-auto">
                {symZones
                  .slice()
                  .sort((a, b) => (a.state === 'fresh' ? -1 : 1) - (b.state === 'fresh' ? -1 : 1))
                  .map((z, i) => <ZoneRow key={i} z={z} currentPrice={latestPrice} />)}
              </div>
            )}
          </Panel>

          {/* Liquidity */}
          <Panel i={3} title={`Liquidity Pools (${symPools.length})`}>
            {symPools.length === 0 ? (
              <div className="text-text-tertiary text-sm text-center py-3">No liquidity pools mapped.</div>
            ) : (
              <div className="space-y-1.5 max-h-[260px] overflow-y-auto">
                {symPools.map((p, i) => <PoolRow key={i} p={p} currentPrice={latestPrice} />)}
              </div>
            )}
          </Panel>

          {/* Order Blocks */}
          {symOBs.length > 0 && (
            <Panel i={4} title={`Order Blocks (${symOBs.length})`}>
              <div className="space-y-1.5 max-h-[180px] overflow-y-auto">
                {symOBs.map((ob, i) => (
                  <div key={i} className="p-2 rounded-md bg-tint/[0.025] ring-1 ring-border">
                    <div className="flex items-center justify-between">
                      <Badge variant={ob.side === 'bull' ? 'buy' : 'sell'}>{ob.side.toUpperCase()} OB</Badge>
                      <span className="text-[10px] text-text-tertiary">{ob.timeframe} {ob.mitigated ? '· mitigated' : '· fresh'}</span>
                    </div>
                    <div className="mt-1 text-xs font-mono text-text-secondary">
                      {ob.bottom.toFixed(5)} → {ob.top.toFixed(5)}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
