#!/usr/bin/env node
// Scans the built frontend (what actually gets served) for things that must never be in it: a database connection
// string or a Supabase secret key. Prints file names and the pattern only — never the matching text.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const STATIC_DIR = process.argv[2] ?? resolve(dirname(fileURLToPath(import.meta.url)), "../../catch/api/static");
const PATTERNS = [
  ["a database connection string", /postgres(ql)?(\+\w+)?:\/\//i],
  ["a Supabase secret key (sb_secret_)", /sb_secret_/],
  ["a service_role key", /service_role/],
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else yield p;
  }
}

let files = 0;
const hits = [];
for (const file of walk(STATIC_DIR)) {
  if (!/\.(js|mjs|css|html|json|map|webmanifest|txt)$/.test(file)) continue;
  files++;
  const text = readFileSync(file, "utf-8");
  for (const [label, re] of PATTERNS) if (re.test(text)) hits.push(`${file.slice(STATIC_DIR.length + 1)}: ${label}`);
}
if (files === 0) {
  console.error(`check-build-secrets: no files under ${STATIC_DIR} — did the build run?`);
  process.exit(1);
}
if (hits.length) {
  console.error("check-build-secrets: STOP — the build contains secrets:\n  " + hits.join("\n  "));
  process.exit(1);
}
console.log(`check-build-secrets: ${files} files clean`);
