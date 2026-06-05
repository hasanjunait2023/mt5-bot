import { useState } from 'react'
import { Badge } from '../ui/Badge'
import { api } from '../../lib/api'

export interface TvEntry {
  side: 'BUY' | 'SELL'
  entry: number
  sl: number
  tp1: number
  tp2: number
  rr: number[]
  type: string
  reasons: string[]
  win_prob: number
  tier?: 'A' | 'B' | 'C'
  score?: number
  news_warn?: boolean
}

export interface TvEvent {
  id: string
  mode: string
  session?: string | null
  symbol: string
  name: string
  tv_symbol: string
  entry_tf: string
  price: number
  bias: string
  narrative: string
  dealing_range?: { high: number; low: number; equilibrium: number; zone: string }
  pdh?: number | null
  pdl?: number | null
  entries: TvEntry[]
  source?: string
  news?: { title: string; ccy: string; at: string }[]
  top_tier?: string | null
  chart_path?: string | null
  ts: string
}

const TIER_COLOR: Record<string, string> = {
  A: 'text-profit', B: 'text-accent', C: 'text-text-tertiary',
}

const num = (n: number | null | undefined) =>
  n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: 5 })

function biasTone(b: string): 'buy' | 'sell' | 'neutral' {
  if (b === 'bullish') return 'buy'
  if (b === 'bearish') return 'sell'
  return 'neutral'
}

export function AnalysisCard({ ev, agent }: { ev: TvEvent; agent: 'intraday' | 'session-scalp' }) {
  const [open, setOpen] = useState(false)
  const chartUrl = ev.id ? api(`/${agent}/chart/${ev.id}`) : null
  const dr = ev.dealing_range

  return (
    <div className="glass rounded-xl overflow-hidden ring-1 ring-border hover:ring-tint/20 transition-all duration-300">
      <div className="p-4 space-y-3">
        {/* header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-text-primary font-semibold tracking-wide">{ev.name}</span>
            <span className="text-text-tertiary text-[11px] font-mono">{ev.symbol}</span>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={biasTone(ev.bias)}>{ev.bias}</Badge>
            <Badge variant="neutral">{ev.entry_tf}</Badge>
          </div>
        </div>

        {ev.news && ev.news.length > 0 && (
          <div className="text-[11px] text-loss bg-loss/10 ring-1 ring-loss/25 rounded-md px-2 py-1">
            ⚠️ News in horizon: {ev.news[0].title} ({ev.news[0].ccy}) · {ev.news[0].at}
          </div>
        )}

        {/* context line */}
        <div className="grid grid-cols-3 gap-2 text-[11px] font-mono text-text-secondary">
          <div>Price <span className="text-text-primary">{num(ev.price)}</span></div>
          {dr && <div>Range <span className="text-text-primary">{dr.zone}</span></div>}
          {dr && <div>EQ <span className="text-text-primary">{num(dr.equilibrium)}</span></div>}
          {ev.pdh != null && <div>PDH <span className="text-text-primary">{num(ev.pdh)}</span></div>}
          {ev.pdl != null && <div>PDL <span className="text-text-primary">{num(ev.pdl)}</span></div>}
          {ev.source && <div>via <span className="text-text-primary">{ev.source}</span></div>}
        </div>

        {/* chart */}
        {chartUrl && (
          <button onClick={() => setOpen(o => !o)} className="block w-full rounded-lg overflow-hidden bg-white ring-1 ring-border">
            <img src={chartUrl} alt={`${ev.symbol} chart`}
                 className={`w-full block transition-all ${open ? '' : 'max-h-56 object-cover object-left-top'}`}
                 loading="lazy" />
          </button>
        )}

        {/* entries */}
        <div className="space-y-1.5">
          {ev.entries.map((e, i) => (
            <div key={i} className="rounded-lg bg-tint/[0.03] ring-1 ring-border px-3 py-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant={e.side === 'BUY' ? 'buy' : 'sell'}>{e.side}</Badge>
                  <span className="text-[11px] text-text-tertiary">{e.type}</span>
                </div>
                <div className="flex items-center gap-2 text-[11px] font-mono">
                  {e.tier && <span className={`font-bold ${TIER_COLOR[e.tier] ?? ''}`}>{e.tier}{e.score != null ? ` ${e.score}` : ''}</span>}
                  <span className="text-accent">{e.win_prob}%</span>
                </div>
              </div>
              <div className="mt-1 grid grid-cols-4 gap-x-3 gap-y-0.5 text-[11px] font-mono text-text-secondary">
                <div>E <span className="text-text-primary">{num(e.entry)}</span></div>
                <div>SL <span className="text-loss">{num(e.sl)}</span></div>
                <div>TP1 <span className="text-profit">{num(e.tp1)}</span></div>
                <div>TP2 <span className="text-profit">{num(e.tp2)}</span></div>
              </div>
              <div className="mt-0.5 text-[10px] text-text-tertiary">
                RR 1:{e.rr[0]} / 1:{e.rr[e.rr.length - 1]} · {e.reasons.join(' · ')}
              </div>
            </div>
          ))}
        </div>

        {ev.narrative && (
          <p className="text-[11px] text-text-tertiary italic leading-relaxed">{ev.narrative}</p>
        )}
      </div>
    </div>
  )
}
