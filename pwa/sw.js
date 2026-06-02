const CACHE = 'agentphone-shell-v21-rgba-fast';
const SHELL = ['/', '/android', '/android/styles.css', '/android/app.js', '/android/manifest.webmanifest', '/android/icon.svg'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL).catch(() => undefined)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  // Aggressively clear ALL old caches
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k.startsWith('agentphone-shell-') && k !== CACHE)
        .map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.pathname.includes('/api/')) return;
  // Network-first, fallback to cache
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Update cache with fresh response
        const clone = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request).then(resp => resp || caches.match('/android')))
  );
});
