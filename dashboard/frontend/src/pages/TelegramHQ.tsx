import { useState } from 'react'
import clsx from 'clsx'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'
import { Badge } from '../components/ui/Badge'
import { useTelegramHQ } from '../hooks/useTelegramHQ'

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={onClick}
      className={clsx(
        'w-11 h-6 rounded-full transition-colors relative shrink-0',
        on ? 'bg-profit shadow-glow-profit' : 'bg-white/[0.06] ring-1 ring-border',
      )}
    >
      <span
        className={clsx(
          'absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform',
          on ? 'translate-x-[22px]' : 'translate-x-0.5',
        )}
      />
    </button>
  )
}

const LEVEL_VARIANT = {
  INFO: 'info',
  WARNING: 'sell',
  CRITICAL: 'sell',
} as const

export function TelegramHQ() {
  const { data, save, test, saving, error } = useTelegramHQ()
  const [testing, setTesting] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  if (!data) {
    return (
      <div className="max-w-3xl">
        <PageHeader title="Telegram HQ" subtitle="Loading routing map…" />
      </div>
    )
  }

  const cats = Object.entries(data.categories)

  async function runTest(key: string) {
    setTesting(key)
    const ok = await test(key)
    setTesting(null)
    setToast(ok ? `Test sent to "${data!.categories[key].label}"` : 'Send failed — check setup')
    setTimeout(() => setToast(null), 3500)
  }

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Telegram HQ"
        subtitle="Every team posts to its own forum topic. Approvals and Maic chat work two-way."
        right={
          <Badge variant={data.setup_complete ? 'buy' : 'sell'}>
            {data.setup_complete ? 'CONNECTED' : 'NOT SET UP'}
          </Badge>
        }
      />

      {!data.setup_complete && (
        <Panel title="Setup" i={0}>
          <ol className="text-sm text-text-secondary space-y-1.5 list-decimal pl-5">
            <li>Create a Telegram <b>supergroup</b> and enable <b>Topics</b> (group settings → Topics).</li>
            <li>Add your bot to the group and make it an <b>admin</b> with <b>Manage Topics</b>.</li>
            <li>In the group, send <code className="text-accent">/hq_setup</code> — the bot creates all 10 topics automatically.</li>
          </ol>
          <p className="text-text-muted text-xs mt-3">
            Group: <span className="font-mono">{data.group_chat_id ?? 'not linked yet'}</span>
          </p>
        </Panel>
      )}

      <Panel title="Topic Routing" i={1}>
        <div className="space-y-1">
          {cats.map(([key, c]) => (
            <div
              key={key}
              className="flex items-center justify-between gap-3 py-2.5 border-b border-white/[0.05] last:border-0"
            >
              <div className="min-w-0">
                <p className="text-text-primary text-sm truncate">{c.label}</p>
                <p className="text-text-muted text-[11px] font-mono">
                  {key} · thread {c.thread_id ?? '—'}
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button
                  onClick={() => runTest(key)}
                  disabled={testing === key || !data.setup_complete}
                  className="px-2.5 h-7 rounded-md text-[11px] font-semibold ring-1 ring-border
                             text-text-secondary hover:text-text-primary hover:bg-white/[0.04]
                             disabled:opacity-40 transition-colors"
                >
                  {testing === key ? 'Sending…' : 'Test'}
                </button>
                <Toggle
                  on={c.enabled}
                  onClick={() => save({ categories: { [key]: { enabled: !c.enabled } } })}
                />
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Behavior" i={2}>
        <div className="space-y-1">
          <Row label="Mirror every CRITICAL to the Critical Alerts topic">
            <Toggle
              on={data.mirror_critical}
              onClick={() => save({ mirror_critical: !data.mirror_critical })}
            />
          </Row>
          <Row label="Daily digest (rollup + pending approvals)">
            <Toggle
              on={!!data.digest.enabled}
              onClick={() => save({ digest: { enabled: !data.digest.enabled } })}
            />
          </Row>
          <Row label="Digest hour (UTC)">
            <NumberStepper
              value={data.digest.hour_utc ?? 6}
              min={0}
              max={23}
              onChange={v => save({ digest: { hour_utc: v } })}
            />
          </Row>
          <Row label="Approval reminder every (hours)">
            <NumberStepper
              value={data.digest.reminder_hours ?? 6}
              min={1}
              max={48}
              onChange={v => save({ digest: { reminder_hours: v } })}
            />
          </Row>
        </div>
      </Panel>

      <Panel title="Recent Notifications" i={3}>
        {data.outbox.length === 0 ? (
          <p className="text-text-muted text-sm">Nothing sent yet.</p>
        ) : (
          <div className="space-y-1 max-h-[420px] overflow-y-auto">
            {[...data.outbox].reverse().map((e, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 py-1.5 font-mono text-xs border-l-2 pl-2.5 rounded-r
                           border-transparent hover:bg-white/[0.025]"
              >
                <span className="text-text-muted shrink-0 w-36 tabular-nums">
                  {e.ts.replace('T', ' ').slice(0, 19)}
                </span>
                <span className="shrink-0">
                  <Badge variant={LEVEL_VARIANT[e.level] ?? 'neutral'}>{e.level}</Badge>
                </span>
                <span className="text-text-secondary shrink-0 w-28 truncate">{e.category}</span>
                <span className="flex-1 break-all text-text-primary">
                  {e.title} — {e.text.slice(0, 140)}
                  {e.skipped && <span className="text-text-muted"> · skipped: {e.skipped}</span>}
                  {!e.ok && !e.skipped && <span className="text-loss"> · failed</span>}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {error && (
        <p className="text-loss text-sm bg-loss/10 ring-1 ring-loss/25 rounded-lg px-3 py-2">{error}</p>
      )}
      {toast && (
        <div className="fixed bottom-20 md:bottom-6 right-6 px-4 py-2.5 rounded-lg
                        bg-bg-surface/90 backdrop-blur-xl ring-1 ring-border
                        text-sm text-text-primary shadow-glow-accent z-50">
          {toast}
        </div>
      )}
      {saving && <span className="sr-only">saving</span>}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-white/[0.05] last:border-0">
      <label className="text-text-primary text-sm">{label}</label>
      {children}
    </div>
  )
}

function NumberStepper({
  value, min, max, onChange,
}: { value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      value={value}
      onChange={e => {
        const v = parseInt(e.target.value, 10)
        if (!Number.isNaN(v) && v >= min && v <= max) onChange(v)
      }}
      className="w-20 h-8 bg-white/[0.04] ring-1 ring-border rounded-lg px-2 text-sm
                 text-text-primary font-mono text-center focus:outline-none focus:ring-accent"
    />
  )
}
