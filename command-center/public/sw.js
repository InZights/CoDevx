// AI Dev Team Command Center — Service Worker
// Provides offline shell support for Android PWA

const CACHE = 'cmd-center-v1'
const STATIC_ASSETS = ['/']

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(STATIC_ASSETS))
  )
  self.skipWaiting()
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', event => {
  // Only cache GET requests for same-origin navigation (not API/WS)
  const url = new URL(event.request.url)
  const isApiOrWs = url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')

  if (event.request.method !== 'GET' || isApiOrWs) return

  event.respondWith(
    fetch(event.request)
      .then(res => {
        if (res.status === 200) {
          const clone = res.clone()
          caches.open(CACHE).then(cache => cache.put(event.request, clone))
        }
        return res
      })
      .catch(() => caches.match(event.request).then(r => r ?? caches.match('/')))
  )
})
