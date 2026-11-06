#!/usr/bin/env node
// CI's automated version of the manual "built, read the output, eyeballed the KB" check every
// prior session in PLAN.md did by hand. Only measures what a fresh page load actually pays for
// up front — the eager entry script plus whatever it <link rel="modulepreload">s — matching
// PLAN.md's own "153.9 KB + 16.2 KB modulepreload" accounting. Lazy route chunks (React.lazy)
// are deliberately excluded: that's the whole point of splitting them out, and counting them
// here would defeat the budget's purpose.
import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BUDGET_BYTES = 250 * 1024;
const STATIC_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../catch/api/static");

const html = readFileSync(join(STATIC_DIR, "index.html"), "utf-8");
const srcs = new Set();
for (const m of html.matchAll(/<script[^>]+type="module"[^>]+src="([^"]+)"/g)) srcs.add(m[1]);
for (const m of html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g)) srcs.add(m[1]);

if (srcs.size === 0) {
  console.error("check-bundle-size: found no <script type=module>/modulepreload tags in index.html — did the build run?");
  process.exit(1);
}

let total = 0;
const rows = [];
for (const src of srcs) {
  const path = join(STATIC_DIR, src.replace(/^\//, ""));
  const gz = gzipSync(readFileSync(path)).length;
  total += gz;
  rows.push([src, gz]);
}

rows.sort((a, b) => b[1] - a[1]);
for (const [src, gz] of rows) console.log(`  ${(gz / 1024).toFixed(1).padStart(7)} KB gzip  ${src}`);
console.log(`Initial JS: ${(total / 1024).toFixed(1)} KB gzip (budget ${(BUDGET_BYTES / 1024).toFixed(0)} KB)`);

if (total > BUDGET_BYTES) {
  console.error(`check-bundle-size: over budget by ${((total - BUDGET_BYTES) / 1024).toFixed(1)} KB`);
  process.exit(1);
}
