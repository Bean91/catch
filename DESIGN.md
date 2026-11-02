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

## Rowing character, restrained

- Splits always `m:ss.t` (round to tenths *before* splitting, so `119.96` → `2:00.0`, never
  `1:60.0`).
- Rate is always labelled `spm`, never "cadence" or "rpm".
- One hairline "waterline" gradient, used once per screen max (under the recovery ring).
  No oars, no boat silhouettes, no rowing-stroke clip-art anywhere.
