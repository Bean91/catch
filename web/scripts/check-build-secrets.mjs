#!/usr/bin/env node
// Scans the built frontend (what actually gets served) for things that must never be in it: a database connection
// string or a Supabase secret key. Prints file names and the pattern only — never the matching text.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// One or more directories (default: the served web build). Session 30: the native apps pass dist-native plus the copies synced into the
// iOS/Android projects, and the built APK/IPA contents are scanned through the same patterns (docs/mobile/security.md).
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DIRS = process.argv.length > 2 ? process.argv.slice(2).map((d) => resolve(process.cwd(), d)) : [resolve(ROOT, "../catch/api/static")];
const PATTERNS = [
  ["a database connection string", /postgres(ql)?(\+\w+)?:\/\//i],
  ["a Supabase secret key (sb_secret_)", /sb_secret_/],
  ["a service_role key", /service_role/],
  ["a private key", /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/],
  ["a Firebase/Google service-account key", /"type"\s*:\s*"service_account"/],
  ["an APNs/FCM server credential name", /\b(?:APNS_KEY_P8|FCM_SERVICE_ACCOUNT_JSON|SUPABASE_SECRET_KEY|DATABASE_ADMIN_URL)\b/],
];
const FORBIDDEN_FILES = /\.(p8|p12|pem|keystore|jks|mobileprovision)$|(^|\/)google-services\.json$|(^|\/)\.env/i;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else yield p;
  }
}

let files = 0;
const hits = [];
for (const dir of DIRS) {
  if (!existsSync(dir)) {
    console.error(`check-build-secrets: ${dir} does not exist — did the build/sync run?`);
    process.exit(1);
  }
  for (const file of walk(dir)) {
    const rel = file.slice(dir.length + 1);
    if (FORBIDDEN_FILES.test(rel)) hits.push(`${rel}: a credential/signing file name`);
    if (!/\.(js|mjs|css|html|json|map|webmanifest|txt|xml|plist|properties)$/.test(file)) continue;
    files++;
    const text = readFileSync(file, "utf-8");
    for (const [label, re] of PATTERNS) if (re.test(text)) hits.push(`${rel}: ${label}`);
  }
}
if (files === 0) {
  console.error("check-build-secrets: no files scanned — did the build run?");
  process.exit(1);
}
if (hits.length) {
  console.error("check-build-secrets: STOP — the build contains secrets:\n  " + hits.join("\n  "));
  process.exit(1);
}
console.log(`check-build-secrets: ${files} files clean across ${DIRS.length} director${DIRS.length === 1 ? "y" : "ies"}`);
