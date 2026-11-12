import type { PhaseKind, PlannedDisplayStatus, SessionType, ZoneLabel } from "../../lib/types";

export const SESSION_TYPES: { value: SessionType; label: string }[] = [
  { value: "erg", label: "Erg" },
  { value: "on_water", label: "On-water" },
  { value: "run", label: "Run" },
  { value: "bike", label: "Bike" },
  { value: "strength", label: "Strength" },
  { value: "cross", label: "Cross-training" },
  { value: "test", label: "Test" },
  { value: "rest", label: "Rest day" },
  { value: "other", label: "Other" },
];

export const ZONES: ZoneLabel[] = ["UT2", "UT1", "AT", "TR", "AN"];

export const PHASE_KINDS: { value: PhaseKind; label: string }[] = [
  { value: "general_prep", label: "General preparation" },
  { value: "specific_prep", label: "Specific preparation" },
  { value: "pre_competition", label: "Pre-competition" },
  { value: "competition", label: "Competition" },
  { value: "recovery", label: "Recovery / transition" },
];

export const EVENT_TYPES = [
  { value: "race", label: "Race" },
  { value: "2k_test", label: "Erg test" },
  { value: "camp", label: "Camp" },
  { value: "selection", label: "Selection" },
];

export function sessionTypeLabel(t: string): string {
  return SESSION_TYPES.find((s) => s.value === t)?.label ?? t;
}

export function phaseKindLabel(k: string): string {
  return PHASE_KINDS.find((p) => p.value === k)?.label ?? k;
}

export function eventTypeLabel(t: string): string {
  return EVENT_TYPES.find((e) => e.value === t)?.label ?? t;
}

// Wording is neutral on purpose: a past plan entry with no workout linked is "Not logged"
// (it may simply not have been recorded), never "missed" or "behind". Every state has a text
// label and a glyph as well as a style, so nothing relies on colour alone.
export const STATUS_STYLE: Record<PlannedDisplayStatus, { label: string; glyph: string; cls: string }> = {
  planned: { label: "Planned", glyph: "○", cls: "border-accent/40 bg-accent/10 text-text-primary" },
  linked: { label: "Done", glyph: "✓", cls: "border-border bg-surface-2 text-text-primary" },
  skipped: { label: "Skipped", glyph: "–", cls: "border-dashed border-border bg-transparent text-text-tertiary" },
  not_logged: { label: "Not logged", glyph: "·", cls: "border-dashed border-border bg-transparent text-text-tertiary" },
  rest: { label: "Rest day", glyph: "◐", cls: "border-border bg-transparent text-text-secondary" },
};

export function formatMinutes(min: number | null | undefined): string {
  if (min == null) return "—";
  const m = Math.round(min);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function formatDistance(m: number | null | undefined): string | null {
  if (!m) return null;
  return m >= 1000 ? `${(m / 1000).toFixed(m % 1000 === 0 ? 0 : 1)} km` : `${Math.round(m)} m`;
}

export function plannedMeta(p: { duration_min: number | null; distance_m: number | null; target_zone: string | null; start_time: string | null }): string {
  return [p.start_time, p.duration_min ? formatMinutes(p.duration_min) : null, formatDistance(p.distance_m), p.target_zone].filter(Boolean).join(" · ");
}
