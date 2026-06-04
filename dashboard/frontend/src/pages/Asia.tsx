import { useEffect, useState } from 'react'
import { Panel } from '../components/ui/Panel'
import { Badge } from '../components/ui/Badge'
import { StatusDot } from '../components/ui/StatusDot'
import { apiFetch } from '../lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────
interface AsiaPosition {
  symbol: string
  dir: 'BUY' | 'SELL'
  volume: number
  entry: number
  sl: number
  tp: number
  profit: number
}

interface AsiaRange { high: number; low: number; width: number }

interface AsiaState {
  timestamp?: string
  strategy?: string
  symbols?: string[]
  magic?: number
  equity?: number | null
  balance?: number | null
  open_positions?: AsiaPosition[]
  daily_trades?: Record<string, number>
  ranges?: Record<string, AsiaRange>
  session_window_utc?: string
}

interface BtPair {
  symbol: string; pf: number; pf_oos: number; wr: number
  trades: number; dd_pips: number; deployed: boolean
}
interface Backtest {
  window: string
  deployed: string[]
  pairs: BtPair[]
  rejected: { strategy: string; note: string }[]
}

export function Asia() {
  const [state, setState] = useState<AsiaState | null>(null)
  const [bt, setBt] = useState<Backtest | null>(null)

  useEffect(() => {
    const load = () => {
      apiFetch('/asia/state').then(r => r.ok ? r.json() : null).then(d => d && setState(d)).catch(() => {})
    }
    load()
    apiFetch('/asia/backtest').then(r => r.ok ? r.json() : null).then(d => d && setBt(d)).catch(() => {})
    const id = setInterval(load, 15000)
    return () => clearInterval(id)
  }, [])

  const ts = state?.timestamp ? new Date(state.timestamp) : null
  const fresh = ts ? (Date.now() - ts.getTime()) < 20 * 60 * 1000 : false
  const positions = state?.open_positions ?? []
  const ranges = Object.entries(state?.ranges ?? {})

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Asia Desk</p>
          <h1 className="text-2xl font-semibold">Asian Range Fade</h1>
          <p className="text-sm text-white/50 mt-1">
            Mean reversion on JPY pairs · session {state?.session_window_utc ?? '02:00-07:00'} UTC ·
            flattens before London
          </p>
        </div>
        <StatusDot status={fresh ? 'running' : 'stopped'} label={fresh ? 'Live' : 'Stale / stopped'} />
      </div>

      {/* Live metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Panel className="p-4">
          <p className="eyebrow">Equity</p>
          <p className="text-xl font-semibold">${state?.equity?.toFixed(2) ?? '—'}</p>
        </Panel>
        <Panel className="p-4">
          <p className="eyebrow">Open positions</p>
          <p className="text-xl font-semibold">{positions.length}</p>
        </Panel>
        <Panel className="p-4">
          <p className="eyebrow">Trades today</p>
          <p className="text-xl font-semibold">
            {Object.values(state?.daily_trades ?? {}).reduce((a, b) => a + b, 0)}
          </p>
        </Panel>
        <Panel className="p-4">
          <p className="eyebrow">Magic</p>
          <p className="text-xl font-semibold">{state?.magic ?? 20260800}</p>
        </Panel>
      </div>

      {/* Open positions */}
      <Panel className="p-5">
        <h2 className="text-lg font-medium mb-3">Open positions</h2>
        {positions.length === 0 ? (
          <p className="text-sm text-white/40">No open positions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-white/50 text-left">
              <tr><th className="py-1">Symbol</th><th>Dir</th><th>Vol</th><th>Entry</th>
                <th>SL</th><th>TP</th><th>P&L</th></tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="py-1.5 font-medium">{p.symbol}</td>
                  <td><Badge tone={p.dir === 'BUY' ? 'green' : 'red'}>{p.dir}</Badge></td>
                  <td>{p.volume}</td><td>{p.entry}</td><td>{p.sl}</td><td>{p.tp}</td>
                  <td className={p.profit >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    ${p.profit?.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {/* Today's Asian ranges */}
      <Panel className="p-5">
        <h2 className="text-lg font-medium mb-3">Today's Asian range (00:00–02:00 UTC)</h2>
        {ranges.length === 0 ? (
          <p className="text-sm text-white/40">Range not yet formed.</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {ranges.map(([sym, r]) => (
              <div key={sym} className="rounded-lg bg-white/5 p-3">
                <p className="font-medium">{sym}</p>
                <p className="text-xs text-white/50">H {r.high} · L {r.low}</p>
                <p className="text-xs text-white/40">width {r.width}</p>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {/* Validated backtest */}
      {bt && (
        <Panel className="p-5">
          <h2 className="text-lg font-medium">Validated backtest</h2>
          <p className="text-xs text-white/40 mb-3">{bt.window}</p>
          <table className="w-full text-sm">
            <thead className="text-white/50 text-left">
              <tr><th className="py-1">Pair</th><th>PF</th><th>PF (oos)</th><th>WR</th>
                <th>Trades</th><th>DD</th><th>Status</th></tr>
            </thead>
            <tbody>
              {bt.pairs.map((p) => (
                <tr key={p.symbol} className="border-t border-white/5">
                  <td className="py-1.5 font-medium">{p.symbol}</td>
                  <td>{p.pf.toFixed(2)}</td>
                  <td className={p.pf_oos >= 1.3 ? 'text-emerald-400' : 'text-amber-400'}>
                    {p.pf_oos.toFixed(2)}
                  </td>
                  <td>{p.wr.toFixed(1)}%</td><td>{p.trades}</td><td>{p.dd_pips}p</td>
                  <td>
                    <Badge tone={p.deployed ? 'green' : 'gray'}>
                      {p.deployed ? 'DEPLOYED' : 'hold'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-white/40 mt-4 mb-1">Rejected (failed real-cost / long-history):</p>
          <ul className="text-xs text-white/50 space-y-0.5">
            {bt.rejected.map((r) => (
              <li key={r.strategy}>· <span className="text-white/70">{r.strategy}</span> — {r.note}</li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  )
}
