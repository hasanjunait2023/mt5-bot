import { useState, useEffect, useCallback, type ReactNode, type FormEvent } from 'react'
import { api, getToken, setToken, clearToken } from '../lib/api'

type Phase = 'checking' | 'open' | 'need-login' | 'authed'

/**
 * Gates the whole app behind a password ONLY when the backend has auth enabled
 * (DASHBOARD_PASSWORD set). When the backend reports auth_required=false the
 * gate is transparent — local/VPS same-origin keeps working with zero config.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('checking')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const checkStatus = useCallback(async () => {
    try {
      const res = await fetch(api('/api/auth/status'))
      const data = await res.json()
      if (!data.auth_required) { setPhase('open'); return }
      setPhase(getToken() ? 'authed' : 'need-login')
    } catch {
      // backend unreachable — let the app render and surface its own errors
      setPhase('open')
    }
  }, [])

  useEffect(() => { checkStatus() }, [checkStatus])

  // apiFetch fires this on any 401 → bounce back to the login screen
  useEffect(() => {
    const onUnauth = () => { clearToken(); setPhase('need-login') }
    window.addEventListener('mt5-dash-unauthorized', onUnauth)
    return () => window.removeEventListener('mt5-dash-unauthorized', onUnauth)
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(api('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail ?? 'Login failed')
        return
      }
      const data = await res.json()
      if (data.token) {
        setToken(data.token)
        setPassword('')
        setPhase('authed')
      } else {
        setPhase('open')
      }
    } catch {
      setError('Cannot reach the backend')
    } finally {
      setSubmitting(false)
    }
  }

  if (phase === 'checking') {
    return (
      <div className="min-h-screen grid place-items-center text-text-muted text-sm">
        Loading…
      </div>
    )
  }

  if (phase === 'need-login') {
    return (
      <div className="min-h-screen grid place-items-center px-4">
        <form onSubmit={submit} className="glass w-full max-w-sm p-7 space-y-5">
          <div>
            <p className="eyebrow mb-1">MT5 Dashboard</p>
            <h1 className="text-text-primary text-lg font-semibold">Sign in</h1>
            <p className="text-text-muted text-xs mt-1">
              This dashboard is protected. Enter the access password.
            </p>
          </div>
          <input
            type="password"
            autoFocus
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 h-11
                       text-text-primary text-sm outline-none focus:border-accent/60
                       focus:ring-1 focus:ring-accent/30 transition"
          />
          {error && <p className="text-loss text-xs">{error}</p>}
          <button
            type="submit"
            disabled={submitting || !password}
            className="w-full h-11 rounded-lg bg-accent text-bg-base font-semibold text-sm
                       hover:opacity-90 disabled:opacity-40 transition"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    )
  }

  // 'open' (auth disabled) or 'authed' (valid token held)
  return <>{children}</>
}
