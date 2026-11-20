# Native push (session 30)

**Registration.** Settings → Notifications → "Enable notifications on this device" (native build) asks the OS for permission *in that tap*, registers
with APNs (iOS) or FCM (Android) and POSTs `{platform, token, environment, app_id, label}` to `POST /api/push/native/subscribe`. Nothing is requested at launch.
The listener for notification taps is registered at launch (it asks for nothing) so a tap that cold-starts the app is not lost.

**Storage.** `native_push_tokens` (migration 0009) is a *global* catch_api-only table (like `deleted_accounts`) so a device token belongs to exactly one
account: registering it from another account moves it, and sign-out/account deletion remove it. Only `catch/sync/native_push_store.py` touches it. The API never
returns a full token — a device recognises its own row by the last eight characters. Cap: 10 per account.

**Delivery.** `push.notify()` fans out to Web Push and to native tokens, each channel gated on its own configuration (an unset VAPID key no longer silences the phone).
`catch/notify/native_push.py`: APNs HTTP/2 with an ES256 provider token (`.p8`), FCM HTTP v1 with an OAuth token minted from the service-account key. Hosts are fixed in
`core/netguard.py`. A token is pruned only when the service says it is dead (APNs 410 / BadDeviceToken after trying the other environment, FCM 404/UNREGISTERED);
a bad provider credential never deletes a device. Payload: `{title, body, url, type}`; `url` is an in-app path routed through the same allow-list as links.
Quiet hours and the five per-type toggles are the existing ones.

**Not verified here (needs credentials/devices):** actual delivery through Apple/Google. Covered: the senders against mock transports (JWT claims decoded and verified,
host selection, error mapping), the store on PostgreSQL, and the tap → screen path via `xcrun simctl push` / intents. To go live: an APNs key (Apple Developer
account) and a Firebase project (`android/app/google-services.json`, FCM service account), then set the `APNS_*`/`FCM_*` server secrets.
