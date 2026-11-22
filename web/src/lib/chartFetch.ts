import { toISODate } from "./dates";
import { formatShortDate } from "./format";
import type { Domain } from "./useChartInteraction";

/** How many points to ask the server's downsampler for: 2× the plot's pixel width, rounded to a step of 100 so a few px of
 * ResizeObserver jitter doesn't create a new query-cache entry. */
export function quantizePoints(plotWidthPx: number): number {
  return Math.min(2000, Math.max(200, Math.ceil((plotWidthPx * 2) / 100) * 100));
}

/** The visible range plus one screen of padding each side (clamped to the data), so a small pan has data immediately. */
export function padDomain(domain: Domain, full: Domain): Domain {
  const span = domain.max - domain.min;
  return { min: Math.max(full.min, domain.min - span), max: Math.min(full.max, domain.max + span) };
}

/** `padDomain` for date-keyed series (ms domains), as the API's from/to strings. */
export function padDateRange(domain: Domain, full: Domain): { from: string; to: string } {
  const d = padDomain(domain, full);
  return { from: toISODate(new Date(d.min)), to: toISODate(new Date(d.max)) };
}

/** A spoken description of a date window (navigator sliders). */
export function dateRangeText(d: Domain): string {
  return `Showing ${formatShortDate(toISODate(new Date(d.min)))} to ${formatShortDate(toISODate(new Date(d.max)))}`;
}
