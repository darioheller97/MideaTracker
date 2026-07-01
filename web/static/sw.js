// Service worker: offline caching + Web Push notifications.
const CACHE = "midea-v1";
const ASSETS = [
  "/static/app.js", "/static/style.css",
  "/static/icon-192.png", "/static/icon-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network-first with cache fallback: online users always get fresh content (so the
// "new version" reload works and results stay current); offline users get the last
// cached page/assets/results.
self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  event.respondWith(
    fetch(req)
      .then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});

self.addEventListener("push", event => {
  let data = { title: "Midea Tracker", body: "", url: "/" };
  try { data = Object.assign(data, event.data.json()); }
  catch (_) { if (event.data) data.body = event.data.text(); }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      data: { url: data.url || "/" },
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      tag: "midea-deal",
    })
  );
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window" }).then(list => {
      for (const c of list) { if (c.url.includes(url) && "focus" in c) return c.focus(); }
      return clients.openWindow(url);
    })
  );
});
