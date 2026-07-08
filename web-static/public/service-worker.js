// Minimal offline cache for the static shell + the two data assets the assistant needs
// (index.json, config.json). Cache-first for everything this page owns, network for
// everything else (there is nothing else this page ever fetches). Bump CACHE_NAME when
// the shipped bundle changes so clients pick up the new index/config instead of a stale
// cached copy.
const CACHE_NAME = "sprout-static-v1";
const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./styles.css",
  "./manifest.webmanifest",
  "./assets/index.js",
  "./assets/answer.js",
  "./assets/config.js",
  "./assets/confidence.js",
  "./assets/generator.js",
  "./assets/guards.js",
  "./assets/hashEmbedding.js",
  "./assets/lang.js",
  "./assets/lexical.js",
  "./assets/models.js",
  "./assets/retrieve.js",
  "./assets/sha256.js",
  "./assets/store.js",
  "./assets/text.js",
  "./data/index.json",
  "./data/config.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      });
    }),
  );
});
