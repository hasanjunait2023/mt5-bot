import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../lib/api'

export function useSettings() {
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch('/api/settings')
      .then(r => r.json())
      .then(setConfig)
      .catch(() => {})
  }, [])

  const save = useCallback(async (patch: Record<string, unknown>) => {
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) {
        const err = await res.json()
        setError(err.detail ?? 'Save failed')
      } else {
        const updated = await res.json()
        setConfig(updated)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [])

  return { config, setConfig, save, saving, error }
}
