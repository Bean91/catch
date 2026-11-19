# Provider integrations — DRAFT

> **DRAFT — NOT LEGALLY REVIEWED.** What each connection does and what you should know before connecting. Each is your own account; you connect it
> with your own credentials and can remove it any time.

| Service | You provide | Catch reads | Revoke on disconnect | Things to know |
|---|---|---|---|---|
| **Garmin** | A Personal API key from Garmin's own developer page | Activities, sleep, HRV, resting HR, stress, body battery, SpO₂, respiration, skin temp, FIT files (GPS) | No documented call: remove the key at Garmin | Garmin's terms describe personal keys as *not intended for commercial applications serving multiple end users*; the operator may switch this connection off for everyone (`CATCH_GARMIN_BYOK_ENABLED=0`). **[counsel]** |
| **Withings** | Sign in via Withings' OAuth page | Weight and body-composition measurements | No documented call: remove access in your Withings account | Tokens rotate; stored encrypted |
| **Whoop** | Sign in via Whoop's OAuth page | Sleep, workouts, recovery references, body measurements, profile id | **Yes** — Catch revokes at Whoop | Whoop's own recovery/strain scores are shown as reference only and are never inputs to Catch's calculations |
| **Concept2 Logbook** | OAuth, or a personal token you paste | Results, strokes, profile (user id, weight class, max HR); a date of birth is read only when you publish, reduced to an age band and discarded | No documented call: remove access at Concept2 | "Verified" on a leaderboard means Concept2 flagged the result verified and it came through your own connection |
| **AI providers** | Your own API key (or your own Ollama URL on a personal install) | — (Catch sends, see AI data sharing) | Delete the key in Settings → AI providers; revoke it at the provider | You pay the provider; they see what you allow |
| **Open-Meteo** | — | — (Catch sends a date and coordinates rounded to ~11 km) | — | No identifier; weather can be turned off in settings |
| **Open Food Facts / USDA** | — | — (barcode or search text) | — | Public databases |
| **OpenStreetMap tiles** | — | — (your browser asks for map tiles) | — | Your IP address and the area you view go to OSM's servers |
| **Push notifications** | Permission in your browser | — | Turn off in Settings → Notifications | Delivered through your browser vendor's push service |

Disconnecting removes the credential and the sync cursor, never the data already imported (delete that in Privacy).
