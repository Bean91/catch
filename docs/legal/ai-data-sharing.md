# What is shared with AI providers — DRAFT

> **DRAFT — NOT LEGALLY REVIEWED.** Technical explanation of the code's behaviour (`docs/ai-data-sharing.md` has the engineering detail).

**Catch never calls an AI provider by itself.** It happens only when you chat with the coach, ask it to read a photo, or connect an app such as
Claude Desktop — and always with *your* key, to the provider *you* chose (Anthropic, OpenAI, Google Gemini, or your own Ollama server on a personal
install). **Nothing is sent until you have read this and agreed, and every category starts off** (Settings → Privacy → AI sharing).

## What a chat request contains

1. The coach's instructions (fixed text).
2. A short summary of what you've told the coach: upcoming events, goals and remembered facts (category "Coach memory" / "Calendar"), today's
   check-in and any training issue ("Notes and check-ins"), the illness early-warning and the top recommendation ("Recovery…"). Sections for categories that are
   off are left out.
3. The conversation so far (your messages, the coach's replies, the tools it called and their results), trimmed to roughly 60,000 tokens.
4. The list of tools the coach may call (names and descriptions, no data).

## What a tool result can contain, by category

| Category | Examples |
|---|---|
| Recovery, sleep and body | recovery, strain, HRV, resting HR, sleep, stress, body battery, body composition, load, trends, illness level, recommendations |
| Workouts and training | workout list/detail with titles and notes imported from Garmin, Concept2, Whoop; zones; erg tests; strength; GPS-derived summaries and weather (**never raw coordinates**); training insights |
| Nutrition | foods logged, calories, macros, targets |
| Notes and check-ins | your notes and RPE |
| Coach memory | goals, injuries, schedule, preferences |
| Calendar, plans, library | events, planned sessions, templates, technique notes, coach feedback |
| Photos | one meal or PM5-screen photo, sent once, **not stored by Catch** |

If a category is off, the coach receives "sharing is switched off" instead of the data. Other people's public information (leaderboards, club posts)
is not in any category: it can appear if you ask the coach about it, labelled as untrusted text.

## What is never sent

Your AI keys and any credentials; other users' private data; raw GPS coordinates; your email; device tokens; account identifiers. (Tested.)

## After it leaves Catch

The provider handles it under its own terms and retention. Catch asks OpenAI not to store requests (`store: false`) and cannot control the others.
Withdrawing consent stops future sharing; it cannot recall what was already sent.

## Young people

If you say you are under 19, health categories stay off unless you confirm a parent or guardian knows.

## Apps like Claude Desktop

An app connected with a device token is a second route to the same tools. It obeys the same category switches, is read-only unless you gave it write
access, expires after 90 days by default, and everything it does is listed under Settings → Privacy → Recent activity by apps.
