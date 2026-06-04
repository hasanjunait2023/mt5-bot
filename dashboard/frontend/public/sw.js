/* MT5 Terminal service worker — makes the dashboard installable and launchable
   offline, WITHOUT serving stale live data. Strategy:
     - hashed build assets (/assets/*) : cache-first (immutable, content-hashed)
     - navigations                     : network-first, fall back to cached shell
     - everything dynamic (/api, /ws)  : never touched (default network) */
const SHELL = 'mt5-shell-v1'
const ASSETS = 'mt5-assets-v1'
const SHELL_URLS = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_URLS)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL && k !== ASSETS).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  // Live data must always hit the network — never cache it.
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')) return

  // App shell navigation: network-first so a fresh build wins, offline falls back.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          caches.open(SHELL).then((c) => c.put('/', res.clone())).catch(() => {})
          return res
        })
        .catch(() => caches.match('/', { ignoreSearch: true }).then((r) => r || caches.match(req)))
    )
    return
  }

  // Immutable hashed assets: cache-first.
  if (url.pathname.startsWith('/assets/')) {
    e.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            const copy = res.clone()
            caches.open(ASSETS).then((c) => c.put(req, copy)).catch(() => {})
            return res
          })
      )
    )
  }
})
