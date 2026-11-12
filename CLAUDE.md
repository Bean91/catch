# Catch

Self-hosted, single-user rowing training app. Garmin + Withings + Concept2 data, Whoop-style
recovery/strain, an AI coach (bring-your-own Anthropic key or a local Ollama model) with a
shared MCP server for Claude Desktop. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM) alongside
PiAware.

## Stack

Python 3.12 via `uv`, FastAPI + uvicorn, SQLModel on SQLite (WAL mode), httpx, APScheduler
3.x, pytest, `cryptography` (Fernet), `argon2-cffi` (verify the password hash already in
`.env`), `anthropic` (official SDK, lazy-imported; the OpenAI and Gemini adapters are plain `httpx`, no SDK — session 23), `mcp` (official Python SDK, lazy-imported
for the optional HTTP transport). Frontend: React + Vite + TS, Tailwind v4 (CSS-first config,
tokens as CSS vars), Radix primitives, Framer Motion, TanStack Query, React Router,
`leaflet` (session 20: the route map — OpenStreetMap tiles, lazy-loaded in its own chunk;
tile URL in one constant, `web/src/lib/mapConfig.ts`), `barcode-detector` (session 13: a ponyfill over a self-hosted ZXing-wasm binary — Vite's
`?url` import serves it from `/assets` rather than the package's default jsDelivr-CDN fetch —
used only as a fallback when `window.BarcodeDetector` is absent, e.g. iOS Safari) — built to
`catch/api/static` (gitignored), served by FastAPI. No Docker, no Postgres, no Redis, no Node
at runtime (Node is a build-time-only dependency; the Pi never runs `npm`).

## Layout

```
catch/
  api/          FastAPI routers (routes_coach.py: shared tool endpoints + coach settings/
                conversations/memory/device tokens; sse.py: cancels a streaming response's
                generator on client disconnect — see PLAN.md's session 6 Findings for why
                that needs its own polling helper, not just a per-event check; session 13:
                routes_nutrition.py — foods/barcode/logs/my-foods/saved-meals/targets/
                photo-estimate; session 14: routes_gym.py — exercise library/gyms/stations,
                the idempotent sets-sync endpoint the offline queue flushes to, templates,
                repeat-last-workout, muscle readiness, Garmin-draft confirm; session 15:
                routes_checkins.py — today/upsert/list for the morning check-in, plus
                niggle_streak_days() shared with GET /api/today and the coach's memory
                block; routes_illness.py — dismiss/backtest-mark/backtest-list for the
                illness early-warning flag; routes_tests.py — candidates/list/detail/
                pacing-plan/projection for the erg test center, `{canonical_id}` registered
                *last* in the file — same `/api/activities/duplicates`-style route-order
                pitfall as routes_activities.py, caught by a test here too; session 16:
                routes_push.py — VAPID public key, subscribe/unsubscribe/list/per-device
                test-send, the notification log; routes_status.py — GET /api/status, the
                Settings → Status page's one call: per-source sync health, Garmin key
                expiry, backup status (reads backups/status.json, written by
                deploy/backup.sh — null on any instance that's never backed up), disk/DB
                size, uptime, build; session 17: routes_pieces.py — add/list/update/delete a
                piece, its photo-estimate/upload/serve/delete, align (auto or a manual drag
                from the HR graph), and POST /api/pieces/parse-paste; routes_tests.py gained
                GET /api/pieces/{piece_id}/test-detail, a separate route from GET /api/tests/
                {canonical_id} since a piece's own canonical_id is the *containing* activity,
                not unique to the piece; session 18: routes_training_intelligence.py —
                profile/trends/distribution/consistency/insights reads plus dismiss/save/rate
                on a Recommendation row, all thin wrappers around catch/sync/
                training_intelligence.py's gather_*/list_recommendations, no logic of its own)
  core/         SQLModel models, config, db, security; session 16: healthchecks.py (the
                sync dead-man's-switch ping), uptime.py (process-start timestamp, its own
                module so routes_status.py can import it without a main.py cycle)
  sync/         garmin_client, withings_client, concept2_client, scheduler, upsert helpers;
                session 8/12 (cross-source matching + Peloton + body comp + per-sample
                zones/strain — see PLAN.md): matching.py (the DB-facing half of the matching
                engine — ensure_canonicals/find_candidate_pairs/apply_auto_merges/manual
                merge-split-not_duplicate, run after every sync), canonical.py
                (resolve_canonical — field-priority merge of a canonical's member Activity
                rows into its displayed fields + auto-title, plus its zones/strain via
                zones_samples.py), fit_parse.py (streams a FIT file's record/lap messages
                with `fitdecode`, Peloton detection via file_id.manufacturer), samples.py
                (builds the 1Hz sample arrays FIT parsing or Concept2 strokes produce and
                writes ActivitySamples), body_comp.py (one resolved daily body-comp reading
                across however many scales reported one), rowing_predict.py (shared
                "recent best Concept2 pieces" gathering for GET /api/predict/2k and the erg
                power-zone threshold); session 13: nutrition.py (the DB-facing nutrition
                layer — food search/barcode-lookup-or-fetch/logging/my-foods/saved-meals/
                targets/week-summary, shared by routes_nutrition.py and the coach tools),
                openfoodfacts_client.py (barcode lookup via OFF v2, rate-limited + negative-
                cached, plus opt-in free-text search via OFF's legacy `/cgi/search.pl` — see
                `include_off` in nutrition.py and docs/nutrition-endpoints.md for why it's
                opt-in rather than part of the debounced search box), usda_client.py (USDA
                FDC branded-food search/barcode/detail, the free-text search source that's
                always in-budget since it has no as-you-type restriction); session 14:
                gym.py (the DB-facing gym-logger layer — exercise library, gyms/stations,
                idempotent set upsert keyed on client-generated UUIDs, e1RM/PR detection,
                muscular-load caching onto CanonicalActivity, Garmin-draft set import/
                confirm; catch/analytics/equipment.py and strength.py hold the pure math);
                session 15: erg_test.py (the DB-facing half of the erg test center —
                list/candidate-detection/next-upcoming-event lookup/pacing-plan save; a
                "test" is just a CanonicalActivity with `{"tags": [..., "test"],
                "test_type": "2000m"}` in its existing overrides_json, no new table);
                session 16: state.py gained SyncState.consecutive_failures/alert_sent_at
                (edge-triggered sync-broken alerting — record_error crosses the 3-in-a-row
                threshold exactly once per broken episode, record_success clears both and
                pings healthchecks.io) and a ping on every successful sync;
                garmin_client.py's sleep sync gained wake_time_minutes (parsed from
                `sleepEndTimestampLocal` — see docs/garmin-endpoints.md's gotcha on why
                that field, unlike its GMT sibling, isn't a real UTC instant);
                scheduler.py gained check_notifications (the 10-minute job driving all
                five catch/notify/triggers.py checks); session 17: piece.py (the DB-facing
                half of pieces — create/update/delete, auto/manual alignment against a
                member's own sample stream, the Part D.3 power overlay
                power_member_and_samples called from canonical.py's _resolve_zones, and Part
                D.4's absorb_concept2_piece_results, called from matching.py's run_matching);
                matching.py gained that absorb call; canonical.py gained the rowing
                power-zone-label branch the power overlay exposed was missing;
                rowing_predict.py's recent_rower_pieces now also draws from confirmed pieces,
                not just real Concept2 results; session 18: training_intelligence.py (the
                DB-facing half of training intelligence — gather_training_profile/
                gather_performance_trends/gather_training_distribution/
                gather_training_consistency/gather_training_insights, and
                generate_recommendations, called once per recompute_scores run and scoped to
                today only — see docs/analytics.md §26); scoring.py's recompute_scores gained
                that one call, wrapped in its own try/except so a bug in this newer subsystem
                can't undo the DailyScore rows already committed above it
  analytics/    recovery/strain/load/zones/predict/technique — pure functions, no I/O;
                session 8/12: matching.py (sport_family/is_indoor/match_pair — the pure
                scoring half of cross-source matching), cycling_load.py (TSS-style power
                load + FTP estimate), samples_codec.py (pack/unpack the compact per-sample
                blobs), zones_samples.py (per-sample time-in-zone/Banister-TRIMP/session-
                label/auto-trim-detection — the real zones/strain fix for a session whose
                average HR undersells a short hard block inside a long easy one); session 13:
                nutrition.py (pure target/macro-scaling/under-fuelling math, no I/O);
                session 14: equipment.py (effective-load math per equipment type + the plate
                calculator, catch/seed/exercises.json's vocabulary — see docs/analytics.md
                §22), strength.py (Epley e1RM/PR detection, per-set muscular-load AU and its
                28-day-baseline normalization, a cardio session's small above-threshold-power
                muscular share); session 15: checkin.py (the subjective check-in's 0-100
                recovery sub-score + the separate "badness" figure the illness signal uses —
                §6.1), illness.py (the illness early-warning scoring rule — §23), erg_test.py
                (test-type auto-detect, pacing-plan generation, pacing analysis, trend
                projection — §24); session 16: wake_time.py (one pure function — a plain
                arithmetic mean over a trailing window of wake_time_minutes samples, the
                morning-brief notification's send-time baseline); session 17: piece.py
                (PIECE_TYPES, split template generation, validate_splits/
                aggregate_from_splits, the watts<->split formula, paste parsing, and
                find_best_window — the O(n) highest-average-HR window scan for auto-align —
                §25); zones_samples.py gained hr_recovery_drop, shared with the per-lap HR
                recovery routes_analytics.py already had; session 18:
                training_intelligence.py (pure — equivalence-bucket comparison over
                already-confirmed test_type/piece_type rows, reusing erg_test.py's
                project_time/TEST_SPECS directly rather than re-deriving a trend fitter or a
                tolerance-based bucketer; the confidence ladder; the four recommendation-type
                evaluators + their wording-by-confidence-tier hedging; the five fixed
                training_insights checks — §26)
  coach/        tools.py (the ONE shared tool registry — in-app coach, MCP server, and
                GET/POST /api/coach/tools all call catch.coach.tools.call_tool, never
                duplicated), chat.py (provider-neutral orchestration loop: tool-calling,
                SSE events, cost/cap accounting), memory.py (events/goals/athlete_facts
                CRUD + recall + the compact system-prompt memory block), settings.py
                (coach prefs + per-owner AI provider keys — session 23: `ai_credentials`, sealed by
                catch/core/secret_store.py; a separate table from `settings`), cost.py (usage -> $ from user-entered prices,
                incl. session 13's AiUsageEvent rows so photo-estimate spend counts against
                the same daily cap as chat), system_prompt.md (editable coach persona),
                providers/ (anthropic/openai/gemini/ollama adapters behind one interface — all yield the same
                normalized event stream; see the session 23 paragraph), nutrition_vision.py (session 13: one-shot Anthropic
                vision call for an itemised meal-photo macro estimate; lazy-imported, hidden
                when no Anthropic key is configured, photos never stored after the estimate);
                session 14: tools.py gained log_strength (free-text or structured, always
                previews before a confirm=true save)/get_strength/get_muscle_readiness;
                session 15: tools.py gained get_tests/get_test/make_pacing_plan (the last
                saves to the athlete's next upcoming event by default); get_today's existing
                payload (not a new tool) now also carries today's check-in/niggle flag and
                the illness early-warning level, and the per-turn memory block
                (memory.py::memory_block) surfaces both unprompted; session 17:
                piece_vision.py (one-shot Anthropic vision call reading a PM5 photo into a
                piece draft — every time value comes back as the screen's own display
                string, parsed server-side rather than trusted to the model's arithmetic;
                `_normalize_splits` handles two other real PM5 display shapes); tools.py
                gained add_piece (free text or structured splits, preview-then-confirm like
                merge_activities/log_strength); get_test's `id` param is now optional
                alongside a new `piece_id` param, since get_tests' rows carry a "kind" of
                "test" or "piece"; session 18: tools.py gained get_training_profile/
                get_performance_trends/get_training_distribution/get_training_consistency/
                get_training_insights/get_recommendations/rate_recommendation (the six reads
                delegate to routes_training_intelligence's handlers, same precedent as
                get_tests -> routes_tests.get_tests; rate_recommendation is the only write
                tool here, a direct mutation with no preview step); memory_block gained a
                line surfacing the single most severe *active* (not dismissed, confirmed as
                recently as yesterday) recommendation, same shape as the illness-level line
  notify/       session 16 (see PLAN.md Part A/B): push.py (Web Push from scratch —
                py-vapid + http-ece + httpx directly, not the full pywebpush package, which
                transitively pulls in requests+aiohttp for a .send() this app never calls;
                send_to_subscription/notify, round-trip tested against real decryption in
                tests/notify/test_push.py), triggers.py (the five notification types'
                trigger logic + the shared quiet-hours/type-toggle gate — see
                docs/notifications.md), ntfy.py (the optional second ops-alert channel)
  mcp_server/   server.py (MCPServer + all 55 tools + 3 prompts, built once, shared by both
                transports — session 18 added the 7 training-intelligence tools, hand-written
                @mcp.tool() wrappers matching coach/tools.py's TOOLS keys exactly, plus a
                training_review prompt; a parity test asserts the two sets match), backend.py
                (RestBackend for stdio -> HTTP with a device
                token; InProcessBackend for the /mcp mount, which dispatches straight into
                catch.coach.tools to avoid a same-process HTTP deadlock), __main__.py
                (catch-mcp stdio entry point), http_app.py (the /mcp/ mount + its bearer
                auth middleware)
  cli.py        argparse entry point (`uv run catch ...`, now incl. `token create`/`list`; session 22: `token create --role coach --display-name ...`)
  main.py       FastAPI app factory
  seed/         exercises.json (session 14: the gym logger's exercise library, seeded
                idempotently on startup by catch/core/db.py — yuhonas/free-exercise-db,
                Unlicense/public domain, vendored JSON only at build time, no images; lives
                outside catch/data/ deliberately, since the repo's gitignored `data/` rule is
                unanchored and would otherwise swallow a catch/data/ subdirectory too)
web/
  src/
    components/ ui/ (Card, Badge, Skeleton, …), today/ (RecoveryRing, StrainGauge, …),
                workouts/ (WorkoutRow, IntervalTable, ZoneTable, NotesBox, PbTable),
                charts/ (TrendLineChart, WeeklyVolumeBars, ErgChart, HrChart — session 8/12's
                per-sample HR graph on workout detail: zone-shaded bands, dashed max/avg HR,
                lap markers, the auto-trimmed tail greyed out (not absent — GET
                /api/activities/{id}/samples returns the full recording by default), a
                power/cadence overlay toggle — ChartNavigator — hand-rolled SVG, no chart
                library; lazy-loaded with the page that uses them; no
                on-chart zoom buttons — they covered data at 390px, see DESIGN.md's "On-chart
                zoom buttons removed" note; pan/pinch/press-hold run through the shared
                lib/useChartInteraction.ts hook against `touch-action: none` HTML wrapper divs,
                never the `<svg>` itself — WebKit's touch-action support on SVG root elements
                has real gaps, see DESIGN.md's "Chart touch-action" note; session 17: HrChart
                gained a pieceBands/selectedPieceId/onPieceDragEnd prop trio — a piece's
                window as a shaded accent-hue band, plus a drag handle (a sibling absolutely-
                positioned div, not inside the chart's own SVG, so it never fights
                useChartInteraction's own pointer claim on the surface) at its start edge —
                see DESIGN.md's "Adding a piece" note; session 18: PieceTrendMiniChart — a
                static best/typical/recent bar chart per equivalence bucket, SplitBarChart's
                dependency-free pattern rather than useChartInteraction, see DESIGN.md's
                "Training intelligence" note), shell/ (AppShell,
                Sidebar, BottomNav, UpdateToast — the "New version — tap to reload" banner),
                coach/ (Timeline, ToolCallChip, SuggestedPrompts, CoachSettingsCard),
                nutrition/ (session 13: AddFoodDialog — search/My-Foods/saved-meals quick
                picks/barcode-scan/manual-entry, one flow; BarcodeScanner — lazy-loaded,
                native BarcodeDetector or the self-hosted ZXing-wasm fallback via
                lib/barcodeScan.ts, stops every camera track on close; PhotoEstimateDialog —
                lazy-loaded, client-side ~1500px JPEG resize before upload, editable itemised
                estimate; MealSection, MacroBar, WeekView, NutritionTargetsCard),
                gym/ (session 14: ExerciseBlock — equipment config + set logging + last-
                session-inline numbers in one card; ExercisePicker, Stepper — the shared
                reps/load input with plate-sensible increments per equipment, see
                lib/equipment.ts; RestTimer — auto-starts, computed from a stored end
                timestamp rather than accumulated setInterval ticks since a backgrounded PWA
                suspends JS timers, Web Audio beep since iOS Safari has no navigator.vibrate;
                PlateCalculatorDialog; MuscleBodyMap — a schematic (not anatomical) front/
                back SVG, see DESIGN.md's "Muscle readiness body map" note; SyncStatusBadge);
                session 15: CheckinSheet (a bottom-sheet-on-mobile/centered-on-desktop Radix
                Dialog, 4 sliders + niggle area/severity + note; prefilled from GET /api/
                checkins/today so reopening it later the same day edits, never blanks; see
                DESIGN.md's "Dialogs that reach the bottom nav need z-30" note), IllnessCard
                (the fixed-wording explanation + signals list + a dismiss-with-reason row,
                shown only when illness.level !== "none"); settings/IllnessBacktestCard (the
                flagged-nights list + correct/wrong marks + precision, task Part B.4); tests/
                (PacingPlanDialog — goal-time/style/test-type form, saves to the next event by
                default; SplitBarChart — a small static actual-vs-target-per-500m bar chart,
                deliberately not built on ErgChart's pan/zoom machinery, see DESIGN.md);
                session 16: settings/NotificationsCard (enable/disable push on this device,
                per-device list + test-send, per-type toggles, quiet hours — detects "iOS
                Safari, not installed to home screen" and says so rather than showing a
                button that can't work there);
                pieces/ (session 17: AddPieceDialog — one dialog, a branching first step
                (an activity picker, only when opened from the test center) then photo-or-
                typed entry, both ending at the same SplitsReviewTable; TimeInput — the
                m:ss.t digit-entry field, since iOS's numeric keyboard has no colon, see
                DESIGN.md; SplitsReviewTable — shared by AddPieceDialog and PieceCard's own
                edit mode, highlights exactly the rows validate_splits flagged; PieceCard —
                a piece's summary on workout detail: splits, edit, delete, view/delete photo);
                intelligence/ (session 18: TrainingProfileCard, PerformanceTrendsCard,
                TrainingDistributionCard, ConsistencyCard, StrengthsWeaknessesCard,
                InsightCard, RecommendationCard — each a plain Card + useQuery section on
                TrainingIntelligence.tsx, confidence rendered as plain text rather than a
                colored badge, see DESIGN.md's "Training intelligence" note)
    lib/        api.ts (fetch + mock switch; streamMessage() parses the coach's SSE body by
                hand since EventSource can't POST), types.ts (hand-kept in sync with the
                API — no codegen), mock.ts (?mock=1/calibrating/empty/error/loading/offline
                fixtures, incl. a scripted streamMockMessage() turn), format.ts, auth.tsx,
                theme.tsx, zoneColors.ts/hrZone.ts (zone color ramp + a small TS port of
                catch/analytics/zones.py's zone_for_hr for client-side chart coloring),
                dateRanges.ts (Trends' 4w/12w/season/all -> from/to), chartRange.ts (preset <->
                URL querystring helpers), useChartInteraction.ts (the shared pan/pinch/press-hold
                gesture engine every chart uses), useOnlineStatus.ts (the Today offline banner's
                only signal — an actual /api/health probe, never navigator.onLine or a cached-
                response heuristic; see session 10's PLAN.md notes), useServiceWorkerUpdate.ts
                (registers sw.js for its caching behavior, but drives the update toast off a
                separate version.json poll — deliberately not off the service worker's own
                install/waiting/controllerchange timing, which a session 10 bug report showed
                isn't reliable enough on a real iOS PWA to be the only signal), timeline.ts
                (merges a conversation's tool_call/tool_result block pairs — stored on two
                separate message rows — into one display entry), toolLabels.ts (mirrors
                catch/coach/chat.py's chip-label templates for persisted history),
                barcodeScan.ts (session 13: createBarcodeDetector() — native
                window.BarcodeDetector when present, else the self-hosted ZXing-wasm ponyfill;
                one detect() shape either way); session 14: equipment.ts (a TS port of
                catch/analytics/equipment.py's effective-load math + the plate calculator —
                duplicated, not shared, so the offline logger can preview a real effective
                load with zero network; keep in sync by hand), gymDb.ts (hand-rolled raw
                IndexedDB, no wrapper library — one `sets` object store, dirty/deleted
                flags, keyed on each set's client-generated UUID), gymSync.ts (the offline
                queue's flush: idempotent upsert to POST /api/gym/sessions/sync, never
                required for a local write to "succeed" — library/gyms/templates/readiness
                reads need no bespoke IndexedDB mirror of their own, since every GET under
                /api/* already gets network-first-with-cache-fallback from the service
                worker itself), useGymSync.ts (wires useOnlineStatus — never
                navigator.onLine — plus the browser's own `online` event and
                visibilitychange to the flush, each a real trigger on its own: the
                online-status hook's 15s-interval probe can go a whole short reconnect
                window without ever toggling, so the plain `online` event is load-bearing,
                not just belt-and-suspenders, confirmed by web/tests/gym-offline/); session
                15: api.ts/mock.ts gained check-in/illness/erg-test-center functions
                (confirmTest reuses patchActivity, no new endpoint); types.ts gained
                CheckIn/TodayCheckin/IllnessState/ErgTestDetail/PacingPlan/ProjectionResult
                etc., plus `test_type` on ActivityOverrides/WorkoutListItem (a confirmed test
                is just a tagged CanonicalActivity — see catch/sync/erg_test.py); session 16:
                push.ts (subscribe/unsubscribe, the iOS-installed-PWA detection heuristic,
                enablePush()'s Notification.requestPermission()-first-in-the-tap-handler
                ordering — see docs/notifications.md); api.ts/mock.ts/types.ts gained the
                push-subscription/status functions and AppStatus/PushSubscriptionRow types;
                format.ts gained formatBytes/formatUptime; session 17: pieceSplits.ts (a TS
                port of catch/analytics/piece.py's pure functions — PIECE_TYPES, split
                templates, validate_splits/aggregate_from_splits, the watts<->split formula,
                paste parsing — same "duplicated, not shared" precedent as equipment.ts, for
                live validation with zero network; its paste parser shares a test-vector
                fixture, tests/fixtures/pieces/paste_vectors.json, with the Python one so
                they can't silently drift), image.ts (resizeImage(), pulled out of
                PhotoEstimateDialog so AddPieceDialog's photo tab can reuse the same ~1500px
                JPEG downscale); api.ts/mock.ts/types.ts gained the piece CRUD/photo-
                estimate/align functions and Piece/PieceSplitRow/PieceTestDetail/
                PiecePhotoEstimate types; ErgTestSummary and PbEntry both gained a
                `kind`/`piece_id` (PbEntry: just `piece_id`) so a row can resolve to either a
                confirmed test's or a piece's own detail route; session 18: api.ts/mock.ts/
                types.ts gained fetchTrainingProfile/fetchPerformanceTrends/
                fetchTrainingDistribution/fetchTrainingConsistency/fetchTrainingInsights/
                fetchRecommendations/dismissRecommendation/saveRecommendation/
                rateRecommendation and TrainingProfile/PerformanceTrends/
                TrainingDistribution/TrainingConsistency/TrainingInsight/Recommendation types
    pages/      Today.tsx (eager); Workouts (session 8/12: a Select mode for bulk retype/
                tag/exclude-from-totals, links to Duplicates), Duplicates (the flagged-
                possible-duplicate-pairs review screen, merge/not-duplicate actions),
                WorkoutDetail (inline title/sport/tags/RPE/exclude editing with
                revert-to-source, a per-metric field-source panel, the HrChart), Trends,
                Body (session 8/12: per-day resolved weight/fat%/muscle with its source,
                a manual-weight-entry form), Nutrition (session 13: day/week toggle, macro
                bars vs. targets, per-meal quick-add/copy-yesterday/edit/delete, barcode scan
                and photo-estimate entry points), Coach, Settings, Memory, Gym (session 14:
                hub + active-workout logging in one page — resumes today's IndexedDB session
                on mount, offline-first; reads the exercise library/gyms/templates/repeat-
                last-workout over the network as usual, mock-gated like every other page),
                MuscleReadiness (session 14: the 72h front/back body map + list); session 15:
                TestCenter (`/tests` — candidates to confirm, PbTable reused as-is for PBs per
                type, confirmed-tests list with a type filter, the projection line, "Build
                pacing plan" entry point; no bottom-nav slot — reached via the Sidebar on
                desktop and a Workouts-header link on mobile, same pattern Duplicates/
                MuscleReadiness already use), TestDetail (`/tests/:id` — pacing chart +
                segment/even-split/worst-split numbers, compare-to-earlier, w/kg; links out to
                the real workout-detail page for the full ErgChart/HrChart pan-zoom
                experience rather than duplicating it); session 16: Status (`/settings/
                status` — per-source sync health, Garmin key expiry, backup status, disk/DB
                size, uptime, build; its own route rather than a Settings card specifically
                so the sync_broken/garmin_key_expiring push notifications' deep links have
                somewhere operational to point at — no bottom-nav slot, same
                Duplicates/Tests pattern, reached via a "Status" link on Settings' Connected
                sources card); session 17: WorkoutDetail gained a "Pieces" card (list +
                "Add piece" + per-piece selection, wired to HrChart's new drag handle) and
                TestCenter gained an "Add piece" entry point (AddPieceDialog with its
                activity-picker first step) plus a "piece" badge on piece rows in the
                confirmed-tests list; PieceTestDetail (`/tests/piece/:id` — the piece
                equivalent of TestDetail, a separate route since a piece's own canonical_id
                is the *containing* activity; pacing chart + the embedded PieceCard for
                edit/delete/photo); session 18: TrainingIntelligence (`/trends/intelligence`
                — profile, performance trajectory, distribution, consistency, strengths/areas
                to investigate, insights, recommendations, each its own Card + useQuery; no
                bottom-nav/Sidebar slot — reached via a link on Trends' own header, same
                no-slot pattern as Tests/MuscleReadiness/Duplicates/Status) (React.lazy,
                one chunk per route — keeps the initial bundle under budget)
    styles/     tokens.css — design tokens as CSS vars, see /DESIGN.md
  public/       manifest.webmanifest, icons/ (generated, see /DESIGN.md); sw.js is NOT
                here — vite.config.ts's serviceWorkerPlugin writes it at build time with
                the real hashed asset list, so it can't be a static passthrough file;
                session 16: that same generated sw.js gained push/notificationclick
                handlers (see docs/notifications.md), syntax-checked in CI/`make check`
                via `node --check` since nothing else exercises the template string
tests/          fixtures/ has recorded JSON; no live network calls in the suite; notify/ has
                the Web Push round-trip (real encrypt-then-decrypt against a fake browser
                keypair, not just a mocked HTTP call) and the five trigger types' gating
                logic (session 16); coach/ has
                the tool-layer, chat-loop, and provider tests (Anthropic client mocked,
                Ollama mocked via httpx.MockTransport), plus (session 17) piece_vision.py's
                fake-anthropic-module tests (screen-shape normalization, server-side
                validation); test_piece_sync.py/test_piece_test_center.py/test_api_pieces.py
                (session 17) cover the alignment fixture, the Part D.3 strain-unchanged
                guarantee, and the Part D.4 absorb (a fixture with real Stroke rows,
                asserting the parent canonical's duration/strain survive untouched — the
                exact bug a second advisor review caught); test_api_training_intelligence.py/
                tests/analytics/test_training_intelligence.py (session 18) cover the
                recommendation dedup/cooldown/staleness semantics, the four evaluators'
                suppression rules, the structural "confidence never exceeds the weakest
                input, insufficient_data only ever comes from a data-quality warning"
                guarantees, and an MCP/coach-tool-registry parity check. `web/` has its own test trees:
                `web/src/**/*.test.ts` (Vitest, pure-function unit tests, e.g. chartRange.ts,
                and session 17's pieceSplits.test.ts, which also runs the shared
                tests/fixtures/pieces/paste_vectors.json vectors) and
                `web/tests/touch/` (Playwright, real touch-device gesture regression tests —
                `playwright.config.ts` runs a Chromium+iPhone-profile project driven via CDP
                multi-touch, since Playwright's own WebKit bindings only support a single tap
                with no move/multi-touch; a real-WebKit project covers what a tap alone can
                verify, e.g. computed `touch-action`; session 16 added a third project,
                `desktop-mouse` — plain Chromium, no touch emulation, scoped via testMatch to
                its own mouse.spec.ts — covering ctrl/cmd+wheel zoom and mouse drag-to-pan,
                which the CDP-touch suite can't exercise; CI/`make check` run this suite
                against a real production build via `vite preview`, not the dev server, set
                by `CI=1`) and `web/tests/update/` (Playwright,
                `playwright.update.config.ts` — builds two real production bundles with distinct
                `CATCH_BUILD_ID`s, serves one then the other from an in-process swappable static
                server (server.mjs, not catch.main — booting the real app starts APScheduler
                against the real .env) to confirm a client on build A actually detects and
                reloads to build B, plus the offline-banner scenarios) and `web/tests/
                gym-offline/` (session 14, `playwright.gym.config.ts` — the one Playwright
                suite that *does* boot the real `catch.main` app, via a `webServer` entry:
                `uv run uvicorn` against a disposable scratch DB + freshly generated secrets
                (never the real `.env`/`data/catch.db`, same precedent as every prior
                session's by-hand disposable-instance checks, just automated here), a real
                registered service worker, and real IndexedDB — logs a full workout with
                `context.setOffline(true)`, reloads mid-offline to confirm nothing is lost,
                reconnects, and asserts the synced result directly against the backend. The
                substitute for "use the logger on my phone with airplane mode on," which this
                environment has no real iPhone to do live)
docs/           garmin-endpoints.md, withings-endpoints.md, garmin-openapi.json,
                analytics.md, mcp.md (Claude Desktop config, device tokens, Inspector),
                peloton.md (session 8/12: Peloton-push detection mechanism + live findings —
                no Peloton-pushed activity exists in this account yet to confirm it against),
                nutrition-endpoints.md (session 13: Open Food Facts v2 + USDA FoodData
                Central API facts — rate limits, field shapes, OFF's legacy free-text search
                endpoint and why it's opt-in (`include_off`) rather than part of the
                debounced as-you-type search box), notifications.md (session 16: the five
                push notification types' exact trigger/dedup/deep-link rules, the Web Push
                implementation, GET /api/status's fields, the off-Pi backup design);
                analytics.md §25 (session 17): piece validation/alignment/strain-refinement/
                Part D.4 absorb — see that section for the full writeup
DESIGN.md       palette/type/motion decisions for the web frontend
```

Session 19 (intervals within a piece — see PLAN.md, docs/analytics.md §27, DESIGN.md): a piece
can be made of `piece_intervals` rows (`PieceInterval` in core/models.py; `Piece.has_intervals`
flags it). Pure math/validation/"4 x 500m" expansion/signatures live only in
`catch/analytics/piece_intervals.py`; the DB layer is `catch/sync/piece_intervals.py` (in-place
id-stable updates, parent totals re-derived on every mutation, on-demand Concept2 import from
`workout.intervals`); routes are in `routes_pieces.py`, comparisons in
`routes_training_intelligence.py`/`gather_interval_comparisons`, coach `get_interval_comparisons`
+ `add_piece` `repeat`/`intervals`. Interval pieces are excluded from every single-effort reader
(`has_intervals` filter: test rows, PBs, 2k predict, fast-start, Concept2 absorb) and never
change the parent's strain. Web: `components/pieces/IntervalEditor.tsx` (stacked rows),
`PieceIntervalTable.tsx`, `components/intelligence/IntervalComparisonCard.tsx`; the browser holds
no interval math, the server returns every total. Playwright: `web/tests/touch/intervals.spec.ts`.

Session 20 (GPS, on-water metrics, routes, weather — see PLAN.md, docs/analytics.md §28,
docs/weather-endpoints.md, DESIGN.md "Maps, GPS and weather"): a separate streaming FIT pass
(`parse_fit_track` in `sync/fit_parse.py`; `parse_fit`/HR/strain untouched) stores each activity's
GPS fixes in `activity_tracks` (`sync/tracks.py`; delta-coded int32 + zlib blobs, filtering at *read*
time). Pure math only in `analytics/gps.py` (filter, distance/moving/peak speed, splits, laps),
`analytics/routes.py` (signature, alignment, history stats) and `analytics/weather.py` (per-variable hour
semantics, UTC-only matching); DB layers are `sync/routes.py` (a route forms only when a second session
aligns; rowing only), `sync/weather.py` + `sync/weather_client.py` (Open-Meteo archive, one cached
`weather_cells` row per 0.1° cell per UTC day, coordinates rounded before sending, generic User-Agent),
`api/routes_gps.py` (REST + the `build_*` functions the coach tools call). Coach/MCP gained
`get_route` (area + summary, **never coordinates**), `get_route_history`, `get_on_water_metrics`,
`get_workout_weather` (40 tools; 47 after session 21). Every figure is labelled `gps_derived`/`provider`/`manual`; nothing
is wind-/current-corrected. `Activity.sport_family` is NULL on rows older than that column — always go
through `sync/tracks.py::family_of`. Web: `components/gps/` (GpsSection composes the cards),
`components/maps/` (Leaflet in a lazy chunk; two-finger-only touch pan, ctrl/cmd+wheel zoom),
`pages/Routes.tsx`/`RouteDetail.tsx`, `lib/mockGps.ts` (mock ids 1/6/11/16 = full/partial weather/no weather/no GPS).
Playwright: `web/tests/touch/route-map.spec.ts`, `route-map-desktop.spec.ts`.

Session 21 (calendar, race planning, periodization — see PLAN.md, docs/calendar.md, docs/analytics.md §29,
DESIGN.md "Calendar, plans and events"; the brief called itself "session 16"): `PlannedWorkout` and
`TrainingPhase` in core/models.py (new tables, `owner_id` on each; `events` gained location/goals/notes/
distance_m/owner_id). **A plan is never a completed workout**: its own table, no Activity/Canonical row is
ever created from it, linking sets only `linked_canonical_id` (unique, one-to-one), and no completed-total
reader may import it (tested). Pure math (recurrence, matching, planned totals, phase lookup, review flags) is
`catch/analytics/planning.py`; the DB layer — owner-filtered CRUD, link/unlink/skip, the calendar and
week-summary assemblers, events, phases/approval, race projection, the write-tool previews — is
`catch/sync/planning.py`; routes `catch/api/routes_calendar.py` (`/api/calendar`, `/api/planned`, `/api/events`,
`/api/phases`; `/api/planned/{id}` lives in its own namespace so it can't shadow `/api/calendar/week-summary`).
Time zones: the pure helpers take an explicit `tz`; the DB layer uses the host zone like the rest of the app (no
`timezone` setting — see docs/calendar.md). Coach/MCP: 47 tools; `add_event` was replaced by confirm-gated
`create_event`, and `create_planned_workout`/`update_planned_workout`/`delete_planned_workout`/`update_event`/
`forget("event:N")` all preview unless `confirm=true` (one `_gate` code path, not hard enforcement); reads are
`get_calendar`/`get_upcoming_events`/`get_event`/`get_training_phase`. `_migrate_columns` now uses
`sqlalchemy.inspect()` (dialect-neutral). Web: bottom-nav slot "Plan" (was "Log") → `pages/Calendar.tsx`
(week/day/month), `EventDetail.tsx` (`/calendar/events/:id`, the notification deep link), `Plan.tsx`
(`/calendar/plan`, phases + weekly bars), `components/calendar/`, `components/today/UpcomingEventsCard.tsx`,
`lib/dates.ts` (local-date math, Monday weeks), `lib/mockCalendar.ts`. Playwright: `web/tests/touch/calendar.spec.ts`.

Session 22 (workout library, technique notes, coach feedback — see PLAN.md, docs/library.md, DESIGN.md "Library, technique
notes and coaching feedback"; the brief called itself "session 17"): `WorkoutTemplate`, `TechniqueNote`, `CoachFeedback`,
`CoachFeedbackRevision` in core/models.py (new tables; `api_tokens` gained nullable `role`/`display_name`,
`planned_workouts` gained `template_id`). **There are still no user accounts**: `catch/core/principal.py` derives a
*principal* per request (cookie / role-less token = athlete, `role="coach"` token = coach, unknown = the fail-closed
`viewer`) and holds every visibility/ownership rule (`note_visible`, `feedback_visible`, `can_edit_feedback`,
`can_respond_to_feedback`, `may_call_tool`). A coach token reaches only five tools (enforced in `call_tool`, and
`require_tool_auth` refuses coach tokens unless a route opts in via `require_tool_auth_allow_coach` — only the two tool
endpoints and the `/mcp` mount do); the `/api/library`, `/api/technique-notes`, `/api/coach-feedback` routes are
cookie-only (no coach web UI). New tool handlers read `principal_from(ctx)` and **fail closed** without one; transports
set it (REST from auth, `/mcp` via a contextvar set per request in `http_app.py`, `chat.py` = athlete). Pure math is
`analytics/workout_library.py` (validation, `summarize_template`: rest after every rep but the last, a duration/distance
only when knowable with `duration_basis`, `to_planned_fields`); DB layers are `sync/workout_library.py` (CRUD,
duplicate/archive, `schedule_template` = a snapshot copy through `planning.create_planned` + `template_id`, idempotent
example seed from `catch/seed/workout_templates.json`) and `sync/coaching_notes.py` (notes, feedback, per-revision
history filtering, soft delete, and the stale-reference hooks: `repoint_canonical` from `_merge_canonicals`,
`detach_event`/`detach_planned`/`detach_piece`). Technique notes have **no rating/score field and nothing infers
technique quality** (Catch's data can't measure it). Coach/MCP: 55 tools (`coach/library_tools.py`, merged into
`TOOLS`; every write previews unless `confirm === true`). Routes: `api/routes_library.py`, `api/routes_coaching.py`
(`/preview`, `/coaches` registered before `/{id}`). Web: `pages/Library.tsx`, `LibraryTemplate.tsx`, `LibraryEditor.tsx`,
`Feedback.tsx`; `components/library/` (BlockEditor, StructureView, SummaryPanel, ScheduleSheet — **the browser holds no
interval math**, the editor asks `POST /api/library/templates/preview`), `components/coaching/` (PrivacyBadge,
TechniqueNotesCard on WorkoutDetail, FeedbackEntryCard, sheets), `lib/duration.ts` (text↔seconds only),
`lib/mockLibrary.ts`/`mockCoaching.ts`; the Settings device-token form can mint a coach token. Playwright:
`web/tests/touch/library.spec.ts` (both mobile projects) and `library-desktop.spec.ts` (desktop-mouse). Postgres: the
new services were run against a real PostgreSQL 18 via `tests/test_postgres_optional.py` (skipped unless
`CATCH_TEST_PG_URL`).

Session 23 (Whoop, provider-independent recovery, BYOK AI providers — see PLAN.md, docs/whoop-endpoints.md,
docs/ai-providers.md, docs/security.md, docs/analytics.md §6.2/§30, DESIGN.md "AI providers, Whoop and recovery inputs"; the
brief carried no number). **Whoop**: `sync/whoop_client.py` (OAuth with *rotating* refresh tokens behind a lock, `records`/
`next_token` pagination, 429 handling, revoke on disconnect), `analytics/whoop.py` (pure: offsets, the wake-day rule, sport
families), routes in `routes_auth.py` (`/auth/whoop/start|callback|disconnect`, `GET /api/whoop/test`), `catch whoop check`,
source registered in `scheduler.SOURCES` (a not-connected Whoop is skipped silently — no attempt, no alert) and explicit
`cli.py` branches. Only `SCORED` records import; Whoop's own recovery/strain are reference, never inputs. **Recovery inputs**:
every provider records `wellness_readings(date, source, signal)`; `sync/wellness_readings.py::resolve_days` is the *only*
writer of the signal columns of `daily_wellness` (hrv, resting HR, sleep + stages + wake time, sleep respiration, skin temp,
SpO₂), one winner per signal per day, never averaged, order from `Settings.wellness_priority` (Garmin first by default);
`analytics/wellness_inputs.py` holds the pure rules, `RecoveryInputs`, `recovery_from_inputs` (the formula in `recovery.py` is
unchanged) and the availability/calibration report; Garmin's `sync_health` records readings and resolves the days it touched;
`daily_wellness` gained `skin_temp_c`/`field_sources_json`; recovery/illness payloads gained `calibration`,
`data_availability`, `baseline_mixed_sources`. **BYOK**: `core/secret_store.py` (AES-256-GCM, per-owner HKDF key, AAD =
owner|provider; master = `CATCH_SECRETS_MASTER_KEY`, Pi falls back to `CATCH_FERNET_KEY`), `core/redact.py` (applied to provider
errors, stored tool errors, sync errors and every log record), `core/owner.py::current_owner_id` (the ONE owner dependency —
credentials, coach settings, conversations, AI usage, rate limits all filter by it; `"owner"` on the Pi). `coach/providers/`:
`base.py` (capabilities, `ProviderError` with a fixed `kind` vocabulary, `VisionRequest`), `anthropic_provider.py`,
`openai_provider.py` (Responses API), `gemini_provider.py` (key in a header), `ollama_provider.py` (off on a public deployment: `CATCH_OLLAMA_ENABLED=0`), `registry.py`
(`build_provider` is the only place a key is decrypted; no env fallback; `normalize_tool_ids` in `base.py` makes stored synthetic call ids unique before any provider sees them), `model_catalog.json` (patterns only). `coach/limits.py`
(per-owner rate/concurrency/length/history-trim/wall-clock), `coach/vision.py` (the shared photo path; `nutrition_vision.py` and
`piece_vision.py` are now async and provider-neutral). A hosted model with no entered price has *unknown* cost (`None`), not
$0; a per-owner daily token cap exists beside the USD cap. API: `routes_ai.py` (`/api/ai/providers|…/key|…/test|…/models|active|
usage`, cookie-only); the old `/api/coach/key` stays as an alias. Tools/MCP: still 55, none touch credentials. Web:
`pages/AiProviders.tsx` (`/settings/ai`), `components/settings/ProviderCard|ProviderKeySheet|WhoopControls|RecoveryInputsCard`,
`lib/aiProviders.ts`, `lib/mockAi.ts`, `lib/useVisionAvailable.ts`; `RecoveryRing`'s dialog lists each input's provider.
Playwright: `web/tests/touch/ai-providers.spec.ts` (both mobile projects) and `ai-providers-desktop.spec.ts`. Adapters and the
Whoop flow are verified against *synthetic* fixtures only (`tests/fixtures/ai`, `tests/fixtures/whoop`) — never run live.

Session 24 (public deployment: Supabase + FastAPI Cloud, multi-user accounts — see PLAN.md, docs/public-architecture.md,
public-setup.md, public-storage.md, personal-to-public.md, DESIGN.md "Accounts on the public build"; the brief called itself "session
19"). **Two deployments from one codebase, sharing nothing**: `CATCH_DEPLOYMENT=personal` (default — the Pi, SQLite, one owner `"owner"`,
cookie login, APScheduler) and `public` (Supabase Postgres + Supabase Auth, many users, no in-process scheduler, no local files).
**Every user-owned table has `owner_id`** (TEXT, FK → `user_profiles.id` ON DELETE CASCADE; 48 owned + 3 shared-reference tables + `weather_cells`/`user_profiles`
global). `catch/core/tenant.py` is the one owner mechanism: a request-scoped ContextVar (personal default `"owner"`; **public default none — touching an owned
table raises**), the `OwnedStrict`/`OwnedOrShared` markers, `owner_field()`, `tenant.pk(...)` for `session.get` on tables keyed `(owner_id, …)`. `core/tenant_hooks.py`
(installed on SQLAlchemy's `Session` by importing `core/models.py`): `do_orm_execute` adds `owner_id = :owner` to every ORM SELECT/UPDATE/DELETE (incl.
`session.get`), `before_flush` stamps/verifies the owner and — public only — resolves every cross-row reference *for this owner* (404 not 403), `after_begin` runs
`SET LOCAL ROLE authenticated` + `set_config('request.jwt.claims'/'request.jwt.claim.sub', …, true)` + `search_path` **per transaction** on the engine flagged
`catch_rls`. Raw SQL is banned outside the reviewed modules (a test enforces it). **Public auth**: `core/supabase_auth.py` (PyJWT, lazy: ES256/RS256 only, JWKS cache
≤ 5 min, iss/aud/exp/role/sub/session_id required, then `catch_private.session_is_live` against `auth.sessions` so logout/deletion revoke an unexpired token within
`CATCH_SESSION_CHECK_TTL`); `api/deps.py::require_auth` is now **async** and sets the tenant in the request's own task (a sync dependency runs in a thread copy of
the context and would lose it); `core/device_tokens.py` resolves MCP/coach tokens to their minting user through a SECURITY DEFINER function; `Principal.owner_id`.
**Database**: `migrations/` (Alembic, public only — the Pi keeps `core/db.py`'s `_NEW_COLUMNS`): `0001` frozen DDL snapshot (`scripts/gen_pg_baseline.py`), `0002` roles
(`catch_api`: NOBYPASSRLS, only `SET ROLE authenticated`), forced RLS + 4 policies per table, composite tenant FKs, `catch_private` functions, `auth.users` triggers,
`0003` the private `piece-photos` bucket; Catch's tables are in a non-exposed `catch` schema. `core/db_pg.py` (psycopg3, `sslmode=require`, session or transaction pooler
mode, startup refusal of a role that bypasses RLS). `catch db upgrade|check|seed`, `catch export-personal`/`import-personal` (`sync/personal_transfer.py`).
`api/routes_account.py` (`GET /api/me`, `DELETE /api/account`: Storage purge → GoTrue admin delete with the secret key → cascade), `api/routes_internal.py` (`/internal/tick/{sync,
notifications}` with a per-user lease, `/internal/db-check`), `api/security_headers.py` (CSP by hash, HSTS…). Public mode: cookie login and the source OAuth redirects answer 404,
Garmin/Concept2 (one server-wide credential) are skipped. **Web**: `lib/deployment.ts` (build-time flag; a personal build contains no auth-js — the check is inline in `lib/supabase.ts` so the
bundler can drop it), `lib/supabase.ts` (`@supabase/auth-js`, PKCE, localStorage session — see the comment for the tradeoff), `lib/authedFetch.ts` (bearer, one refresh+retry on 401),
`lib/session.ts` (sign-out/user-switch wipe), `pages/Login.tsx` variants, `components/settings/AccountCard.tsx`; Playwright: `npm run test:public`. **Tests**: `tests/tenancy/` (SQLite, public
mode patched: generic isolation for every owned table, JWT attacks, API isolation, structure, transfer, CSP), `tests/pg/` (needs a throwaway local `supabase start` + `CATCH_TEST_SUPABASE_*`:
migrations, RLS with separate identities, Storage, GoTrue, the app on the real runtime path, a Supavisor transaction pooler), `CATCH_TEST_PG_URL=… uv run pytest` runs the **whole** suite on PostgreSQL
(foreign keys dropped there — the suite uses placeholder ids; `sqlite_engine` fixture for tests that reshape the schema). Public deps are the optional `public` extra (psycopg-binary has no 32-bit
ARM wheel): `uv sync --extra public` (CI/Makefile use `--all-extras --all-groups`); the Pi's `uv sync` never installs them.

## Commands

- `uv sync` — install deps
- `uv run catch sync --source garmin --days 30` — sync one source
- `uv run catch backfill` — backfill `BACKFILL_DAYS` from `.env`
- `uv run catch backfill-gps [--weather] [--force]` — parse GPS tracks from FIT files already on disk
  (the sync loop only reaches its window), group rowing tracks into routes, and with `--weather` look
  up weather (sends 0.1°-rounded coordinates to Open-Meteo)
- `uv run catch whoop check` — manual Whoop connection test (counts only; needs `WHOOP_*` in `.env`)
- `uv run catch db upgrade` / `db check` / `db seed` — public deployment only (`DATABASE_ADMIN_URL` for upgrade/seed; `check` over the runtime
  connection); `uv run catch export-personal --out f.jsonl.gz` (on the Pi) and `import-personal --file f --user-id <uuid> [--dry-run]` — docs/personal-to-public.md
- `cd web && npm run test:public` — Playwright against the public build (dev server with `VITE_CATCH_DEPLOYMENT=public`; Supabase and `/api` calls intercepted)
- `uv run catch token create --name <device> [--role coach --display-name "Coach Sam"]` — mint a device bearer token for the MCP
  server (prints it once; see `docs/mcp.md`)
- `uv run uvicorn catch.main:app --reload --port $CATCH_PORT` — dev server (port comes from `.env`)
- `uv run pytest` — tests (fixtures only, never hits live APIs)
- `uv run catch-mcp` — MCP stdio server for Claude Desktop (needs `CATCH_BASE_URL` +
  `CATCH_MCP_TOKEN` env vars; see `docs/mcp.md`)
- `cd web && npm install` — install frontend deps
- `cd web && npm run dev` — Vite dev server, proxies `/api` and `/auth` to the FastAPI port
  from `.env`; append `?mock=1` (or `?mock=calibrating|empty|error|loading|offline`) to run the
  UI against fixtures with no backend at all
- `cd web && npm run build` — builds to `catch/api/static`, which FastAPI serves at `/`
  (gitignored; not committed — the Pi has no Node, so the build must run elsewhere and the
  `catch/api/static` output deployed alongside the backend)
- `cd web && npm run test` — Vitest (pure-function unit tests only)
- `cd web && npm run test:touch` — Playwright real-touch-device gesture regression tests
  (installs its own Chromium/WebKit via `npx playwright install` the first time; starts its own
  dev server on port 5190, no backend needed since it runs against `?mock=1`)
- `cd web && npm run test:update` — Playwright service-worker update + offline-banner tests;
  builds two real production bundles itself (no `.env`/backend needed) and serves them from its
  own swappable static server on port 5192
- `cd web && npm run test:gym` — Playwright offline gym-logger test; builds the real frontend
  into `catch/api/static` and boots a real disposable `uv run uvicorn` backend (scratch DB +
  generated secrets, port 8731) via Playwright's `webServer`, needs `uv` on PATH but no running
  `.env`-backed instance of its own
- `./deploy.sh` — build the frontend + rsync the backend to the Pi + restart + health-check
  (needs `deploy/pi-bootstrap.sh` to have been run on the Pi at least once; see that file)

## Conventions

- Upserts are idempotent, keyed on `(source, external_id)` (or `date` for the single-source
  `daily_wellness` aggregate). Never duplicate a row on re-sync.
- Garmin: **only** endpoints verified in `docs/garmin-openapi.json` / `garmin-endpoints.md`.
  Never invent an endpoint or response field. Task fields Garmin doesn't expose stay `NULL`
  and are noted in `docs/garmin-endpoints.md`, not silently dropped.
- Withings: current docs require HMAC-signed `requesttoken` calls — see
  `docs/withings-endpoints.md` before touching `sync/withings_client.py`.
- Stream downloads (FIT zips) and page through history — never load years of data into RAM.
  This box has 1GB total, shared with PiAware.
- No comments explaining *what* code does. Only *why*, for non-obvious Garmin/Withings field
  mappings or Pi-memory tradeoffs.

## Pi 3 limits

- 1GB RAM shared with PiAware — keep per-request memory bounded, stream large responses.
- ARM — avoid deps that need compiling heavy C extensions; prefer pure-Python or wheels with
  ARM builds already on PyPI.
- Single uvicorn worker — more than one means duplicate APScheduler jobs.

## Secrets

Everything sensitive lives in `.env` (gitignored) — on the public deployment, in FastAPI Cloud's secrets (never `DATABASE_ADMIN_URL`, never in the frontend; only the publishable key
is public). `.env.example` documents every key with
no real values. Never commit `.env`, the SQLite DB, or downloaded FIT files. Never print env
values to logs or chat — key *names* only when debugging.
