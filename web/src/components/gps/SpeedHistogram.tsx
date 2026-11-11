import { formatSpeedKmh } from "../../lib/gpsFormat";
import type { RouteHistory } from "../../lib/types";

const W = 320;
const H = 110;
const PAD = 8;

/** A static count-per-bin chart of each session's average moving speed — dependency-free SVG, no
 * pan/zoom (the PieceTrendMiniChart precedent). The summary figures and every bar's count are
 * also in text, so nothing depends on seeing the bars. */
export function SpeedHistogram({ dist }: { dist: NonNullable<RouteHistory["stats"]["speed_distribution"]> }) {
  const bins = dist.histogram;
  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const bw = (W - PAD * 2) / bins.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Distribution of average speed across ${dist.n} sessions`} data-testid="speed-histogram">
        {bins.map((b, i) => {
          const h = (b.count / maxCount) * (H - 34);
          return (
            <g key={i}>
              <rect x={PAD + i * bw + 3} width={Math.max(bw - 6, 2)} y={H - 20 - h} height={h} rx={3} fill="var(--accent)" opacity={0.75} />
              {b.count > 0 && (
                <text x={PAD + i * bw + bw / 2} y={H - 24 - h} fontSize={10} textAnchor="middle" fill="var(--text-secondary)" className="font-mono-nums">
                  {b.count}
                </text>
              )}
            </g>
          );
        })}
        <text x={PAD} y={H - 5} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
          {formatSpeedKmh(dist.min)}
        </text>
        <text x={W - PAD} y={H - 5} fontSize={10} textAnchor="end" fill="var(--text-tertiary)" className="font-mono-nums">
          {formatSpeedKmh(dist.max)}
        </text>
      </svg>
      <p className="mt-1 text-xs text-text-tertiary">
        {dist.n} session{dist.n === 1 ? "" : "s"}: median {formatSpeedKmh(dist.median)} (middle half {formatSpeedKmh(dist.p25)}–{formatSpeedKmh(dist.p75)}). {dist.basis}.
      </p>
    </div>
  );
}
