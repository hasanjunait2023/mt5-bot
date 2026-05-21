import { useEffect, useMemo, useRef, useState } from 'react'
import { Panel } from '../components/ui/Panel'
import { Badge } from '../components/ui/Badge'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { apiFetch, api } from '../lib/api'
import { useWebSocket } from '../hooks/useWebSocket'
import type { SignalEvent } from '../types/trading'
import { DeliveryControl } from '../components/signals/DeliveryControl'

type SignalType = 'alignment' | 'cross' | 'touch' | 'all'

interface SignalsResponse {
  state: {
    running: boolean
    symbols: string[]
    tick_sec: number | null
    updated_at: string | null
  }
  events: SignalEvent[]
  counts_recent: { alignment: number; cross: number; touch: number }
}

const TYPE_LABEL: Record<Exclude<SignalType, 'all'>, string> = {
  alignment: '4-TF EMA-200 Alignment',
  cross:     '9/15 EMA Cross (M1)',
  touch:     '200 EMA Touch (M3)',
}

const TYPE_ACCENT: Record<Exclude<SignalType, 'all'>, string> = {
  alignment: 'from-violet-500/40 to-violet-500/0',
  cross:     'from-amber-500/40 to-amber-500/0',
  touch:     'from-sky-500/40 to-sky-500/0',
}

function fmtTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function chartSrc(ev: SignalEvent): string | null {
  if (ev.chart_b64) return `data:image/png;base64,${ev.chart_b64}`
  if (ev.id) return api(`/signals/chart/${ev.id}`)
  return null
}

function SignalCard({ ev }: { ev: SignalEvent }) {
  const isBuy = ev.side === 'BUY'
  const accent = TYPE_ACCENT[ev.type as Exclude<SignalType, 'all'>] ?? TYPE_ACCENT.alignment
  const src = chartSrc(ev)
  return (
    <div className="glass rounded-xl overflow-hidden ring-1 ring-border hover:ring-white/20 transition-all duration-300">
      <div className={`relative h-1 bg-gradient-to-r ${accent}`} />
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-text-primary font-semibold tracking-wide">{ev.symbol}</span>
            <Badge variant={isBuy ? 'buy' : 'sell'}>{ev.side}</Badge>
            <Badge variant="neutral">{ev.timeframe}</Badge>
          </div>
          <span className="font-mono text-[11px] text-text-secondary">{fmtTime(ev.ts)}</span>
        </div>
        <div className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
          {TYPE_LABEL[ev.type as Exclude<SignalType, 'all'>] ?? ev.type}
        </div>
        {src && (
          <div className="rounded-lg overflow-hidden bg-white ring-1 ring-border">
            <img src={src} alt={`${ev.symbol} ${ev.type}`} className="w-full block" loading="lazy" />
          </div>
        )}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs font-mono text-text-secondary">
          <div>Price <span className="text-text-primary">{ev.price.toFixed(5)}</span></div>
          <div>EMA200 <span className="text-text-primary">{ev.ema200.toFixed(5)}</span></div>
          <div>EMA9 <span className="text-text-primary">{ev.ema9.toFixed(5)}</span></div>
          <div>EMA15 <span className="text-text-primary">{ev.ema15.toFixed(5)}</span></div>
        </div>
        <div className="text-[11px] text-text-tertiary italic">{ev.note}</div>
        {ev.detect_ms !== undefined && (
          <div className="text-[10px] text-text-tertiary font-mono">
            detected in {ev.detect_ms.toFixed(0)} ms
          </div>
        )}
      </div>
    </div>
  )
}

export function Signals() {
  const [resp, setResp] = useState<SignalsResponse | null>(null)
  const [filter, setFilter] = useState<SignalType>('all')
  const [livePulse, setLivePulse] = useState(0)
  const initLoaded = useRef(false)

  // initial load + 10s refetch as a safety net
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await apiFetch('/signals')
        if (!r.ok) return
        const data: SignalsResponse = await r.json()
        if (!cancelled) {
          setResp(data)
          initLoaded.current = true
        }
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 10_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // live WS push — prepend the new event
  useWebSocket('signal', (data) => {
    const ev = data as SignalEvent
    setResp(prev => {
      if (!prev) {
        return {
          state: { running: true, symbols: [], tick_sec: null, updated_at: ev.ts },
          events: [ev],
          counts_recent: {
            alignment: ev.type === 'alignment' ? 1 : 0,
            cross:     ev.type === 'cross' ? 1 : 0,
            touch:     ev.type === 'touch' ? 1 : 0,
          },
        }
      }
      const events = [ev, ...prev.events].slice(0, 200)
      const counts_recent = { ...prev.counts_recent }
      if (ev.type in counts_recent) {
        // @ts-ignore
        counts_recent[ev.type] += 1
      }
      return { ...prev, events, counts_recent }
    })
    setLivePulse(p => p + 1)
  })

  const filtered = useMemo(() => {
    if (!resp) return []
    if (filter === 'all') return resp.events
    return resp.events.filter(e => e.type === filter)
  }, [resp, filter])

  const running = resp?.state?.running ?? false
  const symbolsCount = resp?.state?.symbols?.length ?? 0
  const counts = resp?.counts_recent ?? { alignment: 0, cross: 0, touch: 0 }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Signals</h1>
          <p className="text-text-secondary text-sm mt-1">
            Multi-timeframe EMA-200 alignment scanner — live, sub-second.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusDot status={running ? 'running' : 'offline'} />
          <span className="text-sm text-text-secondary">
            {running ? 'Engine running' : 'Engine offline'} · scanning {symbolsCount} symbols
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <MetricCard label="Live"        value={livePulse}            tone="accent" />
        <MetricCard label="Alignments"  value={counts.alignment}     tone="neutral" />
        <MetricCard label="Crosses M1"  value={counts.cross}         tone="profit"  />
        <MetricCard label="Touch M3"    value={counts.touch}         tone="neutral" />
      </div>

      <DeliveryControl />

      <Panel
        i={0}
        title="Live Feed"
        right={
          <div className="flex items-center gap-2">
            {(['all', 'alignment', 'cross', 'touch'] as const).map(t => (
              <button
                key={t}
                onClick={() => setFilter(t)}
                className={`px-3 h-7 rounded-md text-[11px] font-semibold uppercase tracking-wider transition-all ${
                  filter === t
                    ? 'bg-white/[0.08] text-text-primary ring-1 ring-border'
                    : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.03]'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        }
      >
        {filtered.length === 0 ? (
          <div className="text-text-tertiary text-sm py-6 text-center">
            No signals yet — waiting for the next alignment / cross / touch.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map(ev => <SignalCard key={ev.id} ev={ev} />)}
          </div>
        )}
      </Panel>
    </div>
  )
}
