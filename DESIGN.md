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

## Rowing character, restrained

- Splits always `m:ss.t` (round to tenths *before* splitting, so `119.96` → `2:00.0`, never
  `1:60.0`).
- Rate is always labelled `spm`, never "cadence" or "rpm".
- One hairline "waterline" gradient, used once per screen max (under the recovery ring).
  No oars, no boat silhouettes, no rowing-stroke clip-art anywhere.
