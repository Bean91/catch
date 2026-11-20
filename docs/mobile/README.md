# Catch native apps (iOS and Android)

Capacitor 8 shells around the same React/Vite frontend, talking to the same **public** API with the same **Supabase Auth** project as the web app
(`catch.openoted.com`). No second frontend, no copied business logic, no privileged credential in the app. The Pi stays a separate web/PWA install.
Everything here is session 30; decisions and findings are in PLAN.md.

## What is in the app, beyond the web build

| Feature | Where | Notes |
|---|---|---|
| Session in Keychain / Keystore | `web/src/lib/native/secureStorage.ts` | GoTrue `storage` adapter; nothing in webview localStorage; first-launch marker clears a Keychain session left by a previous iOS install |
| Native push (APNs / FCM) | `lib/native/push.ts`, `catch/notify/native_push.py`, `docs/mobile/push.md` | permission asked only on the Enable tap |
| Deep links + notification taps | `lib/native/deepLinkTargets.ts` (pure, allow-list), `useDeepLinks.ts` | `docs/mobile/deep-links.md` |
| Camera / photo library | `lib/native/camera.ts` | same `resizeImage()` + endpoints as the web |
| Offline strength logging | unchanged `gymDb.ts`/`gymSync.ts` + retry timer + resume trigger | `queryPersist.ts` replaces the service worker's read cache |
| Haptics, lifecycle, back button, status bar, external links, share-sheet export | `lib/native/*` | no-ops on the web |
| Health import (Apple Health / Health Connect) | `lib/native/health.ts`, `pages/HealthData.tsx`, `catch/sync/health_import.py` | `docs/mobile/health-data.md` |

## Environments and ids

| `CATCH_NATIVE_ENV` | app id (iOS bundle / Android applicationId) | name | web bundle mode |
|---|---|---|---|
| `production` (default) | `com.openoted.catch` | Catch | `native-production` |
| `staging` | `com.openoted.catch.staging` | Catch Staging | `native-staging` |
| `development` | `com.openoted.catch.dev` | Catch Dev | `native-development` |

Dev/staging install beside the store build. `web/.env.native-<env>.example` lists the (public-only) variables; copy to `.env.native-<env>.local`.
`vite.config.ts` refuses to build if the API/web base isn't an https origin (a local http origin is allowed in development only), if a
`VITE_*` value looks like a database URL or a Supabase secret key, or if `VITE_CATCH_MOCK` is set in a production build.
`scripts/check-build-secrets.mjs` (`npm run check:native-secrets`) scans the built bundle, the copies synced into both projects and credential-looking file names.

## Build (macOS)

```sh
cd web && npm install
# one-time: JDK 21 + Android SDK (docs below), Xcode 26+
cp .env.native-development.example .env.native-development.local   # fill in the publishable key
CATCH_NATIVE_ENV=development npm run native:sync     # builds dist-native with --mode native-development, then `cap sync`
```

**Android** (`JAVA_HOME` = JDK 21, `ANDROID_HOME` = the SDK, `android/local.properties` has `sdk.dir`):
`cd android && ./gradlew assembleDevDebug` (flavors `dev`, `staging`, `prod`; `assembleProdRelease` / `bundleProdRelease` need a keystore, see release.md).
Deep-link host: `-PcatchHost=<host>` (default `catch.openoted.com`). Android 8+ only (Health Connect's minimum).

**iOS**: `npm run native:ios` opens Xcode, or
`xcodebuild build -project ios/App/App.xcodeproj -scheme App -destination 'platform=iOS Simulator,name=iPhone 17 Pro' CODE_SIGNING_ALLOWED=NO CATCH_ID_SUFFIX=.dev "CATCH_APP_NAME=Catch Dev"`.
Dependencies come from Swift Package Manager. If `xcodebuild` sits at "Resolve Package Graph", SwiftPM is waiting on a macOS Keychain
prompt for a github.com credential: run `swift package --disable-keychain resolve` inside `ios/App/CapApp-SPM` once, copy its `Package.resolved` to
`ios/App/App.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/`, and build with `-clonedSourcePackagesDirPath CapApp-SPM/.build -disableAutomaticPackageResolution -onlyUsePackageVersionsFromResolvedFile`.
The iOS target is iPhone-only (`TARGETED_DEVICE_FAMILY = 1`). Entitlements (`App/App.entitlements`): push, associated domains, HealthKit — they need a
provisioning profile that has those capabilities, so a signed build needs an Apple Developer account; unsigned simulator builds ignore them.

**Icons/splash**: `node scripts/make-native-assets.mjs` derives the sources from the PWA icon into `web/assets/`, then `npm run native:assets`.

**Demo/screenshot build** (no backend, fixtures only): `VITE_CATCH_MOCK=1 npx vite build --mode native-development && npx cap sync`.

Android Auto Backup and device transfer are disabled (the Keystore-encrypted session can't be restored elsewhere, and the webview storage holds health-derived caches); iOS keeps the session in the Keychain as `afterFirstUnlockThisDeviceOnly`.

## Server settings the apps need (public deployment)

`CATCH_NATIVE_ORIGINS` (default `capacitor://localhost,https://localhost`), `CATCH_NATIVE_URL_SCHEME` (`com.openoted.catch`), `CATCH_APPLE_TEAM_ID`,
`CATCH_APPLE_BUNDLE_ID`, `CATCH_ANDROID_PACKAGE`, `CATCH_ANDROID_CERT_SHA256` (→ the two `/.well-known` files), `APNS_KEY_P8`/`APNS_KEY_ID`/`APNS_TEAM_ID`/`APNS_TOPIC`,
`FCM_SERVICE_ACCOUNT_JSON`. All optional; each feature is off until its settings exist (`GET /internal/config-check` reports set/unset). In the Supabase
project, add the web origin (and nothing else) to the redirect allow-list — the apps use the universal link, not a custom scheme, for e-mail links.

## Testing

See `test-report.md`. Android: `web/tests/native/android-e2e.mjs` drives the real app over its WebView with Playwright's Android driver (needs an emulator with a
google_apis image, a local public-mode API and the throwaway Supabase stack; the script header lists the environment). iOS: simulator build/launch, `simctl push`, screenshots.
