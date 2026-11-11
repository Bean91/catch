import { SOURCE_LABEL } from "../../lib/gpsFormat";
import type { GpsSource } from "../../lib/types";

const TITLE: Record<GpsSource, string> = {
  gps_derived: "Computed from this activity's own GPS fixes (not reported by Garmin).",
  provider: "Reported by Garmin's own summary.",
  manual: "Entered by you.",
};

/** Marks where a figure came from, in words — never colour alone. */
export function GpsBadge({ source, className = "" }: { source: GpsSource; className?: string }) {
  return (
    <span
      title={TITLE[source]}
      data-source={source}
      className={`inline-flex items-center rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium leading-none text-text-tertiary ${className}`}
    >
      {SOURCE_LABEL[source]}
    </span>
  );
}
