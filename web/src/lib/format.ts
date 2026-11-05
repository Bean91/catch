// Round to tenths *before* splitting into minutes/seconds — otherwise 119.96 renders as
// "1:60.0" instead of "2:00.0" (the seconds component rounding up past 60 independently).
// Generic clock-with-tenths formatting: used for /500m splits (formatSplit below) and
// equally for any other duration that should read as m:ss.t, e.g. a predicted 2k time —
// the task spec's "splits always m:ss.t" rule applies to on-the-water time generally, not
// only to the word "split."
export function formatTimeTenths(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return "—:—.—";
  const rounded = Math.round(totalSeconds * 10) / 10;
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded - minutes * 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

export function formatSplit(secondsPer500: number | null | undefined): string {
  return formatTimeTenths(secondsPer500);
}

export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return "—";
  const total = Math.round(totalSeconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function formatDistance(meters: number | null | undefined): string {
  if (meters == null) return "—";
  return `${Math.round(meters).toLocaleString()}m`;
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";
  const diffMs = Date.now() - then;
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

// `date.toISOString().slice(0, 10)` gives the *UTC* date, which is already tomorrow for
// anyone west of UTC in the evening — this app's "today" (the date pickers, the day view
// default, "copy yesterday") must always mean the browser's own local calendar day.
export function localDateString(d: Date = new Date()): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function formatShortDate(iso: string): string {
  // Accepts a bare "YYYY-MM-DD" (most callers, e.g. trend/sparkline points) or a full ISO
  // datetime (workout.start) — only append a time-of-day when one isn't already there, or
  // "2026-10-29T07:30:00.000Z" + "T00:00:00" would produce an unparseable string.
  const d = iso.includes("T") ? new Date(iso) : new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const BAND_LABELS: Record<string, string> = {
  green: "Green",
  yellow: "Yellow",
  red: "Red",
  calibrating: "Calibrating",
  insufficient_data: "No data",
  light: "Light",
  moderate: "Moderate",
  high: "High",
  all_out: "All out",
  undertraining: "Undertraining",
  optimal: "Optimal",
  caution: "Caution",
  high_risk: "High risk",
};

export function bandLabel(band: string | null | undefined): string {
  if (!band) return "No data";
  return BAND_LABELS[band] ?? band;
}

const CATEGORY_LABELS: Record<string, string> = { erg: "Erg", on_water: "On-water", strength: "Strength", other: "Other" };

export function categoryLabel(category: string | null | undefined): string {
  if (!category) return "Other";
  return CATEGORY_LABELS[category] ?? category;
}

const TYPE_LABELS: Record<string, string> = {
  rowing_v2: "On-water row",
  indoor_rowing: "Erg",
  strength_training: "Strength",
  indoor_cycling: "Indoor bike",
  rower: "Erg (row)",
  skierg: "Erg (ski)",
  bike: "Erg (bike)",
  dynamic: "Erg (dynamic)",
  slides: "Erg (slides)",
  multierg: "Erg (multi)",
  water: "On-water",
  paddle: "On-water (paddle)",
  snow: "Snow",
  rollerski: "Roller ski",
};

export function activityTypeLabel(type: string | null | undefined): string {
  if (!type) return "Workout";
  return TYPE_LABELS[type] ?? type.replace(/_/g, " ");
}
