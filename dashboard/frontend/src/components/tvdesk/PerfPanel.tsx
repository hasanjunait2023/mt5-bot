import { Panel } from '../ui/Panel'
import { Badge } from '../ui/Badge'

export interface PerfRollup { win: number; loss: number; n: number; win_rate: number }
export interface ClosedTrade {
  id: string; symbol: string; side: 'BUY' | 'SELL'; session?: string | null
  status: 'win' | 'loss' | 'expired'; r_multiple?: number | null
  entry: number; close_price?: number | null; close_ts?: number | null
}
export interface PerfData {
  generated_at?: string
  totals?: {
    recorded?: number; pending?: number; active?: number; no_fill?: number
    win?: number; loss?: number; expired?: number
    win_rate?: number | null; total_R?: number; avg_R?: number | null
  }
  by_symbol?: Record<string, PerfRollup>
  by_session?: Record<string, PerfRollup>
  recent_closed?: ClosedTrade[]
}

function Bar({ rate }: { rate: number }) {
  const tone = rate >= 55 ? 'bg-profit' : rate >= 45 ? 'bg-accent' : 'bg-loss'
  return (
    <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
      <div className={`h-full ${tone}`} style={{ width: `${Math.max(2, Math.min(100, rate))}%` }} />
    </div>
  )
}

function RollupTable({ title, data }: { title: string; data: Record<string, PerfRollup> }) {
  const rows = Object.entries(data).sort((a, b) => b[1].n - a[1].n)
  if (rows.length === 0) return null
  return (
    <div className="space-y-2">
      <div className="eyebrow">{title}</div>
      {rows.map(([k, r]) => (
        <div key={k} className="grid grid-cols-[5rem_1fr_4rem] items-center gap-3 text-xs font-mono">
          <span className="text-text-secondary truncate">{k}</span>
          <Bar rate={r.win_rate} />
          <span className="text-right text-text-primary">{r.win_rate}% <span className="text-text-tertiary">({r.n})</span></span>
        </div>
      ))}
    </div>
  )
}

function fmtTs(ts?: number | null): string {
  if (!ts) return '—'
  try { return new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return '—' }
}

export function PerfPanel({ perf, showSession = false, i = 1 }: { perf: PerfData | null; showSession?: boolean; i?: number }) {
  const t = perf?.totals ?? {}
  const closed = perf?.recent_closed ?? []
  const hasData = (t.win ?? 0) + (t.loss ?? 0) + (t.expired ?? 0) > 0

  return (
    <Panel i={i} title="Performance (measured)" right={
      <span className="text-[11px] text-text-tertiary font-mono">
        {t.pending ?? 0} pending · {t.active ?? 0} active · {t.no_fill ?? 0} no-fill
      </span>
    }>
      {!hasData ? (
        <div className="text-text-tertiary text-sm py-6 text-center">
          No closed trades yet — measurement phase. Win-rate appears as setups resolve against price.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-5">
            {perf?.by_symbol && <RollupTable title="Win rate by symbol" data={perf.by_symbol} />}
            {showSession && perf?.by_session && <RollupTable title="Win rate by session" data={perf.by_session} />}
          </div>
          <div className="space-y-2">
            <div className="eyebrow">Recent closed</div>
            <div className="space-y-1 max-h-72 overflow-auto pr-1">
              {closed.map(tr => (
                <div key={tr.id} className="flex items-center justify-between text-xs font-mono rounded-md bg-white/[0.03] ring-1 ring-border px-2.5 py-1.5">
                  <div className="flex items-center gap-2">
                    <Badge variant={tr.side === 'BUY' ? 'buy' : 'sell'}>{tr.side}</Badge>
                    <span className="text-text-secondary">{tr.symbol}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={tr.status === 'win' ? 'text-profit' : tr.status === 'loss' ? 'text-loss' : 'text-text-tertiary'}>
                      {tr.status.toUpperCase()}
                    </span>
                    <span className={(tr.r_multiple ?? 0) >= 0 ? 'text-profit' : 'text-loss'}>
                      {tr.r_multiple != null ? `${tr.r_multiple > 0 ? '+' : ''}${tr.r_multiple}R` : '—'}
                    </span>
                    <span className="text-text-tertiary">{fmtTs(tr.close_ts)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}
