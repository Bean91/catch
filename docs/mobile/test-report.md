# Test report — session 30 (2026-11-19/20)

Environment: macOS, Xcode 26.3, iOS 26.3 simulator (iPhone 17 Pro); Android emulator (Pixel 8 profile, API 36 google_apis arm64); JDK 21; local throwaway Supabase stack (real GoTrue + RLS) and a real `catch.main` app in public mode on it.
**No physical iPhone or Android phone, no Apple/Google/Firebase credentials were available.** Everything below that says "device" is therefore unverified.

## Automated, all green
| Suite | Result |
|---|---|
| `CATCH_DEPLOYMENT=personal uv run pytest --ignore=tests/pg` | **2177+ passed, 3 skipped** (final figure in the closing report), incl. new: CORS (6), native push (26), well-known (5), native OAuth (8), health import API (13), health analytics (33), structure/route-auth updates |
| `tests/pg` on the local Supabase stack | **97 passed** — migration 0009 applies, schema matches the models, RLS/grants for `health_consents` and the global `native_push_tokens`, token hand-off and cascade on the real roles |
| web `vitest` | 91 passed (deep-link resolver, apiBase, + existing) |
| web `test:touch` (Playwright; Chromium+CDP touch, real WebKit, desktop mouse) | 257 passed, 8 skipped |
| `test:update`, `test:gym` | 4 passed, 1 passed |
| `test:public` | **18 passed** (public web auth, incl. account deletion). It could not start at first — pre-existing, reproduced on the base commit: the dev server's env guard rejected the suite's fake Supabase URL; the URL-shape check now applies to `vite build` only. |
| Web build / bundle budget / secrets | build ok; initial JS 229.8 KB gzip (budget 250); `check-build-secrets` clean on the web build |
| `npm run check:native-secrets` + APK content scan | clean (no private key, service-account, DB URL, `sb_secret_`, APNs/FCM names) |

## Native builds
- **Android** `assembleDevDebug` (flavors dev/staging/prod) compiles with JDK 21 / SDK 36; merged manifest verified with `aapt2` (7 Health Connect read permissions, camera, notifications — the plugin's other ~35 removed).
- **iOS** simulator build **succeeds** (Debug, unsigned); `PrivacyInfo.xcprivacy` is in the bundle. A signed build was not attempted (needs an Apple Developer team).

## Android emulator, real app ↔ real backend (`web/tests/native/android-e2e.mjs`, Playwright Android driver over the WebView)
| Check | Result |
|---|---|
| Origin is the native shell (`https://localhost`) and the API call crosses origins (CORS) | pass |
| Sign in through the same Supabase Auth project the web uses | pass |
| No session token in webview localStorage; session held in the native secure store, encrypted at rest (no JWT/`access_token` in clear) | pass |
| Cold start restores the session; in-place app update (`adb install -r`) keeps the session | pass |
| Background → resume stays signed in | pass |
| Deep links (custom scheme): workout, calendar, event, coach, check-in (opens the sheet), connections (query kept), off-allow-list → Today; cold start from a link lands on the workout | 10/10 |
| Offline strength logging (API unreachable via a root firewall rule): 3 sets logged; **force-stop and relaunch offline keeps them**; reconnect flushes on its own; the server gained exactly those 3 sets | pass |
| Hardware back closes the open sheet instead of leaving the app | pass (manual) |
Bug found and fixed here: with the phone online but the server unreachable, nothing retried the queue until the next resume — `useGymSync` now retries every 20 s while sets are pending.

## iOS simulator
Launch, safe areas, live dark/light following the system, icon/splash assets, `PrivacyInfo`. `xcrun simctl push` delivers a banner and `simctl openurl` reaches the app, but the simulator shows a system "Open in Catch Dev?" confirmation and **there is no CLI/tap automation in this environment**, so the iOS tap-to-route and iOS sign-in/Keychain/offline paths were **not** exercised (the JS is the same code that passed on Android; the native pieces — Keychain via `@aparajita/capacitor-secure-storage`, APNs registration callbacks in `AppDelegate`, URL scheme in `Info.plist` — are untested at runtime).

## Not verifiable here — do on devices
Real APNs/FCM delivery and tap routing; universal links / verified App Links (need the files on the real domain + signing identity); HealthKit/Health Connect data (device read path, permission sheets, the 30-day Android window, field mappings); camera permission prompt and the PM5 photo flow on a phone (the emulator has a virtual camera but it was not driven); iOS Keychain persistence across reinstall; haptics; app-switcher/lock-screen behaviours; iOS Keychain-vs-uninstall marker; scroll/pinch feel of the SVG charts inside WKWebView and Android WebView; TestFlight/Play internal-track installs.
