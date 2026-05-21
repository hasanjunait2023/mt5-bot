// Centralized API / WebSocket base + auth-token handling.
//
// Default (empty env)  → relative paths. Works unchanged for:
//   - local dev   (Vite proxy in vite.config.ts forwards /api and /ws)
//   - VPS deploy  (frontend served same-origin as the FastAPI backend)
//
// On Vercel set in the Vercel project env (NOT committed):
//   VITE_API_BASE = https://api.yourdomain.com
//   VITE_WS_BASE  = wss://api.yourdomain.com   (optional; derived if omitted)
//
// Auth: when the backend has DASHBOARD_PASSWORD set, every /api call needs a
// bearer token and the WS needs ?token=. The token is obtained via the login
// screen (AuthGate) and kept in localStorage. When the backend has no password,
// everything still works token-free.

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

const TOKEN_KEY = 'mt5_dash_token'

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(t: string): void {
  try { localStorage.setItem(TOKEN_KEY, t) } catch { /* ignore */ }
}
export function clearToken(): void {
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
}

/** Prefix an API path with the configured backend base (or leave relative). */
export function api(path: string): string {
  return API_BASE + path
}

/**
 * fetch() wrapper that attaches the bearer token and, on a 401, clears the
 * token and signals the AuthGate to show the login screen again.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(api(path), { ...init, headers })
  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('mt5-dash-unauthorized'))
  }
  return res
}

/** Absolute WebSocket URL for the given path (token added as query param). */
export function wsUrl(path = '/ws'): string {
  let base: string

  const explicit = (import.meta.env.VITE_WS_BASE ?? '').replace(/\/+$/, '')
  if (explicit) {
    base = explicit + path
  } else if (API_BASE) {
    const u = new URL(API_BASE)
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:'
    base = `${proto}//${u.host}${path}`
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    base = `${proto}//${window.location.host}${path}`
  }

  const token = getToken()
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}
