# Release checklist (public launch)

Each item has a status, its evidence (what was run, when, and the result) and an owner. **A release tag is created only when every
"Required" row is PASS.** As of 2026-11-20 (session 31) they are not, so **no tag was created**. The current tag `v1.0`
(2026-11-01) predates the public deployment and is not a public-launch release.

Statuses:
- **PASS:** run in session 31, unless another date is given.
- **FAIL:** run or inspected, and not met.
- **NOT VERIFIED:** not run (no account, device, access or authorisation).
- **OWNER:** only the owner can do or confirm it.

Blocker IDs (B-n) refer to [launch-audit.md](launch-audit.md#blockers).

## 1. Code and tests (Required)

| Item | Status | Evidence |
|---|---|---|
| Backend suite (SQLite) | PASS | see launch-audit.md §Evidence (final run on the branch head) |
| Whole backend suite on PostgreSQL | PASS | same |
| `tests/pg` (real GoTrue + RLS + Storage, separate identities) on the local Supabase stack | PASS | same |
| Frontend typecheck, lint, vitest, build, bundle budget (230 KB / 250 KB gzip initial JS), build-secret scan | PASS | same |
| Playwright touch (mobile + WebKit + desktop, against the production preview) | PASS | same |
| Playwright public, update, gym-offline | PASS | `test:public` 18, `test:update` 4, `test:gym` 1 |
| Playwright `test:live` (real public build + local GoTrue + mailpit) | NOT VERIFIED | not run in session 31: it needs the local stack reconfigured (confirmations, mailpit, redirect URLs); last run session 24 |
| Native: `native:sync` (production), `check:native-secrets`, Android `assembleProdDebug` + `assembleDevDebug`, iOS simulator build | PASS | 343 files clean; `BUILD SUCCESSFUL`; `** BUILD SUCCEEDED **` |
| Native Android emulator e2e (`web/tests/native/android-e2e.mjs`) | NOT VERIFIED | not run in session 31 (passed in session 30) |
| MCP stdio end to end | PASS | `scripts/mcp_stdio_check.py` 7/7 |
| Secret scan (gitleaks v8.30.1, full history) | PASS | "no leaks found", 150 commits |
| Dependency audit (pip-audit on the locked set, npm audit `--omit=dev --audit-level=high`) | PASS | "No known vulnerabilities found"; "found 0 vulnerabilities" |
| No open Critical/High code finding | **FAIL** | L-09 per-user time zone (High) is open: B-2 |

## 2. FastAPI Cloud production configuration (Required)

| Item | Status | Owner / next action |
|---|---|---|
| This branch deployed, **after** `catch db upgrade` to 0010 | **FAIL**: production runs session-30 code on a 0008 DB | Owner: B-1 |
| `/internal/db-check`: `bypass_rls` false, ssl true, probes pass, `schema_missing_tables` empty | NOT VERIFIED (tick secret not provided) | Owner: run after B-1 |
| `/internal/config-check`: every required secret loaded; Garmin BYOK set explicitly | NOT VERIFIED | Owner (B-6 decides the Garmin value) |
| Secrets stored as encrypted secrets, values whitespace-free | OWNER | Owner: re-enter `WITHINGS_CLIENT_SECRET` if the deploy doesn't fix B-9 |
| Production smoke `scripts/smoke_public.py` | **FAIL** (28 passed, 3 failed: account deletion 500, 2026-11-20 15:19 UTC) | Re-run after B-1; must be all PASS |
| Rollback procedure rehearsed | NOT VERIFIED (not authorised) | Owner: redeploy the previous commit once, on purpose, before launch |
| Scheduled ticks running (`cron.job_run_details`) | PASS in session 29; NOT VERIFIED in session 31 | Owner |

## 3. Supabase production configuration (Required)

| Item | Status | Owner / next action |
|---|---|---|
| Migrations at head (0010) | **FAIL** (0008) | B-1 |
| Plan with backups (Pro+) or scheduled `pg_dump` of all three schemas; restore drill run against a production dump | **FAIL**: Free plan, no backup ever taken | B-3 |
| Auth settings: confirm email, password policy, secure password change, MFA (TOTP) + moderators enrolled, rate limits + CAPTCHA, exact redirect URLs | OWNER / NOT VERIFIED (F-17) | B-10 |
| Custom SMTP configured; sign-up confirmation and password recovery emails received | **FAIL / NOT VERIFIED** | B-5 |
| `catch`, `catch_private`, `catch_club` not in exposed schemas | OWNER | Owner: confirm in the dashboard |
| `catch_api` password rotated after F-38, connection logs reviewed for the exposure window | OWNER (rotation reported, not independently verified) | B-11 |

## 4. Domain, HTTPS, email

| Item | Status |
|---|---|
| Custom domain, valid TLS, http→https, HSTS, CSP | PASS (curl, 2026-11-20; certificate valid to 2027-02-13) |
| Transactional email (SMTP), SPF/DKIM on the sending domain | **FAIL / NOT VERIFIED**: B-5 |
| Contact address for privacy requests published | **FAIL**: legal pages say "[to be filled in]" (B-4) |

## 5. Backups and monitoring (Required)

| Item | Status |
|---|---|
| Automated backups + a tested restore | **FAIL**: B-3. The local drill passes 15/15 and the runbook documents the auth.users trigger step |
| Uptime alert on `/api/health` | **PASS** once pushed: `.github/workflows/uptime.yml`, every 15 min, a failed run e-mails the owner (B-8) |
| Alert on failing ticks (`cron.job_run_details`) | **FAIL**: none (B-8) |
| Error visibility (platform logs) | OWNER: retention unknown (F-21) |

## 6. Legal and policy (Required)

| Item | Status |
|---|---|
| Privacy policy, terms, deletion policy, AI-sharing, community guidelines, not-medical-advice, provider disclosures reviewed by counsel | **FAIL**: drafts only, never reviewed (F-18, B-4) |
| Placeholders removed from the shipped legal pages | **FAIL**: "Contact: [to be filled in]" and counsel notes render publicly at `/legal/*` (L-25) |
| Minimum-age / guardian rules confirmed by counsel (`MIN_PUBLISH_AGE=13`, guardian under 16) | OWNER |
| Health-data processing basis (GDPR art. 9 etc.) for the regions served | OWNER |
| Residual risk F-02 (MCP/REST confirmation is client-mediated) accepted in writing | **PASS**: accepted by the owner 2026-11-20 (F-02 row in `docs/security-findings.md`) |

## 7. Provider approvals and live verification (Required for each provider offered)

| Provider | Status | Owner / next action |
|---|---|---|
| Garmin | **FAIL**: no Garmin developer-program approval. The public build offers the user's own Personal API key, which Garmin says is "not intended for commercial applications serving multiple end users". | B-6: decide (switch off with `CATCH_GARMIN_BYOK_ENABLED=0`, or obtain approval / legal sign-off) |
| Withings | **FAIL in production**: `Invalid HMAC signature` since 2026-11-20 00:37 UTC. Fix committed (`bf3848e`), not deployed. OAuth + refresh never verified live for a second user. | B-9, B-13 |
| Concept2 | Owner's personal-token connection syncs in production (`last_success` 2026-11-20 15:07 UTC, via MCP). OAuth flow never run live. | B-13 |
| Whoop | NOT VERIFIED: never connected live; app limited to a small member tier until Whoop approves more | B-13 |
| Disconnect / reconnect / credential deletion | PASS (mocked): `tests/test_connections.py`, `tests/tenancy/test_provider_connections.py`; NOT VERIFIED live | B-13 |

## 8. AI providers (Required for each offered)

| Item | Status |
|---|---|
| Anthropic, OpenAI and Gemini BYOK: chat, tool calls, invalid key, revoked key, key replacement keeping history | PASS (synthetic fixtures, full suite); **NOT VERIFIED live** (no keys), B-14 |
| Ollama | Disabled on public by design (startup refuses `CATCH_OLLAMA_ENABLED=1`); personal only, tested with mocks |
| MCP: Claude remote (OAuth) | PASS (owner's claude.ai connector, 2026-11-20: read + preview-only write) |
| MCP: ChatGPT, Gemini API, Gemini CLI | NOT VERIFIED (no accounts), B-15. Setup is documented in mcp-client-setup.md |

## 9. Mobile apps and stores (Required before store submission; not required for a web-only launch)

| Item | Status |
|---|---|
| Apple Developer Program, Google Play Console, Firebase project | OWNER: not in place per session 30. The iOS project now has a development team set (`69e2d34`) |
| Android release signing config | **FAIL**: none (session 30) |
| APNs / FCM delivery, universal / App Links, HealthKit / Health Connect reads, iOS runtime sign-in | NOT VERIFIED (no devices; docs/mobile/test-report.md) |
| Minimum-version / forced-update mechanism | **FAIL**: none (session 30) |
| Store listings, privacy labels, screenshots | drafts (docs/mobile/) |

## 10. Versioning and tag

- Version numbers today:
  - `pyproject.toml` 0.1.0.
  - `web/package.json` 0.0.0.
  - iOS `MARKETING_VERSION` 1.0, build 1.
  - The only tag is `v1.0`.
- When every Required row is PASS:
  1. Set `pyproject.toml`'s version (proposed `1.1.0`, the first public release).
  2. Add a dated `CHANGELOG.md` entry.
  3. Commit.
  4. Tag: `git tag -a v1.1.0 -m "Public launch"`.
  5. Push the tag.
  6. Deploy that exact commit (migrate first, fastapi-cloud-deployment.md §2).
- **Not done in session 31**, because the checklist does not pass.

## 11. Rollback procedure (summary; full steps in operations-runbook.md §6–7)

1. Before release: take a `pg_dump` of all three schemas and note the commit currently live.
2. Code rollback: check out the previous commit, rebuild the frontend, `fastapi deploy`.
3. Schema rollback, only if the release migrated and the old code can't run on the new schema:
   `catch db upgrade <previous revision>` from the dump-protected state. Downgrades are destructive (runbook §6).
4. Restore from the dump only for data loss. Re-create the auth.users triggers afterwards (runbook §7).
5. Run `scripts/smoke_public.py` and `/internal/db-check`.
