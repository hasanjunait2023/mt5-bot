import { useSettings } from '../hooks/useSettings'
import { useState, useEffect } from 'react'

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

  return (
    <div className="max-w-xl space-y-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold mb-1">Settings</h1>
        <p className="text-text-muted text-sm">Edit trading_system_config.json — changes apply on next agent cycle</p>
      </div>

      <div className="bg-bg-surface border border-border rounded-lg p-4 space-y-4">
        {fields.map(f => {
          const val = draft[f.key]
          if (f.type === 'bool') return (
            <div key={f.key} className="flex items-center justify-between">
              <label className="text-text-secondary text-sm">{f.label}</label>
              <button
                onClick={() => set(f.key, !val)}
                className={`w-10 h-5 rounded-full transition-colors relative ${val ? 'bg-profit' : 'bg-bg-elevated border border-border'}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${val ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>
          )
          if (f.type === 'tags') return (
            <div key={f.key}>
              <label className="text-text-secondary text-xs uppercase tracking-widest block mb-1">{f.label}</label>
              <input
                type="text"
                value={Array.isArray(val) ? val.join(', ') : ''}
                onChange={e => set(f.key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                className="w-full bg-bg-elevated border border-border rounded px-3 py-1.5 text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
              />
            </div>
          )
          return (
            <div key={f.key}>
              <label className="text-text-secondary text-xs uppercase tracking-widest block mb-1">{f.label}</label>
              <input
                type="number"
                step="any"
                value={val as number ?? ''}
                onChange={e => set(f.key, parseFloat(e.target.value))}
                className="w-full bg-bg-elevated border border-border rounded px-3 py-1.5 text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
              />
            </div>
          )
        })}
      </div>

      {error && <p className="text-loss text-sm">{error}</p>}

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="px-4 py-2 bg-accent text-white rounded text-sm font-semibold disabled:opacity-40 hover:bg-accent-dim transition-colors"
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        {dirty && <span className="text-warning text-xs">Unsaved changes</span>}
        {!dirty && !saving && <span className="text-profit text-xs">Saved</span>}
      </div>
    </div>
  )
}
