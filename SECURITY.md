# Security

Catch stores health and training data, so security reports are welcome and taken seriously.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private vulnerability reporting for this repository
(Security → Report a vulnerability), or contact the maintainer directly through the address on their GitHub profile.

Include what you found, how to reproduce it, and what an attacker could do with it. Please don't access, change or delete data that
isn't yours, and don't run denial-of-service or social-engineering tests.

You can expect an acknowledgement within a few days. There is no bounty programme; this is a small self-hosted project.

## Scope

In scope: this repository's code (the API, the web app, the MCP server), the Supabase schema/RLS/migrations, and the deployment
documentation. Out of scope: third-party services Catch connects to (Garmin, Withings, Whoop, Concept2, AI providers, Supabase,
FastAPI Cloud) — report those to their vendors.

## What the project does about it

* `docs/security.md` — how secrets are stored, what is logged, the threat model and known gaps.
* `docs/security-findings.md` — the findings register from the session-28 review, with severity and remediation status.
* CI runs secret scanning over the full git history and dependency audits on every push and weekly
  (`.github/workflows/security.yml`).
