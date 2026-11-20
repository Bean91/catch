# Signing and release (nothing here has been done; nothing was submitted or purchased)

## iOS
1. Apple Developer Program membership (US$99/yr, needed for push, HealthKit, associated domains and TestFlight/App Store). Team id → `CATCH_APPLE_TEAM_ID`.
2. In Xcode: set the team on target App; App ID `com.openoted.catch` with capabilities **Push Notifications, Associated Domains, HealthKit**. Xcode manages profiles; the entitlements are in `App/App.entitlements`
   (`aps-environment` is `development`; distribution signing rewrites it to `production`).
3. APNs auth key (.p8): developer portal → Keys → Apple Push Notifications service; key id/team id/.p8 → `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_KEY_P8` (server secret, never in the repo or the app).
4. Version: `MARKETING_VERSION` (user-facing) and `CURRENT_PROJECT_VERSION` (must increase per upload) in the target's build settings.
5. `CATCH_NATIVE_ENV=production npm run native:ios`; Product → Archive → Distribute → App Store Connect → TestFlight (internal testers first).
6. App Store Connect: listing (store-listing.md), privacy "nutrition label" (privacy-disclosures.md), review notes + demo account (app-review-notes.md), age rating, Health & fitness category; screenshots 6.9″/6.5″ iPhone.

## Android
1. Google Play Console (one-time US$25). Use **Play App Signing**; create an upload key: `keytool -genkeypair -v -keystore catch-upload.jks -alias catch -keyalg RSA -keysize 4096 -validity 10000` (never commit it; `*.jks`/`*.keystore` are gitignored).
2. Add a `signingConfigs.release` reading the keystore path/passwords from `~/.gradle/gradle.properties` (not the repo); `versionCode` must increase per upload, `versionName` is user-facing (`app/build.gradle`).
3. `CATCH_NATIVE_ENV=production npm run native:sync && cd android && ./gradlew bundleProdRelease` → `app/build/outputs/bundle/prodRelease/app-prod-release.aab`.
4. Firebase: create a project, add the Android app `com.openoted.catch`, download `google-services.json` into `android/app/` (gitignored; Gradle applies the plugin only when the file exists), create a service account with the "Firebase Cloud Messaging API (V1)" role → `FCM_SERVICE_ACCOUNT_JSON`.
5. App signing SHA-256 (Play Console → App integrity) → `CATCH_ANDROID_CERT_SHA256` so App Links verify.
6. Play Console: store listing, Data safety, **Health apps declaration and Health Connect permissions declaration** (health-policy-review.md), content rating, target audience, the account-deletion URL (`https://catch.openoted.com/account-deletion`), testing track first.

## Both
Supabase dashboard → Authentication → URL configuration: the redirect allow-list holds the web origin used by `VITE_WEB_BASE_URL`. Set the `CATCH_*` server values in README.md. Run `npm run check:native-secrets` after every `native:sync`.
