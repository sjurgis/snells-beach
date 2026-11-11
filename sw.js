/* Kill switch for the old sjurgis.github.io/snells-beach address.
   The site now lives at https://beach.metacursion.com/. This worker replaces any old one,
   clears its caches, unregisters itself and sends open pages to the new address. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    try { for (const k of await caches.keys()) await caches.delete(k); } catch (_) {}
    try { await self.registration.unregister(); } catch (_) {}
    try {
      for (const c of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {
        const u = new URL(c.url);
        const path = u.pathname.replace(/^\/snells-beach(\/|$)/, "/");
        c.navigate("https://beach.metacursion.com" + path + u.search + u.hash).catch(() => {});
      }
    } catch (_) {}
  })());
});
/* No fetch handler: the browser loads everything itself. */
