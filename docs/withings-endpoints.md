# Withings public API — what we actually confirmed

Source: developer.withings.com guide pages, scraped directly (the site is a Docusaurus SPA;
WebFetch's HTML-to-markdown conversion loses client-rendered content, so pages were fetched
raw with `curl` and read as text where WebFetch came back empty). Pulled 2026-10-31. The
`/api-reference` OpenAPI spec itself is loaded by client JS from a path we could not locate
in the time budget for this session — the guide pages below were enough to implement against,
but if anything here conflicts with a live response, the response wins.

## Important: current API requires request signing, not plain client_secret-in-body

Older third-party write-ups of the Withings OAuth2 flow pass `client_secret` directly in the
token request body. **That is not what the current docs show.** The documented flow (as of
this scrape) signs requests with HMAC-SHA256 instead, and `client_secret` never leaves your
server as a value:

1. **Get a nonce** — `POST https://wbsapi.withings.net/v2/signature`
   - body: `action=getnonce`, `client_id`, `timestamp=<unix seconds>`
   - `signature = HMAC_SHA256(client_secret, "getnonce,<client_id>,<timestamp>").hexdigest()`
2. **Exchange code / refresh** — `POST https://wbsapi.withings.net/v2/oauth2`
   - body: `action=requesttoken`, `grant_type=authorization_code|refresh_token`, `client_id`,
     `redirect_uri`+`code` (for the code grant) or `refresh_token` (for refresh), `nonce` (from
     step 1)
   - `signature = HMAC_SHA256(client_secret, "<action>,<client_id>,<nonce>").hexdigest()`
     (the three signed fields are alphabetically sorted by key, which for `action`/`client_id`/
     `nonce` is already their natural order)
   - `client_secret` itself is **not** a body field here — it's only the HMAC key.
3. Response: `{"status": 0, "body": {"userid", "access_token", "refresh_token", "scope",
   "expires_in", "csrf_token", "token_type"}}`.

**Errors are a non-zero `status` in the JSON body, with HTTP 200.** Always check `status`
before touching `body`.

**Token lifetimes:** `access_token` 3h. `refresh_token` 1y, but **rotates on every refresh**
and the *old* refresh_token only survives 8h after a new one is issued (or until the new
access_token is first used) — so persist the new refresh_token immediately, atomically, every
time, or a restart between a refresh and the next use can strand you.

## Authorization URL (unchanged, standard OAuth2 code grant)

```
GET https://account.withings.com/oauth2_user/authorize2
  ?response_type=code&client_id=...&scope=user.info,user.metrics,user.activity
  &redirect_uri=...&state=...
```
`state` should be a random value we generate and verify on callback (CSRF protection — not
mentioned explicitly in the docs but standard OAuth2 practice, and cheap to add). The code
returned to the redirect URI is **valid for 30 seconds only** — exchange it immediately in
the callback handler, don't defer.

## Measures — `getmeas`

```
POST https://wbsapi.withings.net/measure
body: action=getmeas, meastypes=<comma list>, lastupdate=<unix> (incremental) or
      startdate/enddate (range), category=1 (real measures; 2=user objectives)
```

**No `/v2/` in this path** — confirmed directly against Withings' own `openapi.yaml` spec
(2026-11-05): the `getmeas` operation's path key is the literal
`https://wbsapi.withings.net/measure`. Withings is inconsistent about `/v2/` per-action — it
*is* used for `getactivity`, `getintradayactivity`, `getworkouts`, and `confirmuser`, just not
`getmeas`. An earlier scrape of this doc had `/v2/measure` for `getmeas`, which was wrong and
caused a live `status=503 Invalid Params` failure — check the path per-action against the spec
rather than assuming all Withings endpoints share one version prefix.

Response:
```json
{"status": 0, "body": {"measuregrps": [
  {"date": 1755767442, "measures": [{"type": 1, "value": 72400, "unit": -3}]}
]}}
```
**Value conversion:** `real_value = value * 10^unit`. E.g. `72400 * 10^-3 = 72.4`.

### meastype codes used for `body_comp`

Confirmed directly from Withings' own quickstart example in the docs: **1 = weight (kg)**,
**6 = fat ratio (%)**, **88 = bone mass (kg)**. The biomarker reference table on
`all-available-health-data` lists "Fat Mass", "Muscle Mass", "Water Mass" as available
biomarkers but renders their numeric codes via client-side JS tooltips we couldn't extract
in this session — so the codes below for fat mass, muscle mass, and hydration are the
long-standing, widely-documented Withings codes (stable for years across their API), **not
independently re-confirmed against today's live docs**. Treat them as "very likely correct,
verify against a real `getmeas` response during the live sync step":

| code | field | `body_comp` column |
|---|---|---|
| 1 | weight (kg) | `weight_kg` — confirmed |
| 6 | fat ratio (%) | `fat_pct` — confirmed |
| 8 | fat mass weight (kg) | `fat_kg` — unconfirmed, standard code |
| 76 | muscle mass (kg) | `muscle_kg` — unconfirmed, standard code |
| 77 | hydration (kg) | `hydration_kg` — unconfirmed, standard code |
| 88 | bone mass (kg) | `bone_kg` — confirmed |

`getmeas` paginates via `more`/`offset` in the response body when results are truncated —
loop until `more` is falsy.

## Completing the OAuth flow manually (no frontend yet)

This needs a real browser hitting the actual host in `WITHINGS_REDIRECT_URI` — `curl` can't
complete it, and Garmin's sync has no equivalent step since it's an API-key exchange, not a
user login.

1. Start the server: `uv run uvicorn catch.main:app --port $CATCH_PORT`.
2. Open `http://<host>:<port>/docs` in a browser, find `POST /api/login`, "Try it out", send
   your password. This sets the httponly session cookie **in that browser**.
3. Navigate the browser to `/auth/withings/start`. It redirects to Withings, you grant
   access, and Withings redirects back to `/auth/withings/callback`.
4. **The browser must be on the exact host in `WITHINGS_REDIRECT_URI`** — `localhost` and
   `127.0.0.1` are different origins to the browser's cookie jar, so logging in on one and
   following the OAuth flow on the other sends no session cookie on the callback, which
   returns 401 (and by then the 30-second authorization code has likely expired anyway).

## Scopes

`user.info,user.metrics,user.activity` — we only need `user.metrics` for weigh-ins, but the
docs' own example requests all three together; narrowing to just `user.metrics` should work
and is what we request, since activity/info aren't used by `body_comp` sync.

## Callback URL on the Pi deployment

`WITHINGS_REDIRECT_URI` must be `https://<pi-name>.<tailnet>.ts.net/auth/withings/callback`
(the real Tailscale HTTPS hostname `tailscale serve` exposes — see `deploy/pi-bootstrap.sh`),
not `localhost`. Two things that follow from that:

- **Re-register the callback in the Withings developer dashboard** (Withings > My Apps >
  this app > Callback URL) to the new `https://...ts.net/...` value whenever it changes —
  Withings validates the redirect URI against what's registered, not just what's sent.
- **The browser completing step 3 above must itself be on the tailnet** (same rule as
  localhost vs. 127.0.0.1 — different origins get no session cookie), so do the manual OAuth
  flow from a device running Tailscale, browsing to the `https://...ts.net` URL directly, not
  through a LAN IP or `localhost` port-forward.

`tailscale serve` here is **tailnet-only HTTPS**, not Funnel — the callback is reachable to
your own devices, not the public internet. If Withings' dashboard ever tries to actively
fetch the callback URL to validate it (rather than just storing the string), that fetch would
come from the public internet and fail against a tailnet-only `serve`; that would need
`tailscale funnel` instead, which is a real public-exposure change and wasn't enabled here.
