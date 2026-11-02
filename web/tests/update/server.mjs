// A minimal stand-in for catch.main's static/SPA serving + /api/health, just enough to drive
// the service-worker/update-detection Playwright tests without booting the real FastAPI app —
// catch.main's lifespan starts APScheduler, which means live Garmin/Withings/Concept2 sync
// attempts against the real .env (CLAUDE.md: "no live network calls in the suite"). This has
// no DB, no auth, no scheduler — just enough HTTP surface for the client code under test.
import { createReadStream, existsSync, statSync } from "node:fs";
import http from "node:http";
import path from "node:path";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

const NO_CACHE_NAMES = new Set(["sw.js", "index.html", "version.json"]);

// `getRoot()` rather than a fixed path — the whole point is simulating a deploy by swapping
// which build's dist directory is served, without restarting the server (a real restart would
// drop any open connections/SW registration state the test is relying on staying put).
export function startServer(getRoot, port) {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");

    if (url.pathname === "/api/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
      return;
    }

    const root = getRoot();
    const safe = path.normalize(path.join(root, decodeURIComponent(url.pathname))).startsWith(path.normalize(root));
    let filePath = safe ? path.join(root, decodeURIComponent(url.pathname)) : null;

    if (!filePath || !existsSync(filePath) || !statSync(filePath).isFile()) {
      filePath = path.join(root, "index.html"); // SPA fallback, same as catch/main.py's spa()
    }

    const ext = path.extname(filePath);
    const headers = { "Content-Type": MIME[ext] ?? "application/octet-stream" };
    if (NO_CACHE_NAMES.has(path.basename(filePath))) headers["Cache-Control"] = "no-cache";
    res.writeHead(200, headers);
    createReadStream(filePath).pipe(res);
  });
  return new Promise((resolve) => server.listen(port, () => resolve(server)));
}
