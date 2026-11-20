# Mobile experience review (Part D)

Reviewed on the iOS simulator (iPhone 17 Pro, dark), Android emulator (1080×2400, light) with fixture data (`screenshots/`), plus the existing 257-test Playwright touch/WebKit suites. Not reviewed on real devices or on a 360×640 handset or iPad (iPhone-only target).

| Finding | Fix |
|---|---|
| 19 bottom sheets/dialogs used `max-h-[Nvh]` (the tall URL-bar viewport) and no bottom safe-area padding | `dvh` and `pb-[calc(1.25rem+env(safe-area-inset-bottom))]` |
| Landscape notch/rounded corners: no left/right insets anywhere | `#root` and the bottom nav pad by `env(safe-area-inset-left/right)` (0 in portrait) |
| Theme read the system scheme once and then froze it (it wrote the current theme to localStorage on every load) | only an explicit tap is stored; with none, the app follows the system live; status-bar style follows the theme |
| Keyboard | `Keyboard.resize = native` (the webview shrinks, bottom-anchored sheets stay above the keyboard) + the focused field scrolls into view |
| Android hardware back | closes the open dialog, else history back, else exits |
| Offline reads with no service worker | persisted query cache for the read screens (allow-list, per account, 7 days, wiped on sign-out) |
| Offline queue only retried on connectivity events | 20 s retry while sets are pending; flush on app resume |
| External links replaced the app page | `@capacitor/browser` |
| Data export used a blob-URL download (a no-op in a webview) | Filesystem cache file + share sheet |
| PM5 photo `<img src>` could not carry the bearer token (a latent public-web bug too) | fetched as a blob through `authedFetch` |
| Text selection/callout on buttons in a native shell | `user-select: none` on buttons/nav links |
Left as is, deliberately: the existing design tokens, the 8-item bottom nav (fits at 1080 px; unchecked at 360 px), the chart gesture engine (touch-action rules unchanged).
