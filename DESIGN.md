# Catch — design system

## Two directions considered

**A. Boathouse Mono** — warm near-black slate background, one bold indigo-violet accent,
every numeric value (splits, watts, bpm, spm, %) set in a tabular-numeral monospace against
an Inter UI face. Rowing character comes from treating every metric like a PM5 erg-monitor
digit readout, not from iconography. Motif: a single animated hairline "waterline" under
hero numbers, drawn once on load.

**B. Regatta Sans** — deep navy background, cyan accent, one humanist sans throughout with a
condensed display weight for big numbers. Motif: a repeating lane-line hairline texture
behind card headers.

## Decision: A

The mono-numeral treatment is the highest-leverage way to read as rowing-specific without
clip-art oars — it's literally how a PM5 displays splits, and it satisfies the brief's
tabular-numeral / `m:ss.t` requirement for free. B's cyan + lane lines reads as a generic
swim/fitness app. Indigo-violet was chosen over the obvious "nautical blue" or "brass/amber"
accents specifically so it never collides with the red/yellow/green recovery bands (amber
sits too close to the yellow band to read as a separate signal).

## Type pairing

- **Inter** — all UI text (labels, nav, body, buttons). Self-hosted via `@fontsource/inter`
  (no runtime dependency on Google Fonts — this app is self-hosted and often offline on the
  Pi's LAN).
- **IBM Plex Mono** — every number that sits in a data context: splits, watts, bpm, spm, %,
  dates in sparklines. `font-variant-numeric: tabular-nums` plus the mono face means columns
  of numbers always align, and splits always render as `m:ss.t`.

## Palette

Defined as CSS variables in `web/src/styles/tokens.css`, swapped under `[data-theme="light"]`
/ `[data-theme="dark"]` (dark is the default / first-class theme per the brief). Every
foreground/background pairing below was checked against WCAG AA with a contrast script
(`4.5:1` normal text, tertiary text intentionally kept just over that line) before being
locked in — see the ratios recorded in this session; nothing here was eyeballed.

| Token | Dark | Light |
|---|---|---|
| `--bg` | `#0D0F11` | `#F7F5F1` |
| `--surface` | `#161A1D` | `#FFFFFF` |
| `--surface-2` | `#1E2327` | `#EFEDE8` |
| `--border` | `#2B3135` | `#DEDAD2` |
| `--text-primary` | `#F2F0EC` | `#1B1D1F` |
| `--text-secondary` | `#A4ABB0` | `#53585C` |
| `--text-tertiary` | `#7D8489` | `#6B7075` |
| `--accent` | `#A79CFF` | `#5E4FD9` |
| `--band-green` | `#49B382` | `#1A7A50` |
| `--band-yellow` | `#E0B23C` | `#8A6A14` |
| `--band-red` | `#E2614F` | `#C7402C` |
| `--band-calibrating` | `= text-tertiary` | `= text-tertiary` |

Recovery/strain bands are the *only* other strong colours in the UI besides the accent — no
other component introduces a new hue. Every band is always paired with a text label
("Green" / "Yellow" / "Red" / "Calibrating"), never colour alone.

## Motion

Framer Motion, once-only entrance animation on rings/gauges/counters (arc draw-in + number
count-up), nothing loops. `prefers-reduced-motion: reduce` disables the draw-in and count-up
and shows final values immediately — checked via `usePrefersReducedMotion`.

## Interaction patterns (session 8: interactive charts)

Every time-series chart (`TrendLineChart`, `WeeklyVolumeBars`, `ErgChart`) shares one gesture
engine, `web/src/lib/useChartInteraction.ts`, rather than each hand-rolling pan/zoom. It's
*controlled*: callers own the `domain` (view window) as state and hand it down, rather than the
hook owning it internally — the only way Trends' main-metric-chart and weekly-volume-bars can
pan/zoom together as one linked view (interaction spec #6) is for a common ancestor to hold that
one piece of state.

**Live vs. settled domain.** Every page that fetches data for a chart keeps *two* pieces of
domain state: a live one (updates every pan/zoom frame, drives the chart's x-scale so panning
feels instant) and a settled one (only updates once a gesture ends, via the hook's `onSettled`
callback — that's what TanStack Query keys off, and what gets written to the URL). Deriving a
query's cache key from the live domain directly was a real bug caught by a CPU-throttled perf
test this session (PLAN.md's session 8 bug log) — it turned nearly every pointermove into a new
fetch attempt. Any new chart added later should follow the same split.

**Chart touch-action: `none`, not `pan-y` — reversed from session 8's original call.** Session 8
chose `pan-y` (native vertical scroll kept, JS claims horizontal/pinch via direction-locked
`preventDefault()`) specifically to avoid reimplementing scroll in JS. That worked under
Chromium's CDP touch emulation but, per the user's report, did nothing at all on their real
iPhone (session 9 — note: diagnosed from that report and from known WebKit behavior, not
reproduced on an actual device during this session). The leading suspect is a known class of
WebKit gap: iOS Safari does not reliably honor `preventDefault()` inside `pointermove`/
`touchmove` to cancel a native gesture already in progress the way Chromium does; only CSS
`touch-action` reliably governs what the browser claims versus leaves to script, and by the time
a direction-locked drag calls `preventDefault()`, Safari may have already committed to its own
native handling. `touch-action: none` sidesteps relying on that entirely: the browser never
claims the gesture in the first place, full stop, on every engine — true regardless of whether
this specific diagnosis turns out to be the whole story once actually checked on a phone (see
PLAN.md's session 9 checklist). The cost is real — vertical scroll over a chart is no longer
free — so `useChartInteraction.ts` reimplements it itself (`window.scrollBy` per pointermove, a
small decaying-velocity fling on release), gated to touch input only (mouse never loses native
scroll, since `touch-action` only governs touch). Handlers also moved from the `<svg>` itself
onto its wrapping HTML `<div>` (every chart, including `ChartNavigator`) — WebKit's
`touch-action` support on SVG root elements has its own separately-documented history of gaps,
and a plain HTMLElement is the safer bet regardless. Page-level pinch is blocked separately
(`html, body { touch-action: pan-x pan-y }` in `index.css`, plus a viewport-meta
`user-scalable=no` and an *unconditional* `gesturestart`/`gesturechange`/`gestureend`/
2-touch-`touchmove` preventDefault in `main.tsx` — no longer scoped around chart surfaces, since
a chart's own pinch runs entirely on Pointer Events against `touch-action: none` and never relied
on these legacy gesture events to begin with) — see PLAN.md's session 8 gotchas for why both the
meta tag and the JS belt-and-suspenders exist (iOS Safari ignores `user-scalable=no` in a plain
browser tab), and session 9 for the real-iPhone findings above.

**Press-and-hold (~300ms) is a distinct third gesture mode, not a side effect of tap timing.**
A still touch for that long enters "inspect" — the crosshair/tooltip follows the finger, and
release never fires a tap or a pan, regardless of whether the finger then moves. Below the
threshold, the usual direction-lock (first ~6px of movement) decides pan vs. the (now
JS-driven) vertical scroll.

**Annotations reuse, not redefine, "taper."** A race's taper-window shading on a trend chart is
always 14 days, matching `catch/coach/memory.py`'s `next_a_race()` — the same number the Today
screen's recommendation line already uses. If that window ever needs to change, it changes in
one place.

**Crosshair tooltips look up the nearest point per series independently**, not by a shared
array index — two downsampled series (e.g. a trend's primary value and its secondary smoothed
line) don't necessarily land on the same x-positions after LTTB picks different representative
points for each, so indexing them in lockstep would show mismatched dates.

**Ctrl/cmd+wheel zoom is a native `addEventListener('wheel', …, {passive: false})`, not React's
`onWheel` prop.** React registers its delegated wheel listener as passive, so
`e.preventDefault()` inside a JSX `onWheel` handler is silently ignored (confirmed via Chrome's
own "Unable to preventDefault inside passive event listener invocation" warning) — a trackpad
pinch would zoom the whole page right alongside the chart. `useChartInteraction` takes a
`surfaceRef` specifically to attach this natively to the chart's own DOM node.

**On-chart zoom buttons removed (session 11).** Interaction spec #2's `+`/`−`/reset buttons
overlaid on each chart (`ChartZoomButtons`) covered real data on a 390px phone screen, so they
were deleted along with the component. Every other control from the original spec stays: pinch
or ctrl/cmd+wheel to zoom, drag to pan, double-tap/double-click to reset, the navigator strip,
the range presets, and `+`/`-`/arrows/Esc on a focused chart (`useChartInteraction.ts` already
had all of this — the buttons were a redundant, screen-covering affordance for the same
actions). Don't re-add on-chart buttons for this; if zoom/reset ever needs a visible affordance
again, it belongs outside the plot area (e.g. next to the range presets), never floating over
the data.

## Gym logger (session 14)

**Bottom nav at 8 items.** Adding Gym pushed the bottom nav past what session 13's "Fuel"
abbreviation note already flagged as tight at 7. At 390px, "Workouts" and "Settings" both
overflowed their equal-width flex item and got clipped against the screen edge (not just
visually cramped — actually unreadable). Fixed two ways together, not either alone: `min-w-0`
+ `truncate` on each nav item (a safety net, same `min-w-0` flexbox fix session 4 already
established for this exact "intrinsic content width bubbling up through a flex ancestor"
class of bug) so a long label degrades to an ellipsis instead of overflowing the viewport, and
shortening "Workouts" to "Log" in the bottom nav specifically (the Sidebar keeps the full
"Workouts" label — same already-established pattern as "Fuel" vs. "Nutrition") so no label
actually needs to truncate at 390px. Screenshot this at 390px before adding a 9th item.

**Strain gauge's cardio/muscular/daily-activity split is three opacities of the one accent,
not a new hue** — `bg-accent`, `bg-accent/60`, `bg-accent/30`, stacked as three segments
within the existing fill, plus a text legend below (the "never colour alone" rule already
applies to opacity-as-the-only-signal too, hence the legend). Consistent with the existing
rule that recovery/strain bands are the only other strong colours in the UI; this is also no
different from `zoneColors.ts`'s existing one-hue training-zone ramp, applied to a stacked bar
instead of a sparkline point.

**Muscle readiness body map is schematic, not anatomical** — plain rounded rects/ellipses
standing in for each muscle group on a front and a back figure, shaded by the same
accent-opacity-ramp idea as training zones (`loadColor` in `MuscleBodyMap.tsx`), never a
second hue. Each of the 17 muscle names in `catch/seed/exercises.json`'s vocabulary gets
exactly one home — front *or* back, whichever side it's actually visible on in real life
(chest/abdominals/quadriceps front; lats/glutes/hamstrings/triceps back; etc.) — never both,
so there's no ambiguity about where a given AU value is shown. A numeric list under the map
carries the same information in text, since the map's colour-only signal would otherwise be
the sole source for anyone who can't distinguish the opacity ramp.

## Morning check-in, illness card, erg test center (session 15)

**Dialogs that can reach the bottom nav need `z-30`, explicitly.** Every prior `Dialog.Content`
was centered (`top-1/2`) and never got near the viewport's bottom 52px, so the existing
nutrition dialogs' `z-30` on `Dialog.Overlay`/`Dialog.Content` (above `BottomNav`'s `z-20`)
never actually got exercised at that edge. `CheckinSheet` is a bottom sheet on mobile
(`inset-x-0 bottom-0`) specifically to put Save/Skip within easy thumb reach — without an
explicit `z-30` those buttons rendered *underneath* `BottomNav` (two `position: fixed`
siblings, one with an explicit z-index beats one without, regardless of DOM order — Radix's
portal placement at the end of `<body>` doesn't help once a sibling has set its own z-index).
Caught by screenshotting the sheet scrolled to its bottom, not by any functional test (Radix's
focus trap and click handling worked fine either way — this was purely a paint-order bug).
Carried over to `PacingPlanDialog` too, even though it's centered, since nothing stops a future
edit from growing it toward the same edge.

**Trends' metric picker stays a fixed height — new metrics go behind "More metrics," not
inline.** The four check-in sliders (soreness/stress/mood/sleep quality) were first added as
four more always-visible buttons in the existing picker row. At 390px that extra ~52px of
wrapped button height pushed the chart far enough down that its own vertical midpoint fell
inside the zone `BottomNav` already overlaps — not just a cosmetic shift, a real regression in
`web/tests/touch/charts.spec.ts`'s drag/pinch/press-hold tests (passing on main, failing with
the four inline buttons added). Fixed by collapsing the check-in metrics behind a "More
metrics" toggle, default-collapsed unless a deep link already points at one of them, so the
picker's default height — and the chart's position under it — never changes. The lesson
generalizes: any future metric/filter/tab addition to a row sitting directly above a
390px-viewport chart should be checked against `test:touch`, not just a static screenshot,
since a few pixels of picker height is exactly the kind of change a screenshot alone reads as
fine right up until it tips the chart's tap/drag point under the fixed nav.

**Erg test center has no bottom-nav slot.** The nav was already documented as tight at 8 items
(see the gym-logger note below); Tests is reached from the desktop `Sidebar` and a link in the
`Workouts` page header on mobile, the same pattern `Duplicates` and muscle-readiness already
use for a screen that doesn't need its own permanent nav real estate.

**The pacing chart is a small static bar chart, not an `ErgChart` extension.** `ErgChart`'s
pan/zoom/domain-state machinery (`useChartInteraction`, windowed re-fetching) exists for
long, dense per-stroke recordings; a test's pacing view is at most ~12 bars (a 6000m piece),
nothing to zoom into. `SplitBarChart` is deliberately dependency-free — no `Domain` state, no
`useChartInteraction` — and the full interactive stroke/HR chart for the same activity stays
one tap away via a "Full workout detail" link rather than being duplicated on the test page.

## Adding a piece (session 17)

**The piece band is the accent hue, not a new one.** `HrChart`'s shaded band (a piece's
window) and its drag handle both use `var(--accent)` at low opacity (0.1 unselected, 0.22
selected) — the same "recovery/strain bands and the accent are the only strong colours"
rule session 3 established, applied to a third chart overlay rather than a new hue. The
handle itself is a thin accent-coloured bar inside a 44px-wide invisible hit area (a real
touch target, not just a visually-thin one).

**The piece drag handle is a sibling DOM element, not inside the chart's own SVG.**
`useChartInteraction` already claims pointer events on the chart's wrapping div for pan/zoom/
pinch; a drag target living inside that same surface would either get swallowed by the
chart's own gesture handling or require teaching that hook about a second kind of drag it has
no reason to know about. Instead the handle is a small absolutely-positioned `<div>` rendered
as a later sibling of the chart surface (so it paints on top without a z-index fight), with
its own `onPointerDown`/`setPointerCapture`/`stopPropagation` — completely independent of the
chart's own interaction state, following the same live-local-state-then-commit-on-release
split as every other chart gesture here (live while dragging, one `PATCH /api/pieces/{id}/
align` on release).

**"Add piece" is one dialog with a branching first step, not three screens.** Photo and
typed/pasted entry both exist only to produce the same `splits` array; routing them through
separate dialogs would mean keeping two review-table implementations in sync instead of one
(`SplitsReviewTable`, shared with the piece-edit card). The photo tab is hidden outright when
no Anthropic key is configured (same `anthropic_key.configured` check Nutrition's photo-
estimate entry point already uses), not shown-then-erroring. When opened from the test center
rather than a workout's own page, the dialog gains one extra first step — an activity picker
— since the test center doesn't already have one workout in scope; workout detail already
knows which activity, so it skips straight to choosing a method.

## Training intelligence (session 18)

**Confidence is rendered as plain text, never a colored badge.** Every other `band` string in
this app (`recovery`, `strain`, `load`, illness `level`) is a real status judgment — green
means things are fine, red means they're not — and `BandBadge` exists to make that judgment
glanceable. A training-intelligence `confidence` value (`insufficient_data`/`low`/`medium`/
`high`) is a different kind of thing: how much data backs a claim, not whether the claim is
good or bad news. Giving it a traffic-light color would misread "low confidence" as a warning
the way a red recovery band legitimately is, so it's always a plain `text-tertiary` line
("Confidence: medium") instead — the one place in this feature that deliberately *doesn't*
reuse `BandBadge`, even though almost everything else here does (recommendation type,
consistency band).

**`PieceTrendMiniChart` is a `SplitBarChart`-style static chart, not a new interactive one.**
Three bars (best/typical/recent) per equivalence bucket is nothing to pan or zoom into — same
reasoning `SplitBarChart.tsx`'s own docstring already gives for staying dependency-free rather
than building on `useChartInteraction`/`Domain`. The training-distribution summary on the same
page follows the same rule for the same reason: a small, static zone-percentage bar, not
`WeeklyVolumeBars.tsx`'s full controlled pan-zoom domain (that component's own interface is
built for Trends' primary interactive chart, and plumbing its domain state into a secondary
summary card would be a lot of machinery for no real benefit here).

**No new top-level Sidebar/BottomNav slot.** Both nav lists are already documented above as
tight; the training-intelligence page lives at `/trends/intelligence`, reached by a `<Link>`
on Trends' own header, matching the Tests/MuscleReadiness/Duplicates/Status precedent of a
standalone route with no nav slot of its own.

## Rowing character, restrained

- Splits always `m:ss.t` (round to tenths *before* splitting, so `119.96` → `2:00.0`, never
  `1:60.0`).
- Rate is always labelled `spm`, never "cadence" or "rpm".
- One hairline "waterline" gradient, used once per screen max (under the recovery ring).
  No oars, no boat silhouettes, no rowing-stroke clip-art anywhere.
