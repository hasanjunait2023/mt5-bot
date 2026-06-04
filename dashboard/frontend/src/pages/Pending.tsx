import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { apiFetch } from '../lib/api'
import { MetricCard } from '../components/ui/MetricCard'

interface Stalled {
  id: string
  name: string
  path: string
  age_s: number | null
  threshold_s: number
  reason: string
}
interface Task {
  id: string
  task: string
  deferred: string
  note: string
}
interface Payload {
  stalled: Stalled[]
  stalled_count: number
  scanned_at: string | null
  scan_age_minutes: number | null
  pending_tasks: Task[]
}

function fmtAge(s: number | null): string {
  if (s == null) return '—'
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

export function Pending() {
  const [data, setData] = useState<Payload | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const res = await apiFetch('/api/system-agents/pending')
        if (!res.ok) return
        const json = (await res.json()) as Payload
        if (alive) setData(json)
      } catch {
        /* ignore — transient */
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    const t = setInterval(load, 15000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const stalled = data?.stalled ?? []
  const tasks = data?.pending_tasks ?? []
  const scanAge = data?.scan_age_minutes

  return (
    <div className="space-y-4 md:space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Operations</p>
          <h1 className="text-2xl font-bold tracking-tight text-text-primary">Pending &amp; Stalled</h1>
        </div>
        <p className="text-xs text-text-muted font-mono">
          {scanAge == null ? 'no scan yet' : `last scan ${fmtAge(Math.round(scanAge * 60))} ago`}
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <MetricCard
          label="Stalled agents"
          value={String(data?.stalled_count ?? 0)}
          tone={(data?.stalled_count ?? 0) > 0 ? 'loss' : 'profit'}
          hero
        />
        <MetricCard label="Pending tasks" value={String(tasks.length)} tone="accent" />
      </div>

      {/* Stalled agents */}
      <section className="glass p-5">
        <p className="eyebrow mb-3">Stalled agents (auto-detected)</p>
        {loading ? (
          <p className="text-sm text-text-muted animate-pulse">Loading…</p>
        ) : stalled.length === 0 ? (
          <p className="text-sm text-profit">All supervised agents are progressing.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-text-muted text-xs uppercase tracking-wide">
                  <th className="py-2 pr-4 font-medium">Agent</th>
                  <th className="py-2 pr-4 font-medium">Why</th>
                  <th className="py-2 pr-4 font-medium text-right">Stale for</th>
                  <th className="py-2 font-medium text-right">Allowed</th>
                </tr>
              </thead>
              <tbody>
                {stalled.map((s) => (
                  <tr key={s.id} className="border-t border-border/60">
                    <td className="py-2.5 pr-4">
                      <span className="font-mono text-text-primary">{s.id}</span>
                      <span className="block text-xs text-text-muted">{s.name}</span>
                    </td>
                    <td className="py-2.5 pr-4 text-text-secondary">{s.reason}</td>
                    <td className="py-2.5 pr-4 text-right font-mono text-loss">{fmtAge(s.age_s)}</td>
                    <td className="py-2.5 text-right font-mono text-text-muted">{fmtAge(s.threshold_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Pending tasks */}
      <section className="glass p-5">
        <p className="eyebrow mb-3">Pending tasks (deferred on purpose)</p>
        {tasks.length === 0 ? (
          <p className="text-sm text-text-muted">No pending tasks.</p>
        ) : (
          <ul className="space-y-2">
            {tasks.map((t) => (
              <li
                key={t.id}
                className={clsx(
                  'flex items-start gap-3 rounded-lg p-3 bg-white/[0.02] ring-1 ring-border',
                )}
              >
                <span className="mt-0.5 shrink-0 w-6 h-6 grid place-items-center rounded-md
                                 bg-accent/15 text-accent text-xs font-mono">
                  {t.id}
                </span>
                <div className="min-w-0">
                  <p className="text-sm text-text-primary">{t.task}</p>
                  <p className="text-xs text-text-muted mt-0.5">
                    {t.note} <span className="opacity-60">· deferred {t.deferred}</span>
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
