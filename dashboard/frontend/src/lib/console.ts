// Claude Code Console — its OWN token (separate from the dashboard token), so a
// leaked dashboard session can't reach code execution. Mirrors lib/api.ts base
// resolution but with the console token + the /api/console/ws endpoint.

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')
const CK = 'mt5_console_token'

export function getConsoleToken(): string | null {
  try { return localStorage.getItem(CK) } catch { return null }
}
export function setConsoleToken(t: string): void {
  try { localStorage.setItem(CK, t) } catch { /* ignore */ }
}
export function clearConsoleToken(): void {
  try { localStorage.removeItem(CK) } catch { /* ignore */ }
}

export async function consoleFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const t = getConsoleToken()
  const headers = new Headers(init.headers)
  if (t) headers.set('Authorization', `Bearer ${t}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  return fetch(API_BASE + path, { ...init, headers })
}

export function consoleWsUrl(): string {
  const path = '/api/console/ws'
  let base: string
  const explicit = (import.meta.env.VITE_WS_BASE ?? '').replace(/\/+$/, '')
  if (explicit) {
    base = explicit + path
  } else if (API_BASE) {
    const u = new URL(API_BASE)
    base = `${u.protocol === 'https:' ? 'wss:' : 'ws:'}//${u.host}${path}`
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    base = `${proto}//${window.location.host}${path}`
  }
  const t = getConsoleToken()
  return t ? `${base}?token=${encodeURIComponent(t)}` : base
}
