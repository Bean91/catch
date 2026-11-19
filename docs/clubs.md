# Clubs, team training and group challenges (session 27)

Public deployment only (every route answers 404 on a personal install). Signed-in users only. Clubs replace session 26's join-code-only clubs; see §12 for what
happened to the old rows.

Code: `catch/analytics/clubs.py` (roles, the permission matrix, validators, invites, k-anonymity), `analytics/challenges.py` (challenge limits, scoring, ranking) —
both pure; `catch/sync/clubs.py` (the athlete-facing service), `club_team.py` (announcements, sessions, participation, the results board), `club_challenges.py`
(a member's own standing), `club_store.py` (the few system-role operations); `catch/api/routes_clubs.py` and the club part of `routes_moderation.py`;
`catch/coach/club_tools.py`; migration `0006_clubs.py`; web `pages/Clubs.tsx`, `ClubPage.tsx`, `ClubChallenge.tsx`, `ClubJoin.tsx`, `components/clubs/`.

## 1. Who clubs are for

A club is for **adults** or for **juniors** (under 19), fixed at creation and never changeable. Age is **self-declared** (a handle and an age group on a person's
club profile, reusing session 26's youth bands U14–U19, the minimum age of 13, and the guardian-agreement tick below 16). **Catch cannot verify anyone's age or
identity**, and says so; the rules below limit what a wrong declaration can reach, they don't make it impossible.

| | adult club | junior club |
|---|---|---|
| members | adults only | young athletes; staff are adults |
| visibility | public (listed in Discover, members-only inside) or private | **always private**, never listed |
| how people join | open, by request, or by invite link | **request only**, by invitation, **a coach approves every young member** (the owner counts as a coach here: *session 27 follow-up*) |
| posts, sessions, challenges | any staff publishes directly | **only a coach's or the owner's go out directly**; an admin's wait for a coach (or the owner) |
| logo | optional (admins) | optional (admins), visible to members only (the club is private) |
| web links in text | allowed | **allowed in posts and sessions**; still refused in the club description, location and rules |
| tighter challenge caps | — | yes (§5) |

A young athlete can exist **only** inside a junior club; an adult can hold any role in an adult club and owner/admin/coach in a junior one, never "athlete" in a junior one.
This is a CHECK constraint on `club_members` (`(age_class='youth') = (role='athlete' AND club_audience='junior')`) as well as service code, and a young person cannot
start a club. Changing between an adult and an under-19 profile is refused while you are in any club.

## 2. Roles and permissions

Roles: **owner**, **admin**, **coach**, **athlete**. (A club's *coach* role is unrelated to a coach **device token** or the in-app AI coach; coach-role tokens still reach only
the five tools in `docs/library.md`, none of them club tools.) The one matrix lives in `analytics/clubs.py`; the browser holds none of it and renders the `capabilities`
the server returns.

| action | owner | admin | coach | athlete |
|---|---|---|---|---|
| view the club, members (handles), calendar, board, challenges | ✓ | ✓ | ✓ | ✓ |
| edit club details / rules, logo | ✓ | ✓ | | |
| transfer ownership, delete the club | ✓ | | | |
| set roles | ✓ (admin/coach/athlete) | ✓ (coach/athlete) | | |
| remove a member (reason required) | ✓ (not the owner) | ✓ (coach/athlete) | ✓ (athlete) | |
| create invites | ✓ | ✓ | ✓ (athlete invites only) | |
| decide a join request | ✓ | ✓ | ✓ — in a **junior** club only a **coach** decides an athlete; only an **owner/admin** decides a coach | |
| publish an announcement / session / challenge | ✓ (junior: waits for a coach) | ✓ (junior: waits) | ✓ directly | |
| approve a held post | adult clubs: any staff · junior: **coach only** | | | |
| join/leave a challenge, link a workout, share a result, report, block | ✓ | ✓ | ✓ | ✓ |
| leave the club | transfers first | ✓ | ✓ | ✓ |

Staff can't act on their own level or above, and nobody changes their own role. **Every decision that affects another person needs a written reason and is recorded in
the club's append-only audit log.** A person's role is checked by the service (clear 403/404), by an RLS policy on the same table, and,
for the matrix itself, by `catch_club.*` SQL predicates that `tests/pg/test_clubs.py` compares against the Python matrix for **every** actor/target/role combination.

## 3. Joining, leaving, removal

- **A private or junior club can be joined only with an invite link.** Public adult clubs are discoverable; a visitor sees name, description, location, rules and a member **count** (never a list).
- **Invites** (`/clubs/join#token`): random, only a hash is stored, shown once, expire in 1–30 days, optional use limit, revocable. The token is in the URL *fragment* (never sent or logged) and cleared from the address bar after use. An athlete invite and a coach invite are different; only owner/admin make coach invites.
- **Open** clubs admit directly; an **invite-policy** adult club admits directly on a valid invite; a **request** club (and every junior club) creates a request staff decide. An approved request is a 14-day window to join, completed by the applicant's own request.
- **Rules**: a club can state rules; joining requires accepting them (recorded).
- **Leaving** removes your own rows in that club (shared results, participation, challenge entries). **Removal** by staff is a *tombstone* (`status='removed'`): the person can't rejoin, can't delete the record, and the staff member's reason is in the audit log. A private club no longer admits it exists to someone removed from it.
- Pending requests: at most five per person; the applicant can withdraw.

## 4. Team training

- **Team sessions** are plans for the club: title, type, date, time, duration, distance, notes. A team session is **never a completed workout and never a `PlannedWorkout`** (nothing is added to anyone's own plan).
- **"I took part"**: a member may *choose* to associate one of their own workouts with a session (±1 day). The club learns **that they took part**, plus their distance/time **only if they tick the box**. The workout itself, its id and every other metric stay theirs.
- **Participation is shown as a count.** **Team summaries are aggregate-only**: sessions, participations, attendance rate, and distance/time totals that appear **only when at least three members chose to share a number** (`K_MIN = 3`); with fewer, the total and mean are hidden so they could never be one person's figure. The summary contains no member identifiers.
- Coaches see **none** of a member's recovery, sleep, HRV, weight, nutrition or training by default — there is no column in any club table that could hold them (`tests/test_clubs_schema.py` enforces that structurally; `tests/tenancy/test_clubs_api.py` seeds distinctive health values and asserts none appears in any club response, including summaries and tool output).

## 5. Challenges

Metrics: **distance**, **time trained**, **number of sessions**, **erg-test participation**, **consistency**. A challenge states its rules in plain words on its page.

Safety rules (constants in `analytics/challenges.py`, marked **pending safety review**; a reasonable first position, not coaching or medical advice):

- **Volume is capped three ways.** A per-day cap (default 3 h / 30 km; junior 2 h / 20 km), a per-week ceiling (12 h / 150 km; junior 8 h / 100 km) and a **goal the score can never exceed**. A distance or time challenge with no goal is refused (also a CHECK constraint); a goal that needs more than the weekly ceiling is refused. Extra volume earns nothing, so there is no way to win by overtraining. Sessions count at most 2 a day and 6 a week, and must last at least 15 minutes (default 20).
- **Consistency counts weeks that reach a modest target (1–5 sessions)**, never more. **There is no streak metric.** A member can **excuse any week** (illness, rest, travel) with a tap and **no reason stored**; an excused week isn't counted against them.
- **Erg-test participation** counts distinct test types completed (reusing the leaderboards' exact eligibility), never how fast.
- **Nothing about weight, calories, recovery, sleep or any health metric is used, ranked or shown**; no such metric exists in the vocabulary, and a health value on an activity row changes nothing (tested).
- A challenge lasts 1–12 weeks and can't start in the past.

Scoring and integrity:

- Only activities recorded by a **connected source** (Garmin, Concept2, Whoop) count. Typed-in work in Catch (the in-app strength logger, pieces) and anything the member excluded from their totals never counts; the sport comes from the provider's record, not a label the member can edit. **A Concept2 result must also carry Concept2's own `verified` flag** (the signal that separates a PM5/ErgData result from one typed into the logbook by hand; its exact semantics are still unconfirmed on a live account, see `docs/leaderboards.md` §1). **Garmin and Whoop don't tell Catch whether a workout was entered by hand, so a manual entry there is not detected** and counts (up to the daily and weekly caps).
- **One real activity counts for one account.** `club_challenge_claims` holds a keyed hash of each counted activity under a global primary key; a second account that sees the same Concept2 result collides on it, is told nothing, and has its score computed without that activity.
- **A score is computed by the member's own request from their own data** and written as one integer; **no endpoint accepts a score**, and the RLS policies let a member write only their own entry, only while the challenge is open. **That the value is honestly computed is enforced by the service, not by RLS**: the database can't tell a computed value from a typed one, so the schema must stay off Supabase's Data API (see §10).
- **Ties**: equal scores share a rank (1, 2, 2, 4). The order *within* a tie is a per-challenge hash, so nothing implies one member is ahead (no date, join order or name).
- A challenge is open until its end date; standings settle for **2 days** (provider syncs lag) and then **freeze**. This is computed from the date, with no finalizer job. Joining is open until the end date; opting out is always allowed while it is open and releases the member's claims.
- Scores refresh when a member joins, when they open the challenge, and after each successful sync (`scheduler.run_sync`): no new scheduled job.

## 6. The club results board

A member **explicitly shares** an exact 500/1,000/2,000/5,000/6,000 m or 30/60-minute result with the club (built from the leaderboards' own eligibility and verification, so a club board can't rank something the public boards wouldn't). A member may also tick "show my public leaderboard results on this club's board". Only **verified** results are ranked; the rest are listed separately, labelled. A member can withdraw their own result; staff can hide one with a reason. `club_results` is a separate table, so the public boards cannot change. The public board's **club filter** matches only *public adult* clubs and only members who ticked the box, so it can't be used to enumerate a private or junior club.

## 7. Announcements and approval

Staff post announcements; there are **no member comments and no direct messages** in this session (§14). In a junior club a post by anyone who isn't a coach or the owner is held *pending* and is invisible to athletes until a coach approves it; the same applies to sessions and challenges. A coach's own posts publish directly, are reportable and are audit-logged. Approving needs the right to publish *in that club* (junior: coach or owner), declining needs a reason, and any staff member can take a published post down with a reason.

## 8. What is Public, Club-only, Private

| | visible to |
|---|---|
| a public club's name, description, location, rules, member **count**, logo | every signed-in user (**Public**) |
| members, handles, roles, announcements, calendar, participation counts, challenge standings, the club board, the audit log (staff) | members of that club (**Club-only**) |
| join requests (with the applicant's handle, age class and guardian note) | staff who may decide them |
| a member's workouts, recovery, sleep, HRV, weight, nutrition, training, provider ids, account id, email, real name | **only that member (Private)** — never a club |
| who reported something | the reporter and platform moderators, **never the club's staff** |
| who blocked whom | the blocker only |

Members are shown by the **handle** they chose and addressed on the wire by a **per-club keyed reference**, never an account id, so one response can't be used to recognise the same person in another club.

## 9. Moderation, reports, blocks, audit

- **Rules** are the club's own text, accepted on joining. **Club staff moderate inside their club**: remove or (by tombstone) ban a member, decline or take down a post, hide a shared result — every action needs a reason and writes an append-only `club_audit` row (authenticated and the app role can INSERT/SELECT; one column-limited UPDATE detaches a deleted person; nothing is rewritten or deleted).
- **Reports** can target a club, an announcement, a member or a challenge; reasons are a fixed list. They go to **platform moderators** (`CATCH_MODERATOR_IDS`, the same people as leaderboards) and are **not visible to the club's staff**. Three distinct reporters **auto-hide an announcement** pending a moderator (nothing else auto-acts, so a few accounts can't silence a club). A person can send ten reports a day.
- **Platform moderators** see a queue, a club's open reports, its recent audit and can **suspend or restore a club** (a suspended club leaves discovery and can't be joined; members keep read access), hide/restore a post, remove a member, or dismiss reports — each with a required reason, recorded in the club's audit log as a *platform moderator*. A moderator **cannot act on a club they belong to**.
- **Block** is deliberately light because there is no direct interaction: it hides a member's name from *your* lists and standings. It changes nothing for them.
- There is no support-contact flow beyond the report form yet (see §14).

## 10. Data and access (RLS)

Fifteen **membership-scoped** tables (`clubs`, `club_profiles`, `club_members`, `club_member_prefs`, `club_invites`, `club_join_requests`, `club_announcements`, `club_sessions`,
`club_session_participation`, `club_challenges`, `club_challenge_entries`, `club_challenge_claims`, `club_results`, `club_logos`, `club_reports`, `club_audit`) and one **owned**
table (`club_blocks`, the usual per-owner RLS). Unlike session 26's global tables, the club tables **are** granted to `authenticated` — behind forced RLS policies that call
`SECURITY DEFINER` predicates in a separate **`catch_club`** schema (`role_of`, `is_staff`, `club_visible`, `join_allowed`, `may_publish`, `can_manage_member`, `challenge_open`, …). That
schema is separate because migration `0002` deliberately keeps `catch_private` away from `authenticated`. So **a member of one club cannot read another club's rows even if a query
forgets its WHERE**, and a role can only do what its policy admits (e.g. a coach can remove an athlete, an admin can't mint an admin, only the owner deletes a club, a challenge
entry is writable only by its owner and only while the challenge is open, self-join needs an approved request or an open public adult club). Column-level grants stop anyone changing
`status`/`audience` or a role through the wrong door. **What RLS does not enforce:** score and result *values*, and the k≥3 suppression of totals, are produced by the service. At the database level a member can read other members' shared participation rows and write their own entry's `value`, a `club_results` row's `value`/`verification` and their own `shared_distance_m`, so **the `catch` schema must never be exposed through Supabase's Data API/PostgREST** (the setup guide already says to keep it out of the exposed schemas; session 24's design assumes it); the app role is the only way in, and it only runs the service's code. `catch_api` also has permissive policies on these tables, used **only** under `tenant.system_detached()` through
`catch/sync/club_store.py` for: member counts and invite lookup (a non-member can't read either table), the report threshold, platform moderation and account deletion. That module
also holds the only raw SQL (`catch_club.transfer_ownership`, which re-checks that the caller is the owner).

**Ownership never lapses:** a `BEFORE DELETE` trigger on `user_profiles` hands a club to its longest-standing **adult** member (admins first, then coaches, then athletes; never a
young athlete) or deletes it if there is none, whichever way the account is deleted (the app, or directly in Supabase). Found by running the account-deletion flow on real
Postgres: the auth user is deleted first and the cascade would otherwise have removed the owner's membership before any application code ran.

## 11. Coach / MCP

Five **read-only** tools (66 in total): `get_my_clubs`, `get_club`, `get_club_calendar`, `get_club_challenges`, `get_club_leaderboard`. They call the same service as the REST routes
as the signed-in athlete, so the roles, membership and row-level security above apply to them exactly as to the person: a tool can read only what that person could read in the app, a
private or junior club they aren't in is "Not found", and no argument can name another user. They are athlete-only (a coach-role device token is refused). **There are deliberately no
club write tools**: creating, inviting, approving, removing, posting and moderating are the person's own acts in the app, with their confirmations and audit trail. The "administrative
writes require confirmation and role authorization" requirement is therefore met by there being none; if confirm-gated admin tools are wanted later they must call these same service
functions, never a second path.

## 12. Retention and deletion

- **Session 26's clubs were migrated** (`0006`): each old member became an adult athlete; the creator (else the longest-standing member) became owner; the old join code became a 30-day revocable invite; every club became private/adult/invite. A leaderboard **youth** member was **not** carried into an adult club — that is written to the audit log (`migration_member_not_carried`) instead of deleting the membership silently. A club with nobody left to carry over was dropped.
- **Deleting an account** removes the person's profile, memberships, requests, shared results, participation, entries, claims and blocks; hands over or deletes the clubs they owned (§10); detaches them from what they wrote (posts, decisions, reports, audit rows keep no account id) so a club's history and a moderator's trail stay explainable; and deletes reports about them.
- **Leaving a club** removes your rows in it. **Deleting a club** (owner, after a preview and a confirm) removes everything in it except the audit trail (which has no foreign key so it outlives the club).
- No retention period has been decided for the audit log or reports; that needs a decision before launch (§14).

## 13. Surfaces

REST (`routes_clubs.py`, all cookie/JWT, never a device token): `/api/clubs` — `/mine`, `/discover`, `/profile`, create, `/join`, `/invite-preview` (POST, so a token stays out of URLs), `/{id}` (+ `members`, `members/{ref}/role|remove`,
`prefs`, `invites`, `requests`, `announcements`, `posts/{kind}/{id}/decide`, `calendar`, `sessions`, `…/participation`, `summary`, `challenges`, `…/join|leave|excuse`, `leaderboard`, `results`, `report`, `blocks/{ref}`,
`audit`, `logo`, `transfer`, `delete`, `leave`). Moderators: `/api/moderation/clubs/queue|{id}|{id}/action`. Web: `/clubs`, `/clubs/join#token`, `/clubs/:id`, `/clubs/:id/challenges/:cid`,
a Sidebar entry and a Settings card on the public build (no bottom-nav slot; the bar stays at eight).

## 14. Limits and what is not done

- **Age and guardian consent are declarations**, not verification. A guardian tick is a recorded checkbox, not a consent process. The junior rules limit exposure; they are not a substitute for a safeguarding policy. **A legal/safeguarding review has not happened** and is a launch blocker (as it is for publishing minors' results).
- The challenge caps and the 13/16 thresholds are unreviewed constants.
- **Manual entries made on the provider side (Garmin Connect, Whoop) are not detected** and can count toward a challenge, within the per-day and per-week caps; a hand-typed Concept2 logbook entry is excluded because it lacks Concept2's `verified` flag. This is why challenges are capped and have no prizes: the worst a manual entry buys is the cap.
- No push notifications for invites, approvals or announcements (they appear in the app only); no member comments; no direct messages (deliberately); no club-level finalizer job (freezing is computed from dates). The claim table stops one provider activity counting for two Catch accounts, but only for activities that have a provider id: two accounts can't be told apart by anything else.
- In a junior club **the owner counts as a coach** for admitting young athletes and for posting without waiting (migration `0007`). An admin does not. This means a one-adult junior club works; it also means the "coach approves" safeguard can be one person, the owner. Web links in a junior club's posts and a logo were allowed at the operator's request; links in its description/rules and member-to-member messaging are still not.
- A moderator contact route other than the report form, and a response-time promise, are not built.
- Verified against synthetic data on a local Supabase stack; no hosted project, real provider or real minors were involved.


## 15. Session 28 additions

Reports count towards an automatic hide only from accounts at least **7 days old** (a moderator still sees every report). Platform moderators can **restrict** one social capability of one
account (`publish`, `clubs`, `posting`) with a mandatory reason; the person sees the reason, that "a platform moderator" decided it, and can appeal once (a different moderator reviews) — it never
limits their own data, download or deletion. Moderator detail reads are logged (`moderator_access_log`) and moderator routes require an `aal2` session. Resolved club reports are pruned after 12 months and
the club audit trail after 24 (the database refuses to delete a newer audit row). A junior-club kill switch and safeguarding review remain unbuilt.
