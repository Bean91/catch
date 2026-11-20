# Privacy disclosures (drafts for the store forms — not legal advice, no legal review)

Basis: `docs/data-inventory.md`, `docs/legal/*` (drafts), the code. **Tracking: none** — no advertising SDKs, no analytics SDKs, no data broker sharing, no cross-app identifiers. All data is linked to the account and used for **App functionality** only.

| Data | Collected? | Linked | Purpose | Notes |
|---|---|---|---|---|
| Email address | yes | yes | account / functionality | sign-in |
| User ID | yes | yes | functionality | opaque account id |
| Health (sleep, HR, SpO₂, HRV) | yes | yes | functionality | from connected sources; from Apple Health/Health Connect only after in-app consent |
| Fitness (workouts, exercise logs) | yes | yes | functionality | |
| Photos | yes, transiently | yes | functionality | PM5/meal photo sent for one estimate; PM5 photos kept only if the person attaches them to a piece |
| Coarse location | yes | yes | functionality | GPS tracks from synced workouts (not from the phone) and weather; coordinates rounded for the weather lookup |
| Other user content | yes | yes | functionality | notes, check-ins, coach conversations |
| Diagnostics | no third-party analytics; server logs are redacted | | | |
| Purchases, contacts, browsing/search history, identifiers for advertising, device ID for ads | no | | | the push token is a device address for notifications, not an advertising id |

**Sharing:** with the services the person turns on (their chosen AI provider using their own key; Garmin/Withings/Concept2/Whoop for sync; Open-Meteo for weather; Open Food Facts/USDA for food lookup), each described in-app. Health data from Apple Health / Health Connect is not shared with anyone and is not used for advertising or data mining.
**Encryption:** in transit (TLS); credentials sealed at rest (AES-256-GCM); the session is in the Keychain/Keystore. **Deletion:** in-app (account-deletion.md) and a public URL.
**Apple:** `PrivacyInfo.xcprivacy` is in the app (no tracking; the collected types above; required-reason APIs: UserDefaults `CA92.1`, file timestamp `C617.1`). `ITSAppUsesNonExemptEncryption` = false (standard TLS only). Third-party SDK manifests come from the Capacitor packages.
**Google Data safety:** declare the rows above as collected, none "shared" except where the person enables a provider/AI integration; data encrypted in transit; users can request deletion (link above); health data from Health Connect covered by the Health apps declaration.
**Must be reviewed before submission:** the privacy policy draft must name Apple Health / Health Connect imports, push tokens and the camera; legal review of all `docs/legal` drafts.
