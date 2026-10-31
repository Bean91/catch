import { ZONE_NAMES, type ZoneName } from "./types";

// Training zones are a magnitude breakdown (effort, low to high), not a status — same
// reasoning as SleepCard's stage ramp: kept off the green/yellow/red band palette (reserved
// for recovery/strain/load) and ramped through one accent hue instead, lightest at the
// easiest zone.
const OPACITIES: Record<ZoneName, number> = { UT2: 0.22, UT1: 0.4, AT: 0.58, TR: 0.78, AN: 1 };

export function zoneColor(zone: ZoneName): string {
  return `color-mix(in oklab, var(--accent) ${OPACITIES[zone] * 100}%, transparent)`;
}

export { ZONE_NAMES };
