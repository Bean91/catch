import type { TrendMetric } from "./types";

/**
 * One colour per measurement, everywhere it is drawn (session 35; DESIGN.md "Metric palette"). The values are token references, so
 * light and dark each use their own validated step. Status (recovery/strain bands) is never one of these.
 */
export const METRIC_COLOR = {
  hr: "var(--metric-hr)",
  power: "var(--metric-power)",
  pace: "var(--metric-pace)",
  rate: "var(--metric-rate)",
  load: "var(--metric-load)",
  sleep: "var(--metric-sleep)",
} as const;

export type MetricKind = keyof typeof METRIC_COLOR;

/** Which colour a trend metric is drawn in. Wellness signals that come from the heart use HR's; performance uses power/pace. */
export function trendMetricColor(metric: TrendMetric | string): string {
  switch (metric) {
    case "resting_hr":
    case "hrv_rmssd":
      return METRIC_COLOR.hr;
    case "w_per_kg":
    case "weight_adjusted_watts":
      return METRIC_COLOR.power;
    case "predicted_2k":
      return METRIC_COLOR.pace;
    case "sleep_score":
    case "checkin_sleep_quality":
      return METRIC_COLOR.sleep;
    default:
      return METRIC_COLOR.load;
  }
}
