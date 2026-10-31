import { motion } from "framer-motion";
import type { VolumeWeek } from "../../lib/types";
import { ZONE_NAMES } from "../../lib/types";
import { formatShortDate } from "../../lib/format";
import { zoneColor } from "../../lib/zoneColors";
import { useReducedMotion } from "../../lib/useReducedMotion";

const WIDTH = 600;
const HEIGHT = 220;
const PAD_X = 12;
const PAD_TOP = 12;
const PAD_BOTTOM = 24;

export function WeeklyVolumeBars({ weeks }: { weeks: VolumeWeek[] }) {
  const reduced = useReducedMotion();
  const totals = weeks.map((w) => ZONE_NAMES.reduce((sum, z) => sum + w.zones[z], 0));
  const max = Math.max(...totals, 1);
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const barWidth = ((WIDTH - PAD_X * 2) / weeks.length) * 0.6;
  const slot = (WIDTH - PAD_X * 2) / weeks.length;
  const anyEstimated = weeks.some((w) => w.estimated);

  if (totals.every((t) => t === 0)) {
    return <div className="flex h-40 items-center justify-center text-sm text-text-tertiary">No training volume in range yet.</div>;
  }

  return (
    <div>
      <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Weekly training volume by zone">
        {weeks.map((w, i) => {
          const total = totals[i];
          const x = PAD_X + i * slot + (slot - barWidth) / 2;
          let yCursor = PAD_TOP + plotHeight;
          return (
            <g key={w.week_start}>
              {ZONE_NAMES.map((z) => {
                const secs = w.zones[z];
                const h = total > 0 ? (secs / max) * plotHeight : 0;
                yCursor -= h;
                return h > 0 ? (
                  <motion.rect
                    key={z}
                    x={x}
                    width={barWidth}
                    y={yCursor}
                    height={h}
                    fill={zoneColor(z)}
                    initial={reduced ? { opacity: 1 } : { opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: reduced ? 0 : 0.5, delay: reduced ? 0 : i * 0.03 }}
                  />
                ) : null;
              })}
              {w.estimated && total > 0 && (
                <text x={x + barWidth / 2} y={PAD_TOP + plotHeight - (total / max) * plotHeight - 4} fontSize={9} fill="var(--text-tertiary)" textAnchor="middle">
                  ~
                </text>
              )}
              {i % Math.max(1, Math.ceil(weeks.length / 8)) === 0 && (
                <text x={x + barWidth / 2} y={HEIGHT - 6} fontSize={9} fill="var(--text-tertiary)" textAnchor="middle">
                  {formatShortDate(w.week_start)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-tertiary">
        {ZONE_NAMES.map((z) => (
          <span key={z} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: zoneColor(z) }} />
            {z}
          </span>
        ))}
        {anyEstimated && <span className="ml-auto">~ estimated from average HR (no per-stroke data)</span>}
      </div>
    </div>
  );
}
