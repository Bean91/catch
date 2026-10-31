import type { PersonalBests } from "../../lib/types";
import { formatDistance, formatDuration, formatShortDate, formatSplit } from "../../lib/format";

const ORDER = ["500m", "1000m", "2000m", "5000m", "6000m", "30min", "60min"];

export function PbTable({ pbs }: { pbs: PersonalBests }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-text-tertiary">
          <th className="py-1 font-normal">Piece</th>
          <th className="py-1 font-normal">Result</th>
          <th className="py-1 font-normal">Split</th>
          <th className="py-1 font-normal">Date</th>
        </tr>
      </thead>
      <tbody>
        {ORDER.map((key) => {
          const entry = pbs[key];
          const isTimed = key.endsWith("min");
          return (
            <tr key={key} className="text-text-primary">
              <td className="py-1.5">{key}</td>
              <td className="font-mono-nums py-1.5">
                {entry == null ? "—" : isTimed ? formatDistance(entry.distance_m) : formatDuration(entry.duration_s)}
              </td>
              <td className="font-mono-nums py-1.5">{entry?.pace_s_per_500 != null ? `${formatSplit(entry.pace_s_per_500)}/500m` : "—"}</td>
              <td className="py-1.5 text-text-tertiary">{entry?.date ? formatShortDate(entry.date) : "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
