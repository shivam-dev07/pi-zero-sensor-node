// Pi Zero Sensor Dashboard — Service Worker
// Cache version: v1
const CACHE = 'pizero-dashboard-v1';
const ASSETS = [
  '/',
  '/manifest.json',
  '/api/readings'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(clients.claim());
});

self.addEventListener('fetch', (e) => {
  // Network-first for API, cache-first for everything else
  if (e.request.url.includes('/api/')) {
    e.respondWith(networkFirst(e.request));
  } else {
    e.respondWith(cacheFirst(e.request));
  }
});

async function networkFirst(req) {
  try {
    const resp = await fetch(req);
    const cache = await caches.open(CACHE);
    cache.put(req, resp.clone());
    return resp;
  } catch {
    return caches.match(req);
  }
}

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const resp = await fetch(req);
    const cache = await caches.open(CACHE);
    cache.put(req, resp.clone());
    return resp;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}
