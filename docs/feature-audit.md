# Feature audit and gap plan (session 36)

Taken before any session-36 work, by reading the code (not the docs). Status words: **Complete** (working as intended),
**Incomplete** (works, missing a part the brief asks for), **Broken** (a real defect), **Missing**, **UX** (functionally complete,
the screen needs work). Every gap below was built this session unless it is listed under "Still open" at the end.

| Feature | Before | What was wrong or missing | What session 36 did |
|---|---|---|---|
| Training calendar | Complete + UX | No monthly totals; a workout linked to a plan on the next/previous day was missing under the plan (broken display); no way to link a workout the matcher didn't suggest | Month summary strip; the plan carries its linked workout; "Link a workout…" picker (±3 days) |
| Planned workouts | Incomplete | Structure was reps/time/distance/zone only; **scheduling a template dropped its split/watts targets** (rate became a hidden note, warm-up/cool-down went into the description); no planned-vs-done; clearing a title returned 500 | Blocks carry `kind` and split/watts/rate/HR targets; templates copy every target; `plan_compare` + "Planned and done" on the sheet and the workout; a cleared title falls back to the type's name |
| Workout builder / templates | Incomplete + broken | No HR targets; split assumed /500 m and bike watts used the rowing formula; the editor dropped distance or zoned warm-ups; **examples invisible on the public build**; archived examples in no tab | HR targets; split per 500 m rowed / 1000 m bike, no pace→watts on a bike; full warm-up/cool-down editor; shared examples readable (not archivable); Archived tab includes examples |
| Intervals and pieces | Complete | Derived watts not labelled; no cross-rep consistency; piece notes had no input | Rest column, rep-to-rep variation (CV, spread, fade), measured/derived notes, piece notes |
| Load and strain | Complete core, incomplete | No Foster monotony/strain, monthly volume, rest-day spread or recent-vs-baseline; **Trends' volume card always errored** (asked 104 weeks, limit 52) | `/api/trends/load-history`, "Load and volume" on Trends; volume limit 104 |
| Recovery | Complete | — | Average recovery per week in load history |
| Erg performance analytics | Incomplete + broken | Erg (distance) and HR (time) charts not synchronised; **HR dropouts bridged with straight lines; power-only recordings showed nothing**; no HR at comparable power, split by rate, power progression; 2k inputs never shown | Shared cursor (same recording or known offset only; otherwise "not linked"); HR panel on the erg chart; gaps break lines; power-only charts; Performance Lab (`/lab`) |
| 2k estimate | Complete | Per-input breakdown not shown | Lab card shows each input, weight and implied 2k (algorithm unchanged) |
| Personal records | Incomplete + broken | No 10k, open-rate 30 min, power or bike records; no test/piece/training label; no history; **ignored "exclude from totals"** | `sync/records.py` (on read), `/api/records`, labels, Concept2-verified, history; `/api/pbs` delegates |
| Test types | Incomplete | Only 500 m–6000 m, 30' r20, 60' | `10000m` and open-rate `30min` everywhere (one list) |
| Goals | Missing as a feature | Free text + date in coach memory; coach `set_goal` updates reset unspecified fields (broken) | Measurable goals (migration 0013), progress on read, `/goals`, structured partial `set_goal`, `get_goals` |
| Races / events | Incomplete | No participation, no linked result; result/distance/boat class not editable in the sheet; plans/phases couldn't be tied to an event from the UI | Participation, a linked result (workout or piece) that follows merges and survives piece deletion, event pickers |
| Notes and annotations | Incomplete | No conditions/equipment; no search or filter | Conditions and equipment (overrides), workouts search/tag/has-notes (SQL, exact paging) |
| Reconciliation | Engine complete, review UX thin | Duplicates showed source/date/duration only, ignored the matcher's reasons, merged in one tap | Merge preview (each field, the merged value and its source, overlap, what moves), confirm step |
| Data quality | Incomplete | No per-workout completeness or measured/derived view | "About this data" on workout detail |
| Data export | Incomplete | Whole-account NDJSON only; bulk tagging replaced every tag including `test` (broken) | Per-category CSV/JSON (`/api/export/{category}`); bulk tags add/remove |
| AI coach | Incomplete | No test comparison, period summary, ranking, split-by-rate, records or goals tools; `list_workouts` capped at 50, no search; no deep links | 8 read tools (74 total), `ref` paths, allow-listed links in the coach UI, prompt guidance |

## Still open (not built, on purpose or for lack of time)

- Drag-and-drop rescheduling (the calendar's ←/→ and date field remain; drag is poor on touch, see DESIGN.md session 21).
- Cross-device chart sync where the two recordings' clocks aren't known to agree (watch + PM5): shown as "not linked", never guessed.
- Rolling best-power from strokes (power-duration curve) — would scan every stroke per request; records use each effort's own average.
- Per-rep comparison against Garmin laps is attempted only when the lap count matches the plan (or alternates with the planned rests).
- ICS/calendar export, folders for templates.
