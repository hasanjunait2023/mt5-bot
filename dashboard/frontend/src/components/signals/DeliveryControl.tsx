import { useEffect, useState } from 'react'
import { Panel } from '../ui/Panel'
import { apiFetch } from '../../lib/api'

interface Window {
  id: string
  label: string
  start: string
  end: string
  enabled: boolean
}

interface DeliveryConfig {
  master_enabled: boolean
  windows_mode: boolean
  brief_ignores_windows: boolean
  windows: Window[]
  channels: Record<string, boolean>
}

interface DeliveryStatus {
  config: DeliveryConfig
  now_bd: string
  in_window: boolean
  live: Record<string, boolean>
}

const CHANNEL_GROUPS: { group: string; items: { key: string; label: string }[] }[] = [
  {
    group: 'Classic',
    items: [
      { key: 'signal_alignment', label: '4-TF Alignment' },
      { key: 'signal_cross',     label: '9/15 Cross' },
      { key: 'signal_touch',     label: '200 EMA Touch' },
    ],
  },
  {
    group: 'Improved',
    items: [{ key: 'signal_improved', label: 'Improved (Phase 1)' }],
  },
  {
    group: 'Alpha Desk',
    items: [
      { key: 'alpha_signal',     label: 'Live Signals' },
      { key: 'alpha_confluence', label: 'Confluence Stack' },
      { key: 'alpha_brief',      label: 'Session Briefs' },
    ],
  },
]

function Toggle({ on, onClick, label, sub }: { on: boolean; onClick: () => void; label: string; sub?: string }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center justify-between gap-3 w-full p-2.5 rounded-lg
                 bg-tint/[0.025] ring-1 ring-border hover:bg-tint/[0.04] transition-all text-left"
    >
      <div className="min-w-0">
        <div className="text-sm text-text-primary font-medium truncate">{label}</div>
        {sub && <div className="text-[11px] text-text-tertiary">{sub}</div>}
      </div>
      <span className={`relative shrink-0 w-9 h-5 rounded-full transition-colors ${on ? 'bg-emerald-500/70' : 'bg-tint/[0.08]'}`}>
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${on ? 'left-[18px]' : 'left-0.5'}`} />
      </span>
    </button>
  )
}

export function DeliveryControl() {
  const [status, setStatus] = useState<DeliveryStatus | null>(null)
  const [cfg, setCfg] = useState<DeliveryConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  const load = async () => {
    try {
      const r = await apiFetch('/signals/delivery')
      if (!r.ok) return
      const s: DeliveryStatus = await r.json()
      setStatus(s)
      setCfg(s.config)
    } catch {}
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 20_000)
    return () => clearInterval(id)
  }, [])

  const save = async (next: DeliveryConfig) => {
    setSaving(true)
    setCfg(next)        // optimistic
    try {
      const r = await apiFetch('/signals/delivery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      })
      if (r.ok) {
        setSavedAt(new Date().toLocaleTimeString())
        await load()
      }
    } catch {} finally {
      setSaving(false)
    }
  }

  if (!cfg) {
    return <Panel title="Delivery Control"><div className="text-text-tertiary text-sm">Loading…</div></Panel>
  }

  const setMaster   = (v: boolean) => save({ ...cfg, master_enabled: v })
  const setWinMode  = (v: boolean) => save({ ...cfg, windows_mode: v })
  const setChannel  = (k: string, v: boolean) => save({ ...cfg, channels: { ...cfg.channels, [k]: v } })
  const setWindow   = (id: string, patch: Partial<Window>) =>
    save({ ...cfg, windows: cfg.windows.map(w => w.id === id ? { ...w, ...patch } : w) })

  const liveCount = status ? Object.values(status.live).filter(Boolean).length : 0
  const totalCh   = Object.keys(cfg.channels).length

  return (
    <Panel
      title="Delivery Control"
      right={
        <div className="flex items-center gap-3">
          {status && (
            <span className={`text-[11px] font-mono px-2 py-0.5 rounded-md ring-1 ${
              status.in_window
                ? 'text-emerald-300 ring-emerald-500/30 bg-emerald-500/10'
                : 'text-text-tertiary ring-border bg-tint/[0.03]'
            }`}>
              {status.now_bd} BD · {status.in_window ? 'IN WINDOW' : 'OUTSIDE WINDOW'}
            </span>
          )}
          <span className="text-[11px] text-text-tertiary">{liveCount}/{totalCh} live</span>
          <button
            onClick={() => setOpen(o => !o)}
            className="text-[11px] px-2 h-6 rounded-md bg-tint/[0.05] ring-1 ring-border
                       text-text-secondary hover:text-text-primary"
          >
            {open ? 'Collapse' : 'Expand'}
          </button>
        </div>
      }
    >
      {/* Always-visible master row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <Toggle
          on={cfg.master_enabled}
          onClick={() => setMaster(!cfg.master_enabled)}
          label={cfg.master_enabled ? 'Signals ON' : 'Signals OFF'}
          sub="Master switch — turns all delivery on/off"
        />
        <Toggle
          on={cfg.windows_mode}
          onClick={() => setWinMode(!cfg.windows_mode)}
          label={cfg.windows_mode ? 'Time windows ON' : '24/5 (no time limit)'}
          sub="Restrict delivery to your chosen hours"
        />
      </div>

      {open && (
        <div className="mt-4 space-y-5">
          {/* Time windows */}
          <div>
            <div className="eyebrow mb-2">Time Windows (BD time)</div>
            <div className="space-y-2">
              {cfg.windows.map(w => (
                <div key={w.id} className={`flex items-center gap-3 p-2.5 rounded-lg ring-1 transition-all ${
                  w.enabled ? 'bg-tint/[0.03] ring-border' : 'bg-tint/[0.01] ring-line/50 opacity-60'
                }`}>
                  <button
                    onClick={() => setWindow(w.id, { enabled: !w.enabled })}
                    className={`relative shrink-0 w-9 h-5 rounded-full transition-colors ${w.enabled ? 'bg-emerald-500/70' : 'bg-tint/[0.08]'}`}
                  >
                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${w.enabled ? 'left-[18px]' : 'left-0.5'}`} />
                  </button>
                  <span className="text-sm text-text-primary font-medium w-20">{w.label}</span>
                  <input
                    type="time"
                    value={w.start}
                    onChange={e => setWindow(w.id, { start: e.target.value })}
                    className="bg-bg-base ring-1 ring-border rounded-md px-2 h-8 text-sm font-mono text-text-primary"
                  />
                  <span className="text-text-tertiary">→</span>
                  <input
                    type="time"
                    value={w.end}
                    onChange={e => setWindow(w.id, { end: e.target.value })}
                    className="bg-bg-base ring-1 ring-border rounded-md px-2 h-8 text-sm font-mono text-text-primary"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Channels */}
          <div>
            <div className="eyebrow mb-2">Signal Channels</div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {CHANNEL_GROUPS.map(g => (
                <div key={g.group}>
                  <div className="text-[11px] uppercase tracking-wider text-text-tertiary mb-1.5">{g.group}</div>
                  <div className="space-y-1.5">
                    {g.items.map(item => {
                      const isLive = status?.live?.[item.key]
                      return (
                        <Toggle
                          key={item.key}
                          on={cfg.channels[item.key] ?? true}
                          onClick={() => setChannel(item.key, !(cfg.channels[item.key] ?? true))}
                          label={item.label}
                          sub={isLive ? '● delivering now' : '○ silent now'}
                        />
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="text-[11px] text-text-tertiary">
            {saving ? 'Saving…' : savedAt ? `Saved ${savedAt}` : 'Changes save automatically.'}
            {' · '}Briefs fire at their scheduled time even outside windows (toggle off to silence).
          </div>
        </div>
      )}
    </Panel>
  )
}
