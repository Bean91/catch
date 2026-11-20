# Deep links and the provider-OAuth return (session 30)

**What opens the app.** (1) the deployment's own https links (`/workouts/:id`, `/calendar`, `/calendar/events/:id`, `/coach`, `/checkin`, `/clubs/join`,
`/settings/connections`) via iOS universal links / Android verified App Links; (2) the app's custom scheme `com.openoted.catch://…` (the provider-OAuth return, and
what the tests use); (3) a notification tap (its `url`). Every incoming URL goes through `deepLinkTargets.ts`: foreign hosts/schemes are ignored, only an
allow-list of routes is navigated to (anything else lands on Today), only the query keys a page reads are kept, the `#fragment` only for club invites. A link that
arrives before sign-in is held and used once after it.

**Association files.** `/.well-known/apple-app-site-association` and `/.well-known/assetlinks.json` are built from `CATCH_APPLE_TEAM_ID` / `CATCH_ANDROID_CERT_SHA256`
and 404 until set (`catch/api/routes_wellknown.py`). Android's manifest claims the same paths with `autoVerify`; the host is `-PcatchHost`. Universal links do not fire for a
URL typed in Safari on the same domain, and cannot be tested in the simulator without the file on a real domain — verify on a device after setting the two values.

**E-mail links** (sign-up confirmation, password reset) use `publicOrigin()` = `VITE_WEB_BASE_URL` as the redirect, so with the files in place they open the app, which
exchanges the PKCE `?code=` itself (the verifier is in its secure storage). Without the app installed they open the web app (where a link requested from the phone's app can't
complete: the verifier is on the phone — same limitation as using the link on another browser).

**Provider OAuth (Withings, Whoop, Concept2).** The web flow relies on a cookie set by the XHR that starts it. The system browser the app opens has neither that cookie nor a
bearer token, so: `POST /api/connections/{p}/oauth/start?native=true` (bearer) returns a 2-minute single-use signed *ticket* URL; the app opens
`GET /auth/{p}/native-start?ticket=…` in the system browser, which redeems it, sets the state cookie *there* and redirects to the provider; the callback sees the "native"
bit and redirects to `com.openoted.catch://settings/connections?provider=…&result=…`, which the app routes (and closes the browser sheet). The ticket uses a different key
derivation from the state cookie, so neither works as the other. Provider redirect URIs are unchanged (still the https callback).
