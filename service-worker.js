const CACHE_NAME = "ris-static-v1.0.0";
const STATIC_ASSETS = ["/", "/offline.html", "/manifest.webmanifest", "/assets/app.css", "/assets/app.js", "/assets/ris-logo.png"];
self.addEventListener("install", (event) => { event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))); self.skipWaiting(); });
self.addEventListener("activate", (event) => { event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith("ris-static-") && key !== CACHE_NAME).map((key) => caches.delete(key))))); self.clients.claim(); });
self.addEventListener("fetch", (event) => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  // API, authentication, billing and customer data are deliberately never cached.
  if (url.pathname.startsWith("/api/")) return;
  if (request.mode === "navigate") { event.respondWith(fetch(request).catch(async () => (await caches.match("/offline.html")) || Response.error())); return; }
  if (["/assets/app.css", "/assets/app.js", "/assets/ris-logo.png", "/manifest.webmanifest"].includes(url.pathname)) {
    event.respondWith(caches.match(request).then((cached) => {
      const fresh = fetch(request).then((response) => { if (response.ok) { const copy = response.clone(); caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)); } return response; });
      return cached || fresh;
    }));
  }
});
