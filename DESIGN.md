# Catch — design system

## Design system (session 35) — current

Session 35 replaced the original "Boathouse Mono" palette and several layout rules. **Where an older section below disagrees with this
one, this one wins.** The older sections stay for their reasoning and for the rules that still hold; the ones that no longer hold are marked
*superseded*.

### Direction

- **Look:** dark first, deep navy surfaces layered by brightness, one refined periwinkle accent, and a small muted palette with one colour
  per measurement.
- **What colour is for:** status, or the identity of a measurement. It never decorates.
- **Type:** the PM5-style mono figures (IBM Plex Mono, tabular) and Inter for UI stay.
- **Gradients:** at most one decorative gradient per screen, the soft navy glow behind the page (`body` in `index.css`). Cards are flat
  surfaces.

### Tokens

Defined in `web/src/styles/tokens.css` and mapped into Tailwind by `@theme inline` in `index.css`. Utilities reference the variables directly,
so the light/dark swap reaches everything.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0B1120` | `#F4F6FB` | Page |
| `--surface` / `-2` / `-3` | `#111A2E` / `#18233A` / `#1F2B45` | `#FFFFFF` / `#EEF1F7` / `#E5E9F2` | Card / inset and controls / raised and hover |
| `--border` / `-strong` | `#243049` / `#34425F` | `#DCE1EB` / `#C5CCDA` | Hairlines |
| `--text-primary` / `-secondary` / `-tertiary` | `#EDF1F8` / `#A9B3C8` / `#8893AB` | `#111827` / `#4A5468` / `#5B667C` | Text |
| `--accent` / `-strong` / `-soft` | `#8C9CFF` / `#AAB6FF` / 14 % tint | `#4D58D0` / `#3B45B8` / 10 % tint | Chrome, focus, selection, the load/volume series |
| `--band-green` / `-yellow` / `-red` | `#4CC38A` / `#E5B84B` / `#EF7565` | `#1A7A50` / `#8A6A14` / `#C7402C` | **Status only**, always with a glyph and a word |
| `--metric-hr` / `-power` / `-pace` / `-rate` | `#D9677F` / `#BB8B2F` / `#3B9FD1` / `#9380E8` | `#C4456A` / `#966810` / `#1F7FAE` / `#7655D0` | One colour per measurement, everywhere |
| `--metric-sleep` | `#7F8FE0` | `#5866C8` | Sleep stages, weight |

**Contrast.** Every text/background pair was checked with a contrast script. All text is at least 4.5:1, with one exception: tertiary text on
`--surface-3` in light mode is 4.47, and that pairing is used only for hover.

**Radii.** Values only; the class names didn't change: `sm` 6, `md` 10, `lg` 14, `xl` 18, `2xl` 22 (px).

**Shadows.** `--shadow-1` to `--shadow-3` are navy-tinted. Cards also get `--highlight`, a 1px lit top edge in dark mode.

**Motion.**
- Easing: `--ease-out`.
- Animations: `animate-enter` (route change), `animate-sheet-up`, `animate-shimmer` (skeletons).
- `prefers-reduced-motion` stops all of them, through the global rule in `index.css`.

### Metric palette: validated, not eyeballed

The palette was checked with the dataviz skill's `validate_palette.js` against the real surfaces. Every pair that shares a plot passes all the
hard gates in both modes:

| Pair | Dark: colour-blind ΔE (deutan) | Dark: normal-vision ΔE | Light: colour-blind ΔE (deutan) |
|---|---|---|---|
| HR + power | 8.7 | 15.5 | 8.2 |
| HR + rate | 16.0 | 18.7 | 17.2 |
| Power + rate | 26.2 | 26.2 | — |
| Pace + power | 21.3 | 23.2 | — |

Accepted deviations, all deliberate:
- **Lightness.** The dark steps sit at OKLCH L 0.66–0.72, while the validator's band ends at 0.67. The softer, pastel-leaning colour was asked
  for.
- **Pace vs rate.** Sky and lavender are close under deuteranopia (ΔE 3.8). They never share a plot: the erg chart shows them as separate
  panels.
- **Accent vs rate.** For the same reason, the accent is never a series colour beside rate (ΔE 2.4).
- **HR vs status red.** Rose against `--band-red` is ΔE 6.1. They never share a plot, and status always has a word.

**Zones** stay a one-hue sequential ramp, now solid steps mixed into `--surface-2` (`zoneColors.ts`).

### Navigation

**One source.** `web/src/lib/navigation.ts` is the single list of destinations: each one's group, icon, blurb, public-only flag and owning tab.
The sidebar, tab bar, More sheet and Train hub all read it.

**Desktop (lg and up).** A grouped sidebar: Overview, Training, Health, Coaching, Community. Settings, the theme switch and log out are pinned at
the foot. The active item is a soft pill plus an accent bar.

**Phone and tablet (below lg).** A fixed five-slot tab bar: **Today · Plan · Train · Coach · More**.
- More opens a grouped sheet of every other destination.
- Exactly one tab is active for any route (`tabFor`).
- `/train` is a hub: training tiles plus recent sessions.

This supersedes the "bottom nav at 8 items" notes further down.

**Shell heights.**
- `--shell-top` is 60px.
- `--shell-bottom` is 52px. It must not be taller than the old bar, because charts.spec's Trends geometry depends on it.

### Primitives

In `web/src/components/ui/`, with no new dependencies.

- **Buttons:** `Button`, `IconButton`, `ButtonLink` and `buttonClass`.
  - Variants: primary, secondary, subtle, ghost, danger.
  - Sizes: md (44px) and sm (36px). `loading` shows a spinner and disables.
- **Form controls:** `Field`, `Input`, `Select`, `Textarea`, `controlClass` (full width) and `controlBase` (sized by its row).
- **Dialogs:**
  - `SheetContent`: a bottom sheet that becomes centred from `sm:` up, at z-30, with no autofocus.
  - `ModalContent`: always centred.
  - `Sheet`: the whole thing in one component.
- **Navigation:** `Segmented` (a real tablist with arrow keys), `PillNav`, `PageHeader`, `SectionHeader`, `BackLink`.
- **Data display:** `StatTile`, `DefinitionList`, `DataTable`, `Badge`, `BandBadge`.
- **Feedback:**
  - `Notice`.
  - `Toast` via `useToast`. It confirms actions that have no visible result in place. Its live region has no `role="status"`, so it never
    collides with a page's own status line.
  - `InfoTip`: tap to explain an unfamiliar metric. It is fixed-positioned and clamped to the viewport, so it can never widen a phone page.
- **Inputs:** `Switch`, which shows On/Off as a word beside the track.
- **Card:**
  - `tone`: default, raised, inset or accent.
  - `eyebrow`: a small label above the title.
  - The title stays an `h3`, and the root keeps the `rounded-lg` class.
- **Loading:** `Skeleton`, `CardSkeleton`, `ChartSkeleton`, all with a shimmer.
- **Empty and error:** `EmptyState` takes an optional title and action. `ErrorState` has `role="alert"`, and the message's parent element
  holds Retry.

### Chart kit

The pieces in `web/src/components/charts/core.tsx`:
- **`useChartWidth`:** measures synchronously on mount. A late ResizeObserver once let a chart draw at a 600px guess and widen a 320px page.
- **Axes:** `niceTicks` and `secondsTicks` give rounded axis values. A non-zero baseline is always labelled.
- **Paths:** `linePath` and `areaPath` use monotone cubic smoothing, so a smoothed line never overshoots the data. A null value breaks the
  line.
- **Lookup:** `nearestIndex` and `lowerBound` binary-search pre-parsed x values.
- **Drawing:** `AreaGradient` with `useSvgId`, and `YGrid`.
- **Tooltip:** `ChartTooltip` slides along itself, so it never leaves the chart.
- **Labels:** `Legend`, and `summarize`, which writes the spoken summary.

Charts built on the kit:
- **Rebuilt:** `TrendLineChart`, `HrChart`, `ErgChart`, `WeeklyVolumeBars`, `TrackChart`, and `Sparkline` (now spaced by date).
- **`ValueBars`:** static bars with a labelled axis. `invert` is for paces; it also takes optional target ticks and a reference line.
- **`StackedBar`:** every 100 % breakdown.
- **`PlanBar`:** planned against completed.
- **`MiniLineChart`:** static progression, with measured results drawn as rings over an estimated line.
- **New chart types:** `CalendarHeatmap`, `ScatterPlot`, `Histogram`.

Chart rules:
- **One y-axis per plot.** The HR power/cadence overlay and the erg chart's split, power and rate are separate panels sharing an x-axis,
  never a second y-axis.
- **Legends:** a legend whenever a plot has two or more series.
- **Text colour:** text uses the text colours, never the series colour.
- **Animation:** the draw-in runs once.
- **Interaction:** `useChartInteraction` and every interactive surface's attributes are unchanged.

`lib/chartFetch.ts` holds the one copy of `quantizePoints` and `padDomain`. `lib/metricColors.ts` maps each measurement to its colour.

### Pages

**Shared structure.**
- Every page title uses the same `h1` style, through PageHeader or the same classes.
- Every back link is `BackLink`.
- Sections under a title use `SectionHeader` (`h2`), so headings no longer jump straight from h1 to h3.

**Today.**
- A readiness hero: the recovery ring with a gradient arc in its band colour, strain, and sleep.
- Today's guidance, then metric-coloured vitals.
- A lazily loaded Training section after that.

**Calendar.** Gained an Agenda view and month shading by time trained.

**Settings.** Grouped into six sections, with a jump list on desktop.

## History

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

## Palette (*superseded by session 35's tokens above*)

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
other component introduces a new hue (*superseded, session 35: a validated per-metric palette now colours data series; bands are still
status-only*). Every band is always paired with a text label
("Green" / "Yellow" / "Red" / "Calibrating"), never colour alone.

## Motion

Once-only entrance animation on rings/gauges/counters (arc draw-in + number count-up), nothing
loops. *Session 35 follow-up: framer-motion was removed — draw-ins are CSS (`.draw-in` on a
`pathLength=1` path, `.ring-draw` with a `--from` offset, `.grow-x`, all in `index.css`) and
`CountUp` is a rAF tween; don't add an animation library back.* `prefers-reduced-motion: reduce` disables the draw-in and count-up
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

**Bottom nav at 8 items** (*superseded, session 35: five slots plus More*). Adding Gym pushed the bottom nav past what session 13's "Fuel"
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

## Intervals within a piece (session 19)

- **Stacked rows, not a wide table, in the editor.** Target + result + rest + five optional
  metrics per row can't fit 390px without sideways scrolling (the existing splits table's
  `min-w-[480px]` scroll is the thing to avoid repeating). Only the prescription, the result
  and rest are always visible; watts/rate/HR/max HR/calories/notes sit under a per-row "More".
- **Quick add first.** A "Reps x distance-or-time, rest" bar generates rows in one tap, so
  4 x 500m is a handful of taps; "+ Add custom interval" covers ladders. The ordinary single-piece
  flow is unchanged — Intervals is just one more choice on the method step.
- **Reorder with up/down buttons**, 44px-ish targets, no drag dependency and no drag-vs-scroll
  conflict on touch.
- **Work vs rest.** Totals strip keeps Work and Rest as separate figures. In the list, rest is
  a muted, italic inset line under the interval it follows — a different register from effort
  rows, never a row of its own with fake metrics.
- **Honest partial data.** "N of M intervals have both distance and time" appears when
  averages exclude some rows; blank cells are "—", never 0.
- **Interval pieces have no Pacing link** (that view is for one continuous effort).
- Interval comparisons live on the Training intelligence page as plain text + confidence, same
  as the other cards — no new nav slot.

## Maps, GPS and weather (session 20)

- **Provenance in words.** Every figure computed from GPS fixes carries a small "GPS-derived" chip;
  Garmin's own numbers sit in a separate "What Garmin reported" block with a "Garmin-reported" chip —
  never blended, never colour alone. Missing values read "—" / "not available", never 0.
- **The map is a vector overlay on a basemap that can fail.** The route is drawn as SVG polylines, so it
  still shows (on `--surface-2`) when tiles can't load offline. OSM attribution is always visible. Leaflet
  loads in its own lazy chunk, only as the placeholder nears the viewport (never in the initial bundle).
- **Speed on the line = weight and opacity in the one accent hue** (thin/faint = slow, thick/solid = fast)
  with a numeric legend — no new hues. Start is a larger ring under a smaller solid finish dot so a loop
  shows both.
- **The map must never trap page scroll.** Touch: one finger scrolls the page (`dragging` off, a "Use two
  fingers to move the map" hint appears), two fingers pan/zoom. Mouse: drag pans; the wheel zooms only with
  ctrl/cmd held (a trackpad pinch sends exactly that) and otherwise shows a hint and lets the page scroll.
  Zoom buttons are 44px on a coarse pointer. Verified with real CDP touch and mouse input
  (`web/tests/touch/route-map*.spec.ts`).
- **The speed/pace chart is read-only**, so unlike the HR/erg charts it sets `touch-action: pan-y`: a
  horizontal drag moves the crosshair (and a marker on the map), a vertical swipe still scrolls. Pace is
  plotted inverted (faster = higher) like speed; y-range is the 2nd–98th percentile so one noisy fix can't
  flatten the line; the line breaks at a GPS gap rather than bridging it.
- **Weather is observed data, labelled as context.** Chips on the summary card, a Conditions card with
  coverage, provisional/partial flags, the wind arrow pointing where the wind blows *to* (the text says
  "from"), the Open-Meteo attribution link, and the standing note that it is not a performance correction.
- **Routes** have no nav slot (the Tests/Duplicates/Status precedent): a desktop sidebar entry plus a
  "Routes" pill in the Workouts header (which now wraps). Route history is plain text + one static SVG
  histogram, with the not-corrected caveats printed on the page.

## Calendar, plans and events (session 21)

- **Navigation.** The calendar took the old "Log" bottom-nav slot, labelled **"Plan"** (calendar icon): "Calendar"
  clips at 11px on 375px and 360px phones (measured with a width sweep at 320/360/375/390/430; `calendar.spec.ts` asserts no label truncates at 390px), the same
  constraint behind "Fuel"/"Gym". The page, the desktop sidebar entry and the URL are "Calendar". The tab also reads
  active on `/workouts*`. Workouts, Tests, Routes, Duplicates and the training plan are pills under the Calendar
  header. (`Settings` itself already clips below 375px; that predates this.)
- **Session states, no shaming.** Planned = accent-tinted solid border, "○ Planned"; Done = filled surface, "✓ Done";
  Not logged = **dashed** outline and tertiary text, "Not logged"; Skipped = dashed, "Skipped"; Rest = quiet outline,
  "Rest day"; completed workout = "● Completed"; event = accent "◆". Every state has a glyph *and* a text label.
  Nothing is red or called missed/behind/overdue, and no week is coloured "over". Bars are neutral: filled = completed,
  outlined = planned, dashed marker = target.
- **Week view** is seven stacked day rows (date column / chips / a 44px "+"), so nothing scrolls sideways at 390px.
  Month is a dot grid (○ planned, ● completed, ◆ event) where every cell has a spoken label; tapping opens the day.
  No drag-and-drop (poor on touch): a session is moved with the sheet's "← Earlier / Later →" buttons or its date field.
- **Sheets** are bottom sheets (`z-30` over the bottom nav, per the existing rule), do not auto-focus the date field
  (iOS would open its picker), keep native date inputs `overflow-hidden`/`min-w-0`, and confirm destructive actions inline.
- **Review flags** read as "Worth a look" — a calm note in a quiet surface, no icon, no colour — and never say "should".
- **Projection card** always shows the number with its range, the data it came from, the assumptions and an
  uncertainty line; with too little data it says why instead of showing a number.

## Library, technique notes and coaching feedback (session 22)

- **Navigation.** No new bottom-nav slot (it is already at eight; `calendar.spec.ts` asserts that). "Library" and
  "Feedback" are desktop-sidebar entries plus pills under the Calendar and Workouts headers; sub-pages carry a back link.
- **Privacy is always a glyph and a word, never colour alone.** `PrivacyBadge`: lock + "Private — only you" (quiet
  outline) or two-people glyph + "Shared with coach" (accent-tinted). It appears on *every* technique note and every
  feedback entry, and a "Who can see what" card at the top of the feedback page explains both. A coach-written entry
  reads "Shared with you".
- **Ownership is visible.** Every feedback entry names its author and role ("Coach" / "Your entry"), shows "via AI coach"
  when the in-app coach logged it, and an entry the viewer can't edit says "Written by … — only they can edit it" instead of
  showing a disabled Edit. "Edited · history (n)" expands the earlier versions inline.
- **No technique verdicts.** The technique-notes card is titled "Technique notes" (distinct from the stroke-metrics
  "Technique" card) and says "Catch can't see technique in this data, so nothing here is scored or rated." No score,
  grade, star or colour is attached to technique anywhere; `library.spec.ts` scans for judgement words.
- **Examples are labelled where they appear**, not just on a tab: a "Example — not prescribed training" pill on every
  example card and detail page, plus a notice above the Examples tab. Examples are read-only (Duplicate, not Edit).
- **Honest totals.** A distance-only template shows "Not set" with the reason, never `0:00`; an estimated duration says
  it is estimated from the split/watts target. Zone minutes are labelled "(work only)".
- **The editor holds no interval math**: stacked block rows (nothing sideways at 390px), a "Check" panel that shows the
  server's validation messages and totals, sticky beside the form on desktop and below it on mobile. Rows are reordered
  with ↑/↓ buttons (no drag-and-drop, as in the calendar).
- **Sheets** follow the calendar's rules: bottom sheets on mobile at `z-30`, centred on desktop, no auto-focus on date
  fields, destructive actions confirmed inline. The visibility choice is a two-option radio group (Private is the default
  for notes) with a one-line consequence under each option.
- Wording stays neutral — no "missed", "behind", "overdue" — and cards say "Not set", "Estimated", "Exact" rather than
  grading a template.

## AI providers, Whoop and recovery inputs (session 23)

- **Navigation.** "AI providers" is `/settings/ai`, reached from a link on the Settings "AI coach" card (and from every
  coach notice that needs it); no bottom-nav or sidebar slot, same pattern as Status and Memory. It has a "← Settings" link.
- **Status is a glyph and a word, never colour alone**: ● Connected, ◐ Saved — not checked yet, ✕ Invalid key, ! Unavailable,
  ○ Not configured, each in a pill; "Active" is a separate accent pill. Detail text explains *why* in a sentence from a
  fixed vocabulary (never provider text) and always names the way out ("Replace it, or switch to another provider").
- **A key is entered once and never shown again.** The key field is a password input (`autocomplete=off`,
  `autocapitalize=none`, `spellcheck=false`) in a bottom sheet (`z-30` over the bottom nav, no autofocus, centred on
  desktop). The card shows `Key …abcd` — only the last four characters of a long key, or just "Key saved". The sheet's
  copy says it checks the key first, stores it encrypted, and that the user pays the provider directly.
  A rejected key keeps the sheet open with the reason and clears the field. `ai-providers.spec.ts` asserts the full key is
  never in the page text or HTML after saving.
- **Destructive actions are confirmed inline** (the existing pattern — no new dialog dependency): "Remove key" opens a
  bordered row that says conversations and coach memory stay, with "Remove key" / "Keep it". Whoop's "Disconnect" says
  imported data stays.
- **Honest numbers.** Usage is titled "Usage Catch has recorded" and says plainly that no provider balance is shown
  because none offers one through an API key. A model with no entered price reads "cost unknown (no price entered)",
  never "$0.00". Prices live behind a collapsed "Prices for <model> (optional)" row.
- **Capabilities hide, they don't error.** The meal-photo and PM5-photo entry points are absent unless the active provider
  is configured, has a model and can read images; a model that can't is marked "(no photos)" in its picker.
- **Coach notices** for provider trouble sit in the existing strip above the composer: one-tap "Switch to <provider>" for
  every other configured provider, plus an "AI providers" link. Switching never touches the conversation.
- **Whoop** is a fourth row in "Connected sources" with Connect/Reconnect, Sync now, Test connection (counts only) and
  Disconnect; a `?whoop=connected|denied|failed` notice appears after the OAuth round trip.
- **Recovery details show their inputs.** The Today recovery dialog now lists "What this score used": each input with a
  ✓ and its provider ("Garmin", "Whoop"), "— none today" when missing, "shown, not scored" for inputs the formula doesn't use,
  `n/7 nights` for HRV, a calibration sentence, and — when the last week mixes devices — a plain note that the comparison is
  less exact. "Recovery inputs" in Settings is a two-button radiogroup (Garmin first / Whoop first), not a table.

## Accounts on the public build (session 24)

Only the public build (`VITE_CATCH_DEPLOYMENT=public`) shows any of this; the personal build is the one-field password screen it always was.

- **One frame, the existing tokens.** Sign in, create account, reset password and "choose a new password" are the same centred 384 px card as the
  password screen, with the same inputs, the same accent button and the same `text-band-red` error line — no new component, no logo treatment.
  Switching view is two quiet text links under the card ("New here? Create an account", "Forgot your password?") with 44 px hit areas.
- **Messages never reveal who has an account.** A wrong password and an unknown address are the same sentence; "Reset password" always answers
  "If that address has an account, a reset link is on its way."; a taken address says "If you already have one, sign in or reset your password."
  Specific wording is kept only where it helps and leaks nothing: "Confirm your email first", "Too many attempts. Wait a minute", "Use at least 8 characters".
- **Confirmation is a state, not a toast.** After sign-up the card is replaced by a `role="status"` sentence ("Check your email — we sent a link…") and a
  single "Back to sign in" button; it doesn't disappear on a timer.
- **Account card (Settings, public only).** Shows the signed-in address, "Sign out of all devices" and "Delete account…". Delete opens an inline
  `role="alertdialog"` with a red hairline border listing what is removed and a typed-`DELETE` field; the destructive button stays disabled until the word matches. The one place red
  is a fill rather than text.
- **Signing out is a clean break.** It clears the query cache, the service worker's `/api` cache, the offline gym queue and every `catch:*` local key — never just the token — and
  the same wipe runs when a *different* person signs in on the same browser.

## Provider connections (session 25)

`/settings/connections` — one page, one card per source (Garmin, Withings, Concept2, Whoop), reached from Settings' "Connected sources" summary and from Status. No bottom-nav slot,
same pattern as AI providers and Status. The Settings card is now only a read-out (a glyph + word per source) with a "Connect, replace a key or disconnect" link; nothing is edited there.

- **Every provider is the same card.** Status pill (glyph + word, never colour alone: ● Connected, ✕ Reconnect needed, ! Problem syncing / Waiting — provider is rate limiting,
  ○ Not connected; "Connected — importing history" while the paced import runs), then a definition list (last sync, history import start, what was allowed, key expiry, next try), a
  recovery sentence when something is wrong, and a row of actions. Only the way in differs: *Connect X* (a provider sign-in page), *Add your X key / Replace key* (a sheet), or both
  for Concept2 ("Use a personal token instead"). Sync now, Test connection and Disconnect appear once connected.
- **Secrets are entered once and never come back.** `CredentialSheet` mirrors `ProviderKeySheet`: bottom sheet at `z-30` (above the nav), centred from `sm:`, no autofocus, `type="password"`,
  `autocomplete="off"`, cleared on close, success *and* failure, error in `role="alert"`. The card shows `Key …abcd` (long secrets only) or `Key saved`; the Playwright specs assert the full
  value is in neither `innerText` nor the HTML. The sheet says what is and isn't being asked ("This is not your Garmin password, and Catch never asks for that") and that Catch checks the
  key first and stores it encrypted.
- **Honest limits, stated once.** A collapsed "What Catch can and can't do with X" lists the provider's limitations and a Yes / No / Not published capability table — both come from the
  backend's single table, so the page, the coach and the docs can't disagree. "Not published" is used where a provider documents nothing (Garmin's rate limits and history depth) instead of
  implying a number. Garmin's card always shows its disclosure line, quoting Garmin's "not intended for commercial applications serving multiple end users".
- **Recovery copy is a fixed vocabulary that names the way out** ("Create a new Personal API key in Garmin Connect and choose Replace key", "Choose Reconnect and approve access again",
  "Catch will retry on its own; nothing needs doing"). Provider text is never shown; the last error is Catch's own sentence.
- **Disconnect is confirmed inline** in a bordered `role="group"` row (no dialog dependency): "Everything already imported stays", plus, for Garmin, "also delete the key in Garmin Connect to
  end access completely" — Catch can't do that for you.
- **After an OAuth round trip** the browser lands back with `?provider=…&result=connected|denied|failed` and a `role="status"` line, not a toast.
- **Garmin's key-expiry banner** (app-wide, 14 days) and the Status page's "Garmin key" card read the connection's expiry instead of a global Settings field.

## Leaderboards and verified results (session 26)

`/leaderboards` (board + filters), `/leaderboards/athletes/:id`, `/settings/leaderboards` (opt-in, privacy, your results, history, clubs) and `/settings/moderation` (moderators
only). **No bottom-nav slot** (the bar is pinned at eight); a Sidebar entry on desktop (public build, and the mock), a Settings card, and a link from the Test center.

- **A board always says what it is.** One line above the list spells out every filter that changes the ranking ("2,000 m · Verified results only · 143 athletes"), then "ranked by
  fastest time · equal results share a rank". The page never shows a rank without that context. The reader's own row is pinned above the list, accent-outlined, labelled "You".
- **Verification is a glyph and a word, never colour alone:** ✓ Verified, ◐ Provider-linked, ○ Unverified. Only Verified is tinted (the green band token); the others stay neutral so
  nothing reads as "wrong". Unverified results appear only behind "Also show unverified", in their own labelled section that says it is never ranked above a verified result.
- **What verified means is stated where it matters** — in the publish sheet's first step and in a Card on the settings page — in plain words, including what it does *not* mean
  ("not that Catch guarantees who rowed it or their physical condition").
- **Publishing is three steps and an explicit confirm** in one bottom sheet (z-30, centred from `sm:`, no autofocus): *what this status means* → *what you choose to show* (date detail
  defaults to "No date"; age category and weight class are separate unticked boxes; an optional note) → *preview*, which renders the server's own public row and a short list of
  disclosures, with "Change choices" and "Publish this result". The confirm sends the preview's hash, so a stale preview can't be published.
- **Privacy is changed in plain controls with plain words**: a "How you appear" radio (a handle you choose, or "Anonymous rower"), a date-detail select, two checkboxes. "Preview as others
  see it" renders the public profile from the same endpoint everyone else reads. Settings say what applies to future publications and what keeps what you previewed.
- **Take-down and opt-out are inline confirmations** in a bordered `role="group"` row, never a modal, and they say what happens ("recorded in your history with the reason 'you opted out'").
- **Decisions are never silent.** "Decisions and appeals" lists every hidden/removed/withdrawn change on your results with who made it, the reason in full, and the time; a hidden or
  removed result gets an **Appeal** button (no "Take down" — a closed entry stays closed), and one hidden only because its source changed gets **Review and publish again**. Reports are anonymous to the athlete; the report sheet says so.
- **Young athletes:** the join form shows the guardian-consent box only for youth bands and tells them what is different (handle or anonymous only, year-only dates). The browser does no
  age maths — it labels and asks; the server decides.
- **Moderator page:** every action sits beside a required reason field; an empty reason returns the server's "A reason is required" in a `role="alert"` line.
- Playwright: `web/tests/touch/leaderboards.spec.ts` (both mobile projects) and `leaderboards-desktop.spec.ts` (desktop-mouse).

## Clubs, teams and challenges (session 27)

`/clubs` (your clubs, profile, an invite-link box, Discover), `/clubs/join#token` (an invite lands here; the token lives in the URL fragment and is cleared once used), `/clubs/:id` (a public club's visitor view, or a member's tabs: Overview,
News, Calendar, Challenges, Board, Members, Manage), `/clubs/:id/challenges/:cid`, and a club-reports card on `/settings/moderation`. **No bottom-nav slot** (the bar stays at eight); a Sidebar entry on desktop and a Settings card.

- **Every section says who can see it, in a glyph and a word.** `PrivacyBadge` gained two states beside Private and Shared: **Public** (a globe: every signed-in user) and **Club-only** (the people glyph: members of this club). A club is always labelled
  "Public club" or "Private club", and a junior club adds "Junior club · under 19". Colour is never the only signal.
- **The browser decides nothing about permission, age or scoring.** It renders the server's `capabilities` and `can_*` flags and every figure as returned. Controls a role can't use aren't dimmed, they're absent (an athlete has no Manage tab and no
  "New announcement"). Where a rule is *why* a button is missing, say so in words: "In a junior club only a coach or the owner approves a young member."
- **Junior clubs are visibly different**: a note under the header ("members are under 19 and approved by a coach or the owner … no private messages"), "Waiting for a coach" on held posts, sessions and challenges, and an admin (who isn't a coach) is told
  "only a coach or the owner can approve this" instead of getting a button. Held posts are invisible to athletes. The create-club sheet replaces the visibility and join-policy choices with a plain explanation when "Juniors" is chosen. A junior club has the same logo control as an adult one.
- **A decision about a person needs a written reason in a sheet** (removing a member, declining a post/session/challenge/request, taking something down, every moderator action), with the submit button disabled until there is one and the server's own wording
  in a `role="alert"` line. An irreversible act (delete a club, hand it over) shows exactly what is lost in a `role="group"` row and needs a second tap.
- **Sheets** are the existing pattern (z-30, a bottom sheet on a phone and centred from `sm:`, no autofocus), because a sheet that reaches the bottom nav's z-index hides its own buttons. **The tab bar scrolls inside itself** (`overflow-x-auto` with negative page
  margins) so seven tabs never widen the page at 390 px.
- **Team totals say when they are hidden**: "Hidden" with the line "Totals appear only when at least 3 members chose to share a number." A small number is never replaced by a dash that could read as zero.
- **Challenges state their rules before you join**: the plain-words rule list is a Card on the page, including "extra volume earns nothing", "Equal scores share a rank (1, 2, 2, 4)" and "Nothing about weight, calories, recovery or sleep is used or shown". Consistency shows each week as
  met / missed / in progress / excused, with one "Excuse this week" tap and the line "no reason needed and it's never held against you". Opting out is a plain button, not a confirmation.
- **Invite links**: shown once in a read-only field that selects on focus, with "shown once and only a fingerprint of it is stored".
- **Profile**: the handle and age group sheet says "never your real name or email", and shows the guardian tick for any under-19 band, naming under-16 as where it is needed (the server decides).
- **Reporting** says who sees it before you send it: "A platform moderator reviews every report. The club's staff are not told who reported."
- Playwright: `web/tests/touch/clubs.spec.ts` (both mobile projects, no horizontal overflow, sheets clear of the bottom nav, every junior state) and `clubs-desktop.spec.ts` (desktop-mouse).

## Privacy center, consent and legal drafts (session 28)

- **One page, plain words, no dark patterns.** `/settings/privacy` (no nav slot — reached from a "Privacy" card on Settings, like Status/Connections). Sections in order of urgency: moderation notices (only when one exists), AI sharing, what other people can see,
  connected apps, download, delete by category, account. Each says what it does and what it can't undo, in sentences, not legalese.
- **Consent is a choice, never a default.** AI sharing opens with the acknowledgement box; until it is ticked every switch is disabled. Every category starts **Off** and reads "On"/"Off" as a word inside a `role="switch"` (colour is never the only signal). The primary
  button is "Save my choice (everything stays off)" — declining is a first-class outcome. Withdrawing is one tap and says what it does. A declared age under 19 reveals the guardian tick *in place*, even when the server refused the band, so the person can fix it without losing their choice; the server's own sentence appears in a `role="alert"` line.
- **The coach says why it is quiet.** With no consent the coach shows a notice with one link ("Choose what to share"), not an error. A category that is off is reported to the coach as switched off, and the coach is told to say so rather than guess — so the athlete sees "that's switched off in Privacy", never a silent gap.
- **Destructive actions are two-step and itemised.** Each delete category shows its row count and what it removes and what it doesn't ("The workouts themselves stay"); the confirm row is a `role="alertdialog"`. Account deletion's copy is *the actual behaviour*: what goes, what stays and why (moderation decisions without your name, club posts without your name), what Catch can't undo (data already sent to an AI provider; Withings/Concept2/Garmin grants), and a plain re-sign-in prompt when the server asks for a recent sign-in.
- **App access is listed, not hidden.** Device tokens and OAuth grants appear with "read only" / "can propose changes (you confirm each)", last used and expiry, and a single "End access" tap; below them, "Recent activity by apps" shows tool, door and whether anything changed — never content.
- **The OAuth consent page names the asker and the destination.** "{app} wants to connect…", "you'll be sent to {host}", write as an *optional* checkbox that starts unticked, and a stale link is explained, not blank.
- **Legal drafts are rendered, never styled as final.** `/legal/:doc` shows a red-bordered "DRAFT — NOT LEGALLY REVIEWED" banner from the document itself, in the same Card language, with a tiny in-house Markdown renderer that builds React nodes (no HTML strings, no dependency). Tables scroll inside themselves (`overflow-x-auto`) so a wide table never widens the page at 390 px.
- **Moderator tools stay narrow.** Account restrictions show ids and reasons only, a mandatory reason field on every action, and an expandable action log; the person sees "a platform moderator decided this", the reason, and one Appeal box.
- Playwright: `web/tests/touch/privacy.spec.ts` (both mobile projects: defaults off, acknowledge-first, guardian tick, two-step delete, app access, consent page, stale link, legal drafts, no horizontal overflow) and `privacy-desktop.spec.ts`; `web/tests/public/public-auth.spec.ts` covers the re-sign-in prompt.

## Native apps (session 30)

The store apps are the same screens in the same tokens; nothing was redesigned. What the native shell adds, and the few rules it follows:

- **Safe areas are the web layer's job** (`contentInset: never`): top/bottom padding in `AppShell`/`BottomNav` as before, plus left/right insets on `#root` and the nav for landscape. Every bottom sheet pads its bottom by `env(safe-area-inset-bottom)` and caps at `dvh`, not `vh`.
- **The system decides light/dark** until the person taps the theme button once; that tap is remembered. The status-bar text colour follows the theme.
- **Permissions are never asked at launch.** Notifications on the Enable tap, camera on "Take photo", Health after the consent screen. A refusal is explained in a sentence with the Settings path, not retried.
- **Haptics confirm, never decorate:** a light tap on a logged set, a success pattern on a PR, a medium tap when the rest timer ends. Off with reduced motion or the Settings switch.
- **Health consent is a screen, not a toast:** what is shared (per type), where it goes, and the two stop/delete buttons are on the page *before* the OS sheet; a counted preview precedes the first upload. iOS can't report denial, so empty results say "no data returned".
- **No update toast** in the apps (the store delivers updates); offline/online/pending use the same subtle badge as the PWA.
- Hardware back closes the open sheet first. External links open in the system sheet, never over the app.

## Launch-audit UI corrections (session 31)

- **Nothing may claim a state the app doesn't have.** The public Status page no longer renders the server's disk, database size,
  uptime or backup state, which the API deliberately zeroes for users ("0 B", "Uptime 0m", "No backup has run yet" were false).
  Settings' metric/imperial toggle is gone because nothing read it; every figure is metric and labelled with its unit.
- Settings → Connected sources lists only providers the deployment offers (`available` from `/api/connections`). Leaderboard, club
  and moderation routes aren't registered in a personal build.
- `?mock=1` works in the dev server, personal builds and explicitly allowed test bundles only. On the real public site it would
  have shown a signed-in-looking app with fake "Connected" sources.

## Setup, passwords, time and estimates (session 32)

- **Setup is five short cards in the existing language**, one per step, with "Step n of 5" as text (and a thin accent progress bar,
  decorative only). Every step has a way forward that never waits: Skip on each provider, Skip on training basics, "Go to dashboard"
  while history imports, and a quiet "Skip setup — I'll do this later in Settings" under every step. Providers reuse the Connections
  cards untouched, each with one line on what it brings; a skipped one collapses to "Skipped for now" with "Connect instead". A provider
  sign-in that comes back refused or failed is a `role="status"` sentence, never a dead end. Only a brand-new public account is sent
  there, once, from the landing page; Settings → First-run setup reopens it.
- **Password requirements are visible before submitting** and tick off as you type: a glyph and a word per rule (✓ / ○, plus
  "done"/"not yet" for screen readers, `aria-live="polite"`), never colour alone. The rules are the server's own (min 8, lowercase,
  uppercase, number, symbol). Every password field has its own Show/Hide button (`aria-pressed`, 44 px, right inside the field), so
  revealing the password never reveals the confirmation. Sign-up and recovery ask for a confirmation; Settings → Account gained
  "Change password", which says "sign in again" in words when Supabase wants a recent sign-in.
- **Time zone** lives in Settings as plain words: "Showing dates in Tokyo now", the home zone as a select (this device's zone first,
  labelled), and "Follow my device while travelling" as an On/Off `role="switch"`. A workout's time is shown where it happened, with the
  zone named only when it differs from where you are now ("07:10 · Tokyo"). Workout detail has a small "Counts on" select (recorded
  day ± 1, "(recorded)" marked, "changed by you" when overridden) — the one manual control, for a device that was on the wrong zone.
- **Estimates look like estimates.** The 2k on Today is titled "Estimated 2k" with a small bordered `ESTIMATE` tag, the confidence as
  words ("Moderate confidence"), "likely m:ss–m:ss" and one line on what it was built from ("From 2 recent hard efforts … An estimate,
  not a result."). A measured 2k, when there is one, is its own line ("Measured 2k 6:35.2 · 8 Nov") and is never replaced. The trend
  metric is "Implied 2k per hard effort".
- **Strain's parts add up.** The gauge's three accent opacities and the breakdown show each part's *share* of the day's one load sum
  (cardio, muscular, everyday movement), and each session's share — always summing to 100 %. A watch workout counted once beside the
  erg's result says "Same time as another workout — counted once".
- **"Training issue"** replaces "niggle" in every word a person or the AI reads ("Training issue (optional)", "No training issue today",
  "Training issue: Left knee — 4 days running").
- Playwright: `web/tests/touch/onboarding.spec.ts` (both mobile projects) and `onboarding-desktop.spec.ts`; the password rules and
  toggles in `web/tests/public/public-auth.spec.ts`.

## Merging, heart-rate zones, bike pieces, photos and Settings (session 33)

- **Merging is a sheet, not a mode.** Workouts → Select gains **Merge…** once two are ticked; it opens the usual bottom sheet (z-30,
  centred from `sm:`, no autofocus). It lists the selected workouts in time order (type, date and time in the workout's own zone,
  duration, distance, sources as words), then either a plain list of reasons in a `role="alert"` box — and **no** merge button
  (absent, not dimmed) — or a "Merged workout" card with the server's own totals and a one-line note on how they were combined
  ("average heart rate is weighted by each part's time"). Overlap is stated in words ("4:00 recorded twice — counted once"). The
  earliest workout is labelled "kept as the merged workout".
- **Undo is a confirmed inline row** on workout detail, under "Merged from 2 workouts (3 recordings)", that says what comes back and
  what stays (edits made after merging stay with the earliest). No new colour; the accent only on the confirm button.
- **Heart-rate zones show their inputs.** Settings → Heart-rate zones: a two-option radiogroup (Heart-rate reserve / % of max heart
  rate) with one-line help each, the max HR field, "Resting heart rate used: 51 bpm — the median of 13 mornings (6–19 Nov)" or the
  plain fallback sentence, an optional own resting HR with "Use the measured value", and a table of % (editable) beside bpm (from the
  server). A suggested max HR is a sentence with "Use this" and a caution about sensor spikes, never applied silently. Workout detail's
  zone table ends with one sentence naming the basis that workout's zones used. The power table is its own "Power zones" card.
- **Bike pieces are labelled in words.** "Rowing erg /500m" and "Bike /1000m" as a two-option radiogroup (● / ○ glyphs) first in Add
  piece and in a piece's edit mode; every split header carries its unit ("Split /1000m"); a "Bike" word badge on the piece and in the
  test center's own "Bike pieces" card. No new hue.
- **A photo piece is reviewed with its photo.** The review step shows the chosen photo, the piece type the screen implies (to confirm),
  total distance and time, and "+ Add split" — a screen with totals only is a valid piece. Saving is one request; a failure says
  "… Nothing was saved." in the server's words. A saved piece offers "Add photo" / "Replace photo" / "Remove photo".
- **Settings cards fail on their own.** Each card has its own skeleton and, on failure, the shared error state with **Retry** —
  never an endless "Loading…". The AI provider card shows the saved model as text and fetches the provider's model list only on
  "Change model" (with "Refresh models").
- Playwright: `web/tests/touch/merge.spec.ts`, `pieces-bike.spec.ts`, `piece-photo.spec.ts` (both mobile projects), `web/tests/public/settings-perf.spec.ts`,
  and the real-backend `web/tests/gym-offline/piece-photo.spec.ts`.

## Text never widens the page (2026-11-22)

A sideways scroll on the phone app came from text that couldn't wrap. The rules:
- `body` sets `overflow-wrap: break-word`: a word breaks only when it can't fit a line on its own, so a row that fits keeps whole words.
  (`anywhere` everywhere was tried and rejected: in a tight row it broke short words like "Coach" mid-word at 320px.)
- Errors and alerts (`role="alert"`, `.text-band-red-text`, `ErrorState`) wrap anywhere: they carry URLs, paths and codes.
- A name or title a person or provider chooses (workout, route, template, club, event, food, exercise, handle, email) that sits in a row
  gets `min-w-0 wrap-anywhere`; otherwise `truncate`. Don't add `break-words` on a container: it resets the inherited rule.
- A text box in a row gets `min-w-0`: WebKit sizes an input to about 20 characters and won't shrink it below that otherwise.
- A row of buttons beside text uses `flex-wrap`, so the buttons drop below rather than squeezing the text.
Guarded by `web/tests/touch/text-wrap.spec.ts` (320px, both mobile engines, plus one-word names and a URL in an error).

## Privacy in setup, power and weight-adjusted power (session 34)

- **Privacy is a setup step, not a consent wall.** "Your privacy" is step 4 of 6, between Training basics and Importing.
  - It opens with one sentence: everything starts **off**, and skipping leaves it off.
  - Then a plain "Your training and health data" card states there is no public profile or feed, so there is nothing to switch.
  - Then the *same* AI sharing card as Settings → Privacy, untouched (acknowledge first, seven On/Off switches).
  - On the public build, a "Public leaderboards" card that says **Off** or **On** as a word. "Join the leaderboards…" opens the same opt-in
    form as Settings, and the copy says that joining publishes nothing.
  - Then a one-line Clubs note.
  - Back / Skip / Continue; Skip and Continue are equally quiet, and declining is never the harder button.
- **Connection outcomes are one sentence each**, shared by Connections and setup (`lib/connections.ts` `CONNECT_RESULT_TEXT`): connected,
  access not granted, "took too long or was used twice — start again", "this server's sign-in setup is wrong — nothing you did", couldn't be
  connected.
  - A card in `app_misconfigured` says "nothing to fix on your side and no need to reconnect" rather than the generic sync failure.
  - Disconnect states whether access was also ended at the provider (Withings and Whoop now) or still has to be removed there.
- **Watts are the server's.** The review table's column reads "Watts (from split)" on a rowing erg, and each calculated value is the input's
  *placeholder* (muted), not a typed value. Typing a screen's watts marks it entered; the server checks it against the split, and a
  contradiction is the usual red row with the calculated figure in words.
  - Under the table, one `aria-live` line: "Average power: 302 W — calculated from the 1:45.0 /500m average split", or "as entered", or why
    there is none ("a bike's power isn't calculated from pace").
  - A bike's column is just "Watts", with a note that its power is never calculated from pace.
- **Weight-adjusted power sits beside, never instead of, watts.** It appears as `16.29 W/kg²ᐟ³ · 3.78 W/kg · 302 W` in the mono figures
  font, with one explanatory line ("average watts ÷ body mass^⅔ … your raw watts are unchanged") and the weigh-in it used ("80.0 kg on 29
  Jun").
  - When no weigh-in fits it says so ("needs a weigh-in from the 30 days before this effort, or the week after") instead of showing a number.
  - Places: test and piece detail (full), the piece card (compact), the interval summary plus a per-interval column only when something
    is in it, and the trends card's best/recent rows. The unit is always written `W/kg²ᐟ³`.
  - Never shown for a bike.
- **Body weight in pounds** is a `kg | lb` select beside the manual-weight field on Body; the server converts it, and everything is
  displayed in kg.
- Playwright: `onboarding.spec.ts`/`onboarding-desktop.spec.ts` (the privacy step), `pieces-power.spec.ts` (server watts, contradiction,
  bike, weight-adjusted line), `connections.spec.ts` (each outcome sentence).

## Rowing character, restrained

- Splits always `m:ss.t` (round to tenths *before* splitting, so `119.96` → `2:00.0`, never
  `1:60.0`).
- A rowing rate is always labelled `spm`, never "cadence" or "rpm". (Session 33: a *bike* piece's rate is pedal cadence and is
  labelled "Cadence (rpm)" — the one place `rpm` appears, and only beside a "Bike" label.)
- *(Superseded, session 35)* The "waterline" hairline is gone; the recovery ring's gradient arc replaced it.
  Still true: no oars, no boat silhouettes, no rowing-stroke clip-art anywhere (the logomark is an abstract mark).
