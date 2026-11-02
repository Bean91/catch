/// <reference types="vitest/config" />
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

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
      const version = Date.now().toString(36)
      const sw = `// Generated at build time by vite.config.ts's serviceWorkerPlugin — do not edit the
// hashed filenames below by hand, they're regenerated on every build.
const VERSION = ${JSON.stringify(version)};
const SHELL_CACHE = \`catch-shell-\${VERSION}\`;
const API_CACHE = 'catch-api-v1';
const PRECACHE_URLS = ${JSON.stringify(precache)};

self.addEventListener('install', (event) => {
  // No unconditional self.skipWaiting() here (session 8's original version had one) — a
  // waiting worker is exactly what main.tsx's update-detection flow needs to find via
  // registration.waiting and prompt the user about ("New version available — tap to reload").
  // Skipping straight to activation on install would mean there's never anything waiting to
  // detect, and a page already open would get its fetch handler swapped out from under it
  // mid-session with no warning.
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(PRECACHE_URLS)));
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Purges the old API_CACHE too, not just old shell caches — a new build's JS may expect
  // response shapes an old cached /api/* response doesn't have; losing one deploy's worth of
  // offline freshness is a better trade than a newer app crashing on stale cached JSON.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

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
    event.respondWith(fetch(req).catch(() => caches.match('/')));
    return;
  }

  event.respondWith(
    caches.match(req).then(
      (cached) =>
        cached ||
        fetch(req).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.put(req, copy)));
          }
          return res;
        }),
    ),
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
