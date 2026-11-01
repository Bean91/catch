// Pure range-preset <-> URL querystring helpers, shared by every Trends/Body chart so the
// visible range survives reload and can be shared as a link (task spec, interaction #5).
// Kept dependency-free (just URLSearchParams, which exists in both the browser and Vitest's
// jsdom/node environment) so it's unit-testable without mounting a component.

export type RangePreset = "7d" | "4w" | "12w" | "6m" | "1y" | "season" | "all";

export const RANGE_PRESETS: { value: RangePreset; label: string }[] = [
  { value: "7d", label: "7d" },
  { value: "4w", label: "4w" },
  { value: "12w", label: "12w" },
  { value: "6m", label: "6m" },
  { value: "1y", label: "1y" },
  { value: "season", label: "Season" },
  { value: "all", label: "All" },
];

const DAY_MS = 86_400_000;
const MIN_SPAN_DAYS = 7;

// "Season" has no single universal definition for rowing — most recent past September 1st
// (Northern-hemisphere indoor/winter-block convention), matching lib/dateRanges.ts's existing
// non-interactive Trends picker so the two don't quietly disagree.
const SEASON_START_MONTH = 8; // September, 0-indexed

export function presetSpanDays(preset: RangePreset, now: Date = new Date()): number | null {
  switch (preset) {
    case "7d":
      return 7;
    case "4w":
      return 28;
    case "12w":
      return 84;
    case "6m":
      return 182;
    case "1y":
      return 365;
    case "season": {
      const year = now.getMonth() >= SEASON_START_MONTH ? now.getFullYear() : now.getFullYear() - 1;
      const start = new Date(year, SEASON_START_MONTH, 1);
      return Math.max(MIN_SPAN_DAYS, Math.round((now.getTime() - start.getTime()) / DAY_MS));
    }
    case "all":
      return null;
  }
}

export interface DomainMs {
  min: number;
  max: number;
}

/** A preset resolved against `now` and the data's earliest known date (for "all"). */
export function presetToDomain(preset: RangePreset, now: Date, earliest: Date | null): DomainMs {
  const spanDays = presetSpanDays(preset, now);
  const max = now.getTime();
  if (spanDays === null) {
    const min = earliest ? Math.min(earliest.getTime(), max - MIN_SPAN_DAYS * DAY_MS) : max - 365 * DAY_MS;
    return { min, max };
  }
  return { min: max - spanDays * DAY_MS, max };
}

export function clampSpanDays(days: number, allTimeDays: number): number {
  return Math.min(Math.max(days, MIN_SPAN_DAYS), Math.max(allTimeDays, MIN_SPAN_DAYS));
}

export interface ChartUrlState {
  preset: RangePreset | null;
  from: string | null; // "YYYY-MM-DD", only set once the user has panned/zoomed off a preset
  to: string | null;
}

const RANGE_PARAM = "range";
const FROM_PARAM = "from";
const TO_PARAM = "to";

const VALID_PRESETS = new Set<RangePreset>(RANGE_PRESETS.map((p) => p.value));

export function parseChartUrlState(params: URLSearchParams): ChartUrlState {
  const rangeParam = params.get(RANGE_PARAM);
  const preset = rangeParam && VALID_PRESETS.has(rangeParam as RangePreset) ? (rangeParam as RangePreset) : null;
  return {
    preset,
    from: params.get(FROM_PARAM),
    to: params.get(TO_PARAM),
  };
}

/** Writes {preset} XOR {from,to} into `params` in place and returns it — a custom (panned/
 * zoomed) domain always clears the preset, and picking a preset always clears from/to, so the
 * URL never carries a preset that contradicts an explicit custom range. */
export function writeChartUrlState(params: URLSearchParams, state: ChartUrlState): URLSearchParams {
  const next = new URLSearchParams(params);
  if (state.preset) {
    next.set(RANGE_PARAM, state.preset);
    next.delete(FROM_PARAM);
    next.delete(TO_PARAM);
  } else if (state.from && state.to) {
    next.delete(RANGE_PARAM);
    next.set(FROM_PARAM, state.from);
    next.set(TO_PARAM, state.to);
  } else {
    next.delete(RANGE_PARAM);
    next.delete(FROM_PARAM);
    next.delete(TO_PARAM);
  }
  return next;
}

export function domainToDateStrings(domain: DomainMs): { from: string; to: string } {
  return { from: new Date(domain.min).toISOString().slice(0, 10), to: new Date(domain.max).toISOString().slice(0, 10) };
}
