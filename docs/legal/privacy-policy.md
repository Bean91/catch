# Privacy policy — DRAFT

> **DRAFT — NOT LEGALLY REVIEWED.** This is an engineering draft of what Catch actually does with personal data, written from the code
> (`docs/data-inventory.md`). It is not a compliant privacy notice and must not be published as one until a qualified lawyer has reviewed it for the
> jurisdictions you serve. See "Open questions for counsel" at the end.

## Who runs this

Catch is a self-hosted rowing training app. On a **personal install** you run it yourself and nobody else receives your data from it. On the
**public deployment** the operator named in the app's footer (to be filled in: legal name, address, contact) runs it and is the party that decides
how your data is used (the "controller", in GDPR terms) — **[counsel: confirm roles for the operator, Supabase and FastAPI Cloud]**.

## What we collect and why

* **Account:** your email and a password hash (held by Supabase Auth), and a display name if you give one. To sign you in.
* **Training and health data you connect or enter:** workouts and heart rate, power, GPS tracks, sleep, HRV, resting heart rate, body
  measurements, nutrition logs, workout notes, morning check-ins (including niggle notes), goals and injuries you tell the coach. To give you
  training analysis. Much of this is **health data**, which many laws treat as a special category.
* **Credentials you provide:** AI provider keys and tokens for Garmin, Withings, Whoop and Concept2, stored encrypted and never shown back.
* **What you publish on purpose:** a handle, an age band you declare, leaderboard results and club activity.
* **Operational logs:** notification history, an audit of what connected apps did (never their content), and moderation records.

We do not run advertising or analytics and do not sell data. Nothing in the app calls a third-party analytics or error-reporting service.

## Where it goes

The full table is in `docs/data-inventory.md` §4. In short: it is stored at **Supabase** (database and sign-in) and served by **FastAPI Cloud**;
it is fetched from the services you connect, using your own credentials; **only if you turn it on**, parts of it are sent to the AI provider you
chose (see the AI data-sharing explanation); rounded location (about 11 km) and a date go to Open-Meteo for weather; barcodes and search text go to
Open Food Facts and USDA; browser notification services receive an encrypted notification; your browser fetches map tiles directly from
OpenStreetMap (which sees your IP address and the area you view).

## AI

Nothing is sent to an AI provider until you read what is sent and agree, and every category starts off. See the AI data-sharing explanation.

## Who can see your data

Only you, through your account — enforced in the application and again by the database (row-level security). The operator can technically read the
database with administrator access. Other users see only what you publish (leaderboards, clubs). Platform moderators see reported content and
moderation records, never your private training or health records. A coach sees only technique notes and feedback you mark shared.

## How long we keep it

Until you delete it or your account. Automatic clean-up: notification and tool-call logs 90 days; AI usage, merge and match history 400 days;
resolved club reports 12 months; club audit entries 24 months. After account deletion we keep, without your identity attached, moderation decisions
about published results, club posts you wrote, and an opaque deleted-account marker. See the data deletion policy. **[counsel: retention periods]**

## Your controls

Settings → Privacy: download everything you own; delete data by category; delete your account; choose what the AI may see; end app access;
opt out of leaderboards; manage club sharing. Provider connections can be removed in Connections.

## Children and young people

Catch can be used by people under 19. We ask for a self-declared age band only where a feature needs one (clubs, leaderboards, AI sharing) and
never a date of birth. People declaring under 19 get stricter defaults: junior clubs are private and approved by a coach; leaderboard entries use a
handle or "Anonymous" with year-only dates; health data cannot be shared with an AI unless they confirm a parent or guardian knows. Self-declared age
is not verified. **[counsel: minimum age, consent age by jurisdiction (13 and 16 are placeholders in the code), guardian consent and its verification]**

## Security

Encryption in transit; credentials sealed with AES-256-GCM under a per-user key; strict content-security policy; secret scanning and dependency
audits in CI. No system is perfectly secure; see `docs/security.md` and the findings register for known gaps.

## Changes and contact

We will describe changes here and in the app. Contact: **[to be filled in]**.

## Open questions for counsel

Controller identity and operator contact; lawful basis for each purpose (consent for health data? contract?); international transfers (Supabase
region, AI providers in the US); minimum age and parental consent by jurisdiction; whether publishing minors' results is acceptable and on what
terms; retention periods and whether moderation records may outlive an account; breach-notification process; cookie/local-storage notice; data
subject request handling and response times; whether a data protection impact assessment is required.
