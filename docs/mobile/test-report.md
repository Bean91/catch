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

## Session 35 follow-up re-run (2026-11-23)
Redesigned build. Android emulator: `android-e2e.mjs` **20/20** (sign-in, Keystore, cold start, resume, deep links, offline gym logging). A real bug
was found and fixed on the way: `vite:preloadError` also fires for failed API fetches, and the app reloaded mid sign-in (see PLAN.md "Follow-ups").
iOS simulator: Mobile Safari renders the production build correctly. The native shell builds, launches to the login screen in dark mode, and shows
the new navy icon. iOS native sign-in was not run. Nothing was checked on a physical device.

## Session 36 follow-up re-run (2026-11-23)
Android emulator (`catch_pixel8`, dev debug build against a local public-mode API and the throwaway stack): `android-e2e.mjs` **21/21**.
iOS simulator: Debug build succeeds unsigned, installs and launches to the sign-in screen. iOS native sign-in still not run; nothing on a
physical device.

## Session 38: native iOS tab bar (2026-11-24)
Fixtures-only native bundle (`VITE_CATCH_MOCK=1`), Debug, unsigned, Xcode 26.3.
| Check | Result |
|---|---|
| XCUITest `AppUITests` on iPhone 17 Pro, **iOS 26.3** | **11/11** passed (software keyboard on) |
| XCUITest `AppUITests` on iPhone SE (3rd generation), **iOS 18.2** | **11/11** passed. One earlier full run had a single "timed out while synthesizing event" on a tap in the background test; it passed on both reruns and in the final full run |
| WebKit content process killed (`kill -9`) on the Plan tab | the page reloads, the bar stays on Plan, and a following Train tap navigates — the listener re-subscribed and the handshake re-ran |
| Does moving the web view between tab hosts look like the app being hidden? (A probe counted events over six tab switches) | `visibilitychange`: **0**. A window `focus` fires on each switch (the web view becomes first responder again); nothing in the app or TanStack Query v5 listens to `focus`, so no refetch or gym-queue flush |
| Increase Contrast + the largest accessibility text size | the system bar switches to its high-contrast material and keeps fixed labels (the large-content viewer is the system's); the web layer's glass goes off through `prefers-contrast: more` |
| Screenshots: dark and light (iOS 26 glass capsule and lens; iOS 18 standard bar), Reduce Transparency on (system bar opaque and web glass off together), Coach composer above the bar and above the keyboard | as designed. Found and fixed from them: a dark band behind the bar in the light theme (the edge effect faded to the web view's dark background) |
| web vitest / `tsc -b` / production build / bundle | 141 passed / clean / ok / 204.1 KB of 250 KB |
| `test:touch` (3 projects) | 393 passed, 10 skipped, 2 failed — both mobile-webkit horizontal-overflow checks (`intervals.spec`, `route-map.spec`), which fail the same way on a build of the base commit |
Also fixed: in a public-mode **mock** build, Log out called the real auth client and native push, failed silently and stayed signed in;
it now ends the pretend session (`auth.tsx`), which is what lets the sign-out test reach the sign-in screen. Signing back in can't be
exercised with fixtures; the bar's return is the same AppShell-mount → `configure` path as every cold start.
Not done here: Android (no SDK or emulator in this environment; the Android path is the unchanged web tab bar — `nativeTabBarAvailable()` is
iOS-only); a physical iPhone (feel of the glass, ProMotion, real haptics); iOS 15–17 runtimes (none installed; on iOS < 18 the bar hides with
`isHidden`, which may leave the bar's inset in the safe area while a sheet is open);
VoiceOver was not run (the bar is the system control, labelled by its titles).
