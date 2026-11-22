import { ZONE_NAMES, type ZoneName } from "./types";

// Training zones are a magnitude breakdown (effort, low to high), not a status — same
// reasoning as SleepCard's stage ramp: kept off the green/yellow/red band palette (reserved
// for recovery/strain/load) and ramped through one accent hue instead, lightest at the
// easiest zone.
const OPACITIES: Record<ZoneName, number> = { UT2: 0.3, UT1: 0.47, AT: 0.64, TR: 0.82, AN: 1 };

export function zoneColor(zone: ZoneName): string {
  // Session 35: solid steps (mixed into surface-2, not transparent) so a zone reads the same on any surface.
  return `color-mix(in oklab, var(--accent) ${OPACITIES[zone] * 100}%, var(--surface-2))`;
}

export { ZONE_NAMES };

/** Which zone a bpm value falls in, given each zone's lower bound in bpm *as the server computed it* (session 33: the browser
 * holds no zone maths — no %, no heart-rate reserve — only this lookup against the workout's own stored bounds). Below UT2's
 * bound reads UT2, as on the server; no bounds (no max HR) = no zone. */
export function zoneForBpm(hr: number | null | undefined, boundsBpm: Record<string, number>): ZoneName | null {
  if (hr == null || boundsBpm.UT2 == null) return null;
  let zone: ZoneName = ZONE_NAMES[0];
  for (const name of ZONE_NAMES) {
    if (boundsBpm[name] != null && hr >= boundsBpm[name]) zone = name;
  }
  return zone;
}
