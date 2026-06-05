import { useSettings } from '../hooks/useSettings'
import { useState, useEffect } from 'react'
import clsx from 'clsx'
import { Panel } from '../components/ui/Panel'
import { PageHeader } from '../components/ui/PageHeader'

const inputCls =
  'w-full h-9 bg-tint/[0.04] ring-1 ring-border rounded-lg px-3 text-sm ' +
  'text-text-primary font-mono placeholder-text-muted ' +
  'focus:outline-none focus:ring-accent transition-shadow'

export function Settings() {
  const { config, save, saving, error } = useSettings()
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setDraft(config)
    setDirty(false)
  }, [config])

  function set(key: string, value: unknown) {
    setDraft(d => ({ ...d, [key]: value }))
    setDirty(true)
  }

  function handleSave() {
    save(draft).then(() => setDirty(false))
  }

  const fields: Array<{ key: string; label: string; type: 'number' | 'bool' | 'tags' }> = [
    { key: 'account_balance',              label: 'Account Balance ($)',         type: 'number' },
    { key: 'max_risk_per_trade',           label: 'Max Risk per Trade (0–0.05)', type: 'number' },
    { key: 'max_daily_loss_pct',           label: 'Max Daily Loss %',           type: 'number' },
    { key: 'max_daily_trades',             label: 'Max Daily Trades',            type: 'number' },
    { key: 'research_interval_hours',      label: 'Research Interval (hrs)',     type: 'number' },
    { key: 'optimization_interval_hours',  label: 'Optimization Interval (hrs)', type: 'number' },
    { key: 'health_check_interval_minutes',label: 'Health Check Interval (min)', type: 'number' },
    { key: 'enable_live_trading',          label: 'Enable Live Trading',         type: 'bool' },
    { key: 'demo_account',                 label: 'Demo Account',                type: 'bool' },
    { key: 'symbols',                      label: 'Symbols (comma-separated)',    type: 'tags' },
  ]

  const toggles = fields.filter(f => f.type === 'bool')
  const inputs  = fields.filter(f => f.type !== 'bool')

  return (
    <div className="max-w-2xl space-y-4 md:space-y-6">
      <PageHeader
        title="Settings"
        subtitle="Edit trading_system_config.json — changes apply on next agent cycle"
      />

      <Panel title="Trading Parameters" i={0}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-4">
          {inputs.map(f => {
            const val = draft[f.key]
            return (
              <div key={f.key}>
                <label className="eyebrow block mb-1.5">{f.label}</label>
                {f.type === 'tags' ? (
                  <input
                    type="text"
                    value={Array.isArray(val) ? val.join(', ') : ''}
                    onChange={e => set(f.key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                    className={inputCls}
                  />
                ) : (
                  <input
                    type="number"
                    step="any"
                    value={(val as number) ?? ''}
                    onChange={e => set(f.key, parseFloat(e.target.value))}
                    className={inputCls}
                  />
                )}
              </div>
            )
          })}
        </div>
      </Panel>

      <Panel title="Toggles" i={1}>
        <div className="space-y-1">
          {toggles.map(f => {
            const val = !!draft[f.key]
            return (
              <div
                key={f.key}
                className="flex items-center justify-between py-2.5 border-b border-tint/[0.05] last:border-0"
              >
                <label className="text-text-primary text-sm">{f.label}</label>
                <button
                  role="switch"
                  aria-checked={val}
                  onClick={() => set(f.key, !val)}
                  className={clsx(
                    'w-11 h-6 rounded-full transition-colors relative shrink-0',
                    val ? 'bg-profit shadow-glow-profit' : 'bg-tint/[0.06] ring-1 ring-border',
                  )}
                >
                  <span
                    className={clsx(
                      'absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform',
                      val ? 'translate-x-[22px]' : 'translate-x-0.5',
                    )}
                  />
                </button>
              </div>
            )
          })}
        </div>
      </Panel>

      {error && (
        <p className="text-loss text-sm bg-loss/10 ring-1 ring-loss/25 rounded-lg px-3 py-2">{error}</p>
      )}

      <div className="flex items-center gap-3 sticky bottom-0 py-3">
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className={clsx(
            'px-5 h-10 rounded-lg text-sm font-semibold transition-all',
            'bg-accent text-white hover:bg-accent-dim',
            'disabled:opacity-40 disabled:hover:bg-accent',
            dirty && !saving && 'shadow-glow-accent',
          )}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        {dirty
          ? <span className="text-warning text-xs font-medium">● Unsaved changes</span>
          : !saving && <span className="text-profit text-xs font-medium">✓ Saved</span>}
      </div>
    </div>
  )
}
