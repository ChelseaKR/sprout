// Offline cache for the reference shell and its two corpus assets. Requests outside
// this explicit list—including MkDocs routes on the same domain—are not intercepted.
// Listed assets are network-first so an online reload sees a new corpus immediately,
// with the installed cache used only as the offline fallback.
const CACHE_NAME = "sprout-reference-v2";
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
const SHELL_URLS = new Set(SHELL.map((path) => new URL(path, self.registration.scope).href));

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
  if (event.request.method !== "GET" || !SHELL_URLS.has(event.request.url)) {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(async () => (await caches.match(event.request)) ?? Response.error()),
  );
});
