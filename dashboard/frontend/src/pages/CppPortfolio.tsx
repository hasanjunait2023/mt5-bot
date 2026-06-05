import { useState, useEffect } from 'react'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusDot } from '../components/ui/StatusDot'
import { apiFetch } from '../lib/api'

interface PerSym { wins: number; losses: number; pnl: number }
interface Daily {
  date: string
  wins: number; losses: number; trades: number; win_rate: number
  daily_pnl: number; floating_pnl: number
  daily_dd_pct: number; dd_limit_pct: number; dd_breaker_tripped: boolean
  target: { wins: number; losses: number; dd: number }
  target_hit: boolean
  per_symbol: Record<string, PerSym>
  recent_trades: { symbol: string; pnl: number; time: string }[]
}
interface Resp {
  daily: Daily
  runner: {
    online: boolean; running: boolean; agent_mode: string
    dd_breaker_tripped: boolean; symbols: string[]
    last_signals: Record<string, string | null>; ts: string | null
  }
  agent: { calls: number; claude: number; nvidia: number; errors: number; fallback_pct: number }
}

export function CppPortfolio() {
  const [d, setD] = useState<Resp | null>(null)

  useEffect(() => {
    const pull = () =>
      apiFetch('/api/cpp/daily').then(r => r.json()).then(setD).catch(() => {})
    pull()
    const id = setInterval(pull, 10000)
    return () => clearInterval(id)
  }, [])

  const day = d?.daily
  const run = d?.runner
  const ag = d?.agent
  const ddTone = day?.dd_breaker_tripped ? 'loss' : day && day.daily_dd_pct > day.dd_limit_pct * 0.66 ? 'loss' : 'neutral'
  const pnlTone = (day?.daily_pnl ?? 0) >= 0 ? 'profit' : 'loss'

  return (
    <div className="space-y-5">
      <PageHeader
        title="CPP — Unified Portfolio"
        subtitle="CPP-FX (EUR/GBP/JPY, hybrid agent, strict 1:2) + S1/S15/S18 on Gold/Silver — one 1%-risk, 6%-daily-DD system"
        right={
          <div className="flex items-center gap-2 text-sm">
            <StatusDot status={run?.online ? 'running' : 'offline'} />
            <span className="text-text-secondary">
              {run?.online ? `runner live · agent ${run?.agent_mode}` : 'runner offline'}
            </span>
          </div>
        }
      />

      <Panel bare className="p-4 text-sm text-text-secondary">
        <span className="text-text-primary font-semibold">Honest target context: </span>
        the 15–20 wins / ≤6 losses goal is the aspiration we measure against, not a promise —
        backtests show ~1–3 high-quality 1:2 trades/day is the realistic profitable rate on
        these markets. This panel tracks the real daily numbers vs that target and the hard 6%
        cutoff. Real money stays gated behind the demo promotion gate.
      </Panel>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          hero
          tone={day?.target_hit ? 'profit' : 'accent'}
          label={`Wins today (target ≥${day?.target.wins ?? 15})`}
          value={day?.wins ?? 0}
          suffix={` / ${day?.losses ?? 0}L`}
          right={<span className="eyebrow">{day?.target_hit ? 'TARGET HIT' : 'tracking'}</span>}
        />
        <MetricCard
          label={`Daily P&L${day?.floating_pnl ? ' (+float)' : ''}`}
          value={day?.daily_pnl ?? 0}
          prefix="$"
          tone={pnlTone}
          positive={(day?.daily_pnl ?? 0) >= 0}
        />
        <MetricCard
          label={`Daily DD (breaker ${day?.dd_limit_pct ?? 6}%)`}
          value={day?.daily_dd_pct ?? 0}
          suffix="%"
          tone={ddTone}
          right={day?.dd_breaker_tripped ? <span className="eyebrow text-loss">HALTED</span> : undefined}
        />
        <MetricCard
          label="Win rate today"
          value={day?.win_rate ?? 0}
          suffix="%"
          tone="neutral"
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <Panel title="Per-symbol contribution today" i={0}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-secondary border-b border-border">
                <th className="text-left py-2">Symbol</th>
                <th className="text-right">Wins</th>
                <th className="text-right">Losses</th>
                <th className="text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(day?.per_symbol ?? {}).length === 0 && (
                <tr><td colSpan={4} className="py-4 text-text-secondary text-center">No closed trades yet today</td></tr>
              )}
              {Object.entries(day?.per_symbol ?? {}).map(([s, v]) => (
                <tr key={s} className="border-b border-line/50">
                  <td className="py-2 text-text-primary font-medium">{s}</td>
                  <td className="text-right text-profit">{v.wins}</td>
                  <td className="text-right text-loss">{v.losses}</td>
                  <td className={`text-right ${v.pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                    ${v.pnl.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Hybrid agent + runner" i={1}>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <dt className="text-text-secondary">Agent mode</dt>
            <dd className="text-text-primary text-right">{run?.agent_mode ?? '—'}</dd>
            <dt className="text-text-secondary">Agent calls (recent)</dt>
            <dd className="text-text-primary text-right">{ag?.calls ?? 0}</dd>
            <dt className="text-text-secondary">Claude / NVIDIA</dt>
            <dd className="text-text-primary text-right">{ag?.claude ?? 0} / {ag?.nvidia ?? 0}</dd>
            <dt className="text-text-secondary">LLM fallback rate</dt>
            <dd className={`text-right ${(ag?.fallback_pct ?? 0) > 30 ? 'text-loss' : 'text-text-primary'}`}>
              {ag?.fallback_pct ?? 0}%
            </dd>
            <dt className="text-text-secondary">DD breaker</dt>
            <dd className={`text-right ${run?.dd_breaker_tripped ? 'text-loss' : 'text-profit'}`}>
              {run?.dd_breaker_tripped ? 'TRIPPED — no new entries' : 'armed'}
            </dd>
            <dt className="text-text-secondary">FX symbols</dt>
            <dd className="text-text-primary text-right">{(run?.symbols ?? []).join(' ') || '—'}</dd>
          </dl>
          <div className="mt-4 pt-3 border-t border-border">
            <p className="eyebrow mb-2">Last signal per symbol</p>
            {Object.entries(run?.last_signals ?? {}).map(([s, v]) => (
              <div key={s} className="flex justify-between text-xs py-1">
                <span className="text-text-secondary">{s}</span>
                <span className="text-text-primary truncate ml-3">{v ?? 'no setup'}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Recent closed trades (all strategies)" i={2}>
        <div className="flex flex-wrap gap-2">
          {(day?.recent_trades ?? []).length === 0 && (
            <span className="text-text-secondary text-sm">Nothing closed yet today.</span>
          )}
          {(day?.recent_trades ?? []).map((t, i) => (
            <span
              key={i}
              className={`text-xs px-2.5 py-1 rounded-md ring-1 ${
                t.pnl >= 0 ? 'ring-profit/30 text-profit' : 'ring-loss/30 text-loss'
              }`}
            >
              {t.time} {t.symbol} ${t.pnl.toFixed(2)}
            </span>
          ))}
        </div>
      </Panel>
    </div>
  )
}
