import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

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
  plugins: [react(), tailwindcss()],
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
})
