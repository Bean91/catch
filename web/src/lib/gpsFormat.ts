import type { GpsSource, PaceUnit } from "./types";

/** m:ss, rounded — a pace over a whole split or session doesn't need tenths. */
export function formatMmSs(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return "—";
  const total = Math.round(totalSeconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function paceUnitLabel(unit: PaceUnit): string {
  return unit === "s_per_500m" ? "/500m" : unit === "s_per_km" ? "/km" : "km/h";
}

export function formatPace(unit: PaceUnit, value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return unit === "km_per_h" ? `${value.toFixed(1)} km/h` : `${formatMmSs(value)} ${paceUnitLabel(unit)}`;
}

export function formatSpeedKmh(mps: number | null | undefined): string {
  if (mps == null || !Number.isFinite(mps)) return "—";
  return `${(mps * 3.6).toFixed(1)} km/h`;
}

export function formatKm(meters: number | null | undefined, digits = 2): string {
  if (meters == null || !Number.isFinite(meters)) return "—";
  return `${(meters / 1000).toFixed(digits)} km`;
}

export const SOURCE_LABEL: Record<GpsSource, string> = {
  gps_derived: "GPS-derived",
  provider: "Garmin-reported",
  manual: "Entered by you",
};

/** Split distances worth offering per sport (metres). */
export function splitChoices(sport: string): number[] {
  if (sport === "rowing") return [250, 500, 1000, 2000];
  if (sport === "running") return [400, 1000, 1609, 5000];
  if (sport === "cycling") return [1000, 5000, 10000];
  return [500, 1000, 5000];
}
