import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../lib/api'

export interface HQCategory {
  label: string
  thread_id: number | null
  enabled: boolean
  icon_color?: number
}

export interface HQOutboxEntry {
  ts: string
  category: string
  level: 'INFO' | 'WARNING' | 'CRITICAL'
  title: string
  text: string
  ok: boolean
  skipped?: string
  error?: string | null
}

export interface HQState {
  group_chat_id: string | null
  setup_complete: boolean
  mirror_critical: boolean
  digest: { enabled?: boolean; hour_utc?: number; reminder_hours?: number }
  quiet_hours: { enabled?: boolean; start_utc?: number; end_utc?: number }
  categories: Record<string, HQCategory>
  outbox: HQOutboxEntry[]
}

export function useTelegramHQ() {
  const [data, setData] = useState<HQState | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    apiFetch('/api/telegram-hq')
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 15000)   // refresh outbox feed
    return () => clearInterval(id)
  }, [load])

  const save = useCallback(async (patch: Record<string, unknown>) => {
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch('/api/telegram-hq', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(err.detail ?? 'Save failed')
      } else {
        load()
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [load])

  const test = useCallback(async (category: string): Promise<boolean> => {
    try {
      const res = await apiFetch('/api/telegram-hq/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category }),
      })
      const j = await res.json().catch(() => ({ ok: false }))
      return !!j.ok
    } catch {
      return false
    }
  }, [])

  return { data, save, test, saving, error, reload: load }
}
