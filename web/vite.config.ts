/// <reference types="vitest/config" />
import { execSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// Computed once per build, shared by the service worker's own VERSION (below), the
// `__BUILD_ID__` the client bundle embeds (the update-check poll in useServiceWorkerUpdate.ts
// compares against this), and version.json (what that poll actually fetches). `CATCH_BUILD_ID`
// lets the Playwright update-flow test (tests/update/) force two distinct, deterministic IDs
// across two builds instead of racing Date.now() across back-to-back builds.
const BUILD_ID = process.env.CATCH_BUILD_ID ?? Date.now().toString(36)

// A human-readable label for Settings — the build id alone doesn't tell the user which commit
// shipped it. Best-effort: a fresh clone or a non-git deploy tree shouldn't fail the build.
function gitCommit(): string {
  try {
    const sha = execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
    const dirty = execSync('git status --porcelain', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim().length > 0
    return dirty ? `${sha}-dirty` : sha
  } catch {
    return 'unknown'
  }
}
const COMMIT = gitCommit()

// Hand-rolled service worker, not a Workbox/vite-plugin-pwa dependency — this app is small
// and self-hosted, and a few dozen lines of fetch-handler logic isn't worth a new build
// dependency. The one thing a static public/sw.js *can't* do on its own is know Vite's
// hashed output filenames, so this plugin writes them in at build time via writeBundle.
function serviceWorkerPlugin(): Plugin {
  return {
    name: 'catch-service-worker',
    writeBundle(options, bundle) {
      const outDir = options.dir ?? 'dist'
      const precache = ['/', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png']
      for (const file of Object.values(bundle)) {
        if (file.fileName.endsWith('.js') || file.fileName.endsWith('.css')) {
          precache.push(`/${file.fileName}`)
        }
      }
      // Fetched by useServiceWorkerUpdate.ts's poll, cache-busted with `cache: 'no-store'` on
      // the client side and Cache-Control: no-cache on the server (catch/main.py), the same way
      // sw.js/index.html already are. Detecting a new build this way — a plain version compare
      // on an interval/visibilitychange, independent of the service worker's own install/waiting
      // lifecycle — sidesteps a real class of WebKit flakiness around *when* (or whether)
      // `updatefound`/`controllerchange` actually fire on an installed iOS PWA; a session 9 bug
      // report ("my iPhone PWA keeps running an old build") despite seemingly-correct lifecycle
      // code pointed straight at not trusting that event timing as the only signal.
      writeFileSync(`${outDir}/version.json`, JSON.stringify({ build: BUILD_ID, commit: COMMIT }))

      const sw = `// Generated at build time by vite.config.ts's serviceWorkerPlugin — do not edit the
// hashed filenames below by hand, they're regenerated on every build.
const VERSION = ${JSON.stringify(BUILD_ID)};
const SHELL_CACHE = \`catch-shell-\${VERSION}\`;
const API_CACHE = \`catch-api-\${VERSION}\`;
const PRECACHE_URLS = ${JSON.stringify(precache)};
// Exempt from every caching path below (section 2 of fetch's branches) — these two are the
// client's actual freshness signals (online-ness, build version). Serving either from a
// stale cache, even as an offline fallback, would make both silently lie.
const NEVER_CACHE = ['/api/health', '/version.json'];

self.addEventListener('install', (event) => {
  // Reload-on-tap is now driven by version.json (above), not by "is a worker waiting" — so
  // there's no more reason to hold a new worker back: skipWaiting immediately, same as
  // clients.claim() on activate below.
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE && k !== API_CACHE).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (NEVER_CACHE.includes(url.pathname)) {
    event.respondWith(fetch(req));
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    // Network-first: today's real numbers beat yesterday's cache whenever we're online. The
    // cache write is wrapped in waitUntil — without it, the browser is free to kill this SW
    // once respondWith's promise resolves, racing the detached cache.put and often losing.
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            event.waitUntil(caches.open(API_CACHE).then((cache) => cache.put(req, copy)));
          }
          return res;
        })
        .catch(() => caches.match(req)),
    );
    return;
  }

  if (req.mode === 'navigate') {
    // Also keeps the precached '/' fallback itself fresh on every successful online
    // navigation — without this it stays frozen at whatever HTML existed the moment this SW
    // was first installed, forever, even though every online load took the network-first path.
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.put('/', copy)));
          }
          return res;
        })
        .catch(() => caches.match('/')),
    );
    return;
  }

  if (url.pathname.startsWith('/assets/')) {
    // Cache-first only for hashed, content-addressed filenames — immutable per build, safe to
    // serve from cache indefinitely without ever re-checking the network.
    event.respondWith(caches.match(req).then((cached) => cached || fetch(req)));
    return;
  }

  // Everything else same-origin (manifest, icons, favicons) is NOT content-hashed, so unlike
  // /assets/* it can change without a new filename — network-first, cache as a fallback only.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.put(req, copy)));
        }
        return res;
      })
      .catch(() => caches.match(req)),
  );
});
`
      writeFileSync(`${outDir}/sw.js`, sw)
    },
  }
}

// Port comes from the backend's own .env (CATCH_PORT) per CLAUDE.md — read directly rather
// than duplicating it into a web/.env the Pi deploy could drift out of sync with.
function catchPort(): number {
  try {
    const envPath = fileURLToPath(new URL('../.env', import.meta.url))
    const match = readFileSync(envPath, 'utf-8').match(/^CATCH_PORT=(\d+)/m)
    if (match) return Number(match[1])
  } catch {
    // .env is gitignored and may not exist yet (fresh clone) — fall back below.
  }
  return 8000
}

export default defineConfig({
  plugins: [react(), tailwindcss(), serviceWorkerPlugin()],
  define: {
    __BUILD_ID__: JSON.stringify(BUILD_ID),
    __COMMIT__: JSON.stringify(COMMIT),
  },
  build: {
    outDir: '../catch/api/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': `http://localhost:${catchPort()}`,
      '/auth': `http://localhost:${catchPort()}`,
    },
  },
  // Scoped to src/ — vitest's default file-matching would otherwise also pick up
  // tests/touch/*.spec.ts, which are Playwright specs (playwright.config.ts's own testDir),
  // not vitest ones; running them under the wrong runner fails immediately on
  // `test.beforeEach`'s signature, which the two packages don't share.
  test: {
    include: ['src/**/*.test.ts'],
  },
})
