# Redesign audit (session 35, 2026-11-22)

This audit was taken before the session-35 redesign so the result can be compared against it.
- **Baseline commit:** `7bb025a`.
- **Measurements:** made on the personal production build (`vite preview`, `?mock=1`).

## Baseline numbers

| Measure | Before |
|---|---|
| Initial JS (`npm run check:bundle-size`) | **236.5 KB gzip** of a 250 KB budget |
| Largest chunks (gzip) | index 175.6 KB, api 58.5 KB, RouteMap 44.6 KB (lazy), WorkoutDetail 16.3 KB, Settings 9.1 KB |
| Trends chart, mouse drag at 4× CPU throttle | 35.0 ms per pointer move |
| Trends chart, hover sweep at 4× | 16.2 ms per move |
| Workout detail (HR chart), drag at 4× | 20.9 ms per move |
| Workout detail, hover at 4× | 16.6 ms per move |
| Playwright touch suite | 331 passed, 8 skipped |
| Horizontal overflow / console errors on 35 routes at 390 and 1280 px, both themes | none |

## What exists and works (keep)

- **Tokens.** Colour is almost entirely token-driven: all `.tsx` files contain just 3 raw hex values, the RouteMap fallbacks. Retuning `styles/tokens.css` restyles the whole app.
- **Chart interaction.** `lib/useChartInteraction.ts` handles pan, pinch, ctrl/cmd+wheel, keyboard and press-and-hold. It keeps live and settled view windows separate and is covered by real-touch tests.
- **Data loading.**
  - Downsampling happens on the server (`points=`).
  - Every route except Today and Login is lazy-loaded.
  - Settings cards load independently of each other.
- **Accessibility and honesty rules.** These are documented in DESIGN.md and enforced by Playwright:
  - glyph and word, never colour alone;
  - z-30 sheets;
  - 44 px targets;
  - text never widens the page;
  - reduced motion is respected;
  - estimates are labelled as estimates;
  - no shaming words in the calendar.

## Incomplete or inconsistent

- **Six shared UI primitives in total:** Card, BandBadge, Skeleton, EmptyState/ErrorState, CountUp and Waterline. Everything else is rebuilt in each file:
  - **Buttons:** 437 buttons. There are at least 28 primary and 45 secondary className variants. Disabled opacity ranges from 30 to 60, and heights are a mix of `min-h-9` and `min-h-11`.
  - **Inputs:** about 35 local input and button constants. Backgrounds are a mix of `bg-bg` and `bg-surface-2`, and only 2 of them have a focus style.
  - **Sheets and modals:** 13 bottom sheets copied from one another. A shared Sheet exists, but only clubs uses it. There are also 10 centred modals.
  - **Page chrome:** 38 `<h1>`s in 5 styles, 5 back-link styles, 4 segmented-control or tab styles, and 11 `<dl>` styles.
  - **Unused packages:** Radix Switch, Tabs and Tooltip are installed but not used.
- **Radius tokens are inverted.** `rounded-md` is 14 px and `rounded-lg` 20 px, but `rounded-xl` is 12 px. The spacing and motion tokens are never used. Several `@theme` entries refer to themselves.
- **Shell.**
  - The sidebar is a flat list of 13–15 items with no `<nav>` landmark.
  - Between 640 and 1023 px the bottom nav becomes an ordinary row at the end of the page, so tablets effectively have no nav.
  - The theme toggle is in three places.
  - `theme-color` is fixed at `#0D0F11`.
- **Pages.**
  - Headings jump from the h1 straight to the card `h3`s.
  - Today has no title and renders the sleep card twice.
  - WorkoutDetail is 690 lines in one column.
  - Settings has about 20 cards with no grouping.
  - Training intelligence is 8 identical full-width cards.
- **Charts.** There are 19 visualisations and they share no axis, grid, tooltip, scale, legend or frame code:
  - **Duplicated code:** ResizeObserver ×6, tooltip markup ×5, nearest-point search ×6, `quantizePoints`/`padDomain` ×3, range-preset rows ×3, stacked zone bar ×3.
  - **Axes and ticks:** Y ticks are the raw min/mid/max. ErgChart has no axes at all and overlays three series, each on its own scale.
  - **Missing chart types:** there are no gradients and no area, heatmap or scatter charts.
  - **Sparkline:** points are spaced by index rather than date, and the label "14 day trend" is hardcoded.

## Broken

- **Skeleton shown forever on error:**
  - Status (it checks `!data` before `isError`);
  - a calendar day missing from the payload;
  - EventDetail's projection;
  - Plan's weekly bars.
- **No error UI:** Trends, Body and Gym.
- **Wrong error state:** MuscleReadiness shows its empty message on error, and TestCenter renders nothing when PBs fail.
- **Missing z-index:** six dialogs (Recovery, Strain, Vitals, Plate calculator, Exercise picker, Coach history) have none, so the fixed bottom nav paints over their scrim on a phone.

## Visually poor

- **Cards:** every card is the same flat `#161A1D` box with a 1 px border, and titles are `text-sm` grey. There is no elevation, no hierarchy, and no page titles above the card titles.
- **Accent colour:** one violet carries the accent, every chart series and every zone, so heart rate, power, pace and stroke rate are indistinguishable.
- **Charts:** they are thin lines on bare SVG, with no area, no gradient and unrounded tick labels.

## Performance problems

- **TrendLineChart:** on every pan frame it rebuilds paths from all padded points, parsing a Date per point. Nothing is memoised and there is no clip.
- **HrChart:** nothing is memoised, and with an overlay it draws about 1300 `<circle>`s per frame.
- **ErgChart:** filters and sorts every stroke on every render.
- **WeeklyVolumeBars:** up to 520 `motion.rect` per pan frame.
- **TrackChart:** re-sorts on every hover.
- **Trends:** `plotWidthPx` is stuck at 600.
- **Duplicate query keys:**
  - `plan-week` / `plan-weeks`;
  - `memory` / `coach-memory`;
  - `gym-exercises` / `exercises`.
- **Plan** fires seven separate week requests.
- **Fetches that bypass the query cache:** ExerciseBlock's last sets, AddFoodDialog, Body's manual save, Onboarding's progress write.
