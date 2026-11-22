const CACHE_PREFIX = "codebrick-cards-";
const SHELL_CACHE = `${CACHE_PREFIX}shell-v4`;
const DATA_CACHE = `${CACHE_PREFIX}data-v2`;
const SHELL_FILES = ["./", "./index.html", "./styles.css", "./app.js"];
const CARD_DATA_PATH = "/data/cards/cards.json";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((key) => key.startsWith(CACHE_PREFIX) && ![SHELL_CACHE, DATA_CACHE].includes(key))
        .map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.endsWith(CARD_DATA_PATH)) {
    event.respondWith(networkFirst(request));
    return;
  }

  if (url.pathname.startsWith(new URL(".", self.registration.scope).pathname)) {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request)) || Response.error();
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    if (request.mode === "navigate") {
      return (await caches.match("./index.html")) || Response.error();
    }
    return Response.error();
  }
}

