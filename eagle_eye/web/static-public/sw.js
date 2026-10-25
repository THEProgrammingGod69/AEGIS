/* EAGLE EYE service worker: makes the hosted console an installable app that still opens without a network.
 *
 * - Pages and data (index.html, demo/...) are network-first: online, every request goes to the server exactly as
 *   before, so a new deploy shows at once; the cache is only the fallback when the network is down or very slow.
 * - Build files under assets/ are cache-first: their names carry a content hash, so a cached copy is never stale.
 * - Only same-origin GETs are touched. The cloud engine, uploads, streams and range requests pass straight through.
 *
 * To retire it, deploy a sw.js whose install handler calls self.registration.unregister().
 */
const VERSION = "ee-1";
const SHELL = `${VERSION}-shell`;
const ASSETS = `${VERSION}-assets`;
const MAX_ASSETS = 160;
const SLOW_MS = 4000;
const ROOT = new URL("./", self.registration.scope).href;
const PRECACHE = ["./", "./demo/index.json", "./favicon.svg", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png"];

const cacheable = (res) => res && res.ok && res.status === 200 && res.type === "basic" && !res.redirected;
const abs = (u) => new URL(u, self.registration.scope).href;
const isAsset = (url) => new URL(url).pathname.includes("/assets/");

async function put(name, key, res) {
  try {
    const c = await caches.open(name);
    await c.put(key, res);
    if (name === ASSETS) {
      const keys = await c.keys();
      await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_ASSETS)).map((k) => c.delete(k)));
    }
  } catch {
    /* quota or an uncacheable response: the network answer was already served */
  }
}

async function fetchInto(name, url) {
  try {
    const c = await caches.open(name);
    if (await c.match(url)) return;
    const res = await fetch(url, { cache: "no-cache" });
    if (cacheable(res)) await put(name, url, res);
  } catch {
    /* offline during install or warm-up: it is cached on its next successful load */
  }
}

self.addEventListener("install", (e) => {
  e.waitUntil(
    (async () => {
      await Promise.all(PRECACHE.map((u) => fetchInto(SHELL, abs(u))));
      // the build files the current index.html loads, so the very first visit already works offline
      try {
        const html = await (await (await caches.open(SHELL)).match(ROOT))?.text();
        const files = [...(html ?? "").matchAll(/(?:src|href)="(\.?\/?assets\/[^"]+)"/g)].map((m) => abs(m[1]));
        await Promise.all(files.map((u) => fetchInto(ASSETS, u)));
      } catch {
        /* nothing cached yet */
      }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n.startsWith("ee-") && !n.startsWith(`${VERSION}-`)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

/** Network first; the cached copy answers when the network fails, or after SLOW_MS when there is one. */
async function networkFirst(req, key) {
  const c = await caches.open(SHELL);
  const net = fetch(req).then((res) => {
    if (cacheable(res)) void put(SHELL, key, res.clone());
    return res;
  });
  net.catch(() => {});
  const cached = c.match(key);
  const slow = new Promise((r) => setTimeout(r, SLOW_MS)).then(() => cached);
  try {
    const first = await Promise.race([net, slow]);
    return first ?? (await net);
  } catch {
    return (await cached) ?? Response.error();
  }
}

async function cacheFirst(req) {
  const hit = await (await caches.open(ASSETS)).match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (cacheable(res)) void put(ASSETS, req, res.clone());
  return res;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || req.headers.has("range")) return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.endsWith("/sw.js")) return;
  if (req.mode === "navigate") e.respondWith(networkFirst(req, ROOT));
  else if (isAsset(req.url)) e.respondWith(cacheFirst(req));
  else e.respondWith(networkFirst(req, req));
});

/** Every recorded run's data (about 1 MB in all), so any page opens offline; their images arrive as they are viewed. */
async function warmRecorded() {
  try {
    const ix = await (await (await caches.open(SHELL)).match(abs("./demo/index.json")))?.json();
    for (const id of Object.keys((ix && ix.runs) || {}).slice(0, 200)) await fetchInto(SHELL, abs(`./demo/runs/${id}/payload.json`));
  } catch {
    /* no index cached yet: the runs are cached as they are opened */
  }
}

/* The page sends the files it has already loaded (lazy pages, images, recorded runs) once the worker is ready, so a
   first visit leaves everything it showed available offline; then the remaining run data follows in the background. */
self.addEventListener("message", (e) => {
  if (!e.data || e.data.type !== "warm" || !Array.isArray(e.data.urls)) return;
  const urls = e.data.urls
    .slice(0, 300)
    .map((u) => { try { return new URL(u, self.registration.scope); } catch { return null; } })
    .filter((u) => u && u.origin === self.location.origin && !u.pathname.endsWith("/sw.js"))
    .map((u) => u.href);
  e.waitUntil((async () => {
    for (const u of urls) await fetchInto(isAsset(u) ? ASSETS : SHELL, u);
    await warmRecorded();
  })());
});
