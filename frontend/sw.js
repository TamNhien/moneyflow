/* MoneyFlow v1.0.28: public UI shell only; NEVER cache authenticated API data. */
'use strict';
const CACHE_NAME = 'moneyflow-shell-v1.0.28';
const CACHE_PREFIX = 'moneyflow-shell-';
const ASSETS = [
  '/offline.html', '/logo.svg', '/favicon.svg', '/apple-touch-icon.png',
  '/icon-192.png', '/icon-512.png', '/icon-512-maskable.png', '/manifest.webmanifest',
  '/main.css?v=1.0.28', '/app.js?v=1.0.28', '/pwa.js?v=1.0.28'
];
const PUBLIC_ASSET_URLS = new Set(ASSETS.map(path => new URL(path, self.location.origin).href));
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([
    caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith(CACHE_PREFIX) && k !== CACHE_NAME).map(k => caches.delete(k)))),
    self.clients.claim()
  ]));
});
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Always pass login, password recovery, and financial APIs to the network.
  if (url.pathname.startsWith('/api/') || url.pathname === '/reset') return;
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(async () =>
      (await caches.open(CACHE_NAME)).match('/offline.html') ||
      new Response('MoneyFlow: kết nối không khả dụng', {status:503})
    ));
    return;
  }
  if (!PUBLIC_ASSET_URLS.has(url.href)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(req);
    if (cached) return cached;
    // Cache only explicitly allowed public static files; never redirects or opaque responses.
    const fresh = await fetch(req);
    if (fresh.ok && fresh.type === 'basic' && !fresh.redirected) await cache.put(req, fresh.clone());
    return fresh;
  })());
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async all => {
    const existing = all.find(client => new URL(client.url).origin === self.location.origin);
    if (existing) return existing.focus();
    return self.clients.openWindow('/');
  }));
});
