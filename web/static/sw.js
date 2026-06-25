// Service worker: receive Web Push and show a notification.
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
