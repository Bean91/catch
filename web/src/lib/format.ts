// Round to tenths *before* splitting into minutes/seconds — otherwise 119.96 renders as
// "1:60.0" instead of "2:00.0" (the seconds component rounding up past 60 independently).
export function formatSplit(secondsPer500: number | null | undefined): string {
  if (secondsPer500 == null || !Number.isFinite(secondsPer500)) return "—:—.—";
  const rounded = Math.round(secondsPer500 * 10) / 10;
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded - minutes * 60;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
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

export function formatShortDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
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
