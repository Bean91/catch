import { Link } from "react-router-dom";
import type { ErgPiece, Predicted2k } from "../../lib/types";
import { bandLabel, formatDistance, formatDuration, formatSplit, formatTimeTenths } from "../../lib/format";
import { BandBadge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";

export function ErgCard({ erg, predicted2k }: { erg: ErgPiece | null; predicted2k: Predicted2k }) {
  const avgSplit = erg?.duration && erg?.distance ? (erg.duration / erg.distance) * 500 : null;

  return (
    <Card title="Latest erg piece">
      {erg ? (
        <>
          <Link to={`/workouts/${erg.canonical_id}`} className="grid grid-cols-2 gap-3 rounded-md transition-opacity hover:opacity-80 sm:grid-cols-3">
            <Stat label="Distance" value={formatDistance(erg.distance)} />
            <Stat label="Time" value={formatDuration(erg.duration)} />
            <Stat label="Avg split" value={`${formatSplit(avgSplit)} /500m`} />
            <Stat label="Rate" value={erg.stroke_rate != null ? `${erg.stroke_rate.toFixed(0)} spm` : "—"} />
            <Stat label="Watts" value={erg.avg_power != null ? erg.avg_power.toFixed(0) : "—"} />
            <Stat label="W/kg" value={erg.w_per_kg != null ? erg.w_per_kg.toFixed(2) : "—"} />
          </Link>
        </>
      ) : (
        <EmptyState message="No Concept2 results synced yet." />
      )}

      <div className="mt-4 border-t border-border pt-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-tertiary">Predicted 2k</span>
          {predicted2k.band !== "insufficient_data" && (
            <BandBadge band={predicted2k.band === "high" ? "green" : predicted2k.band === "moderate" ? "yellow" : "red"} label={bandLabel(predicted2k.band)} />
          )}
        </div>
        {predicted2k.value != null ? (
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-mono-nums text-2xl font-semibold text-text-primary">
              {formatTimeTenths(predicted2k.predicted_time_s)}
            </span>
            {predicted2k.range && (
              // Range shown as 2k times (pace * 4), matching the headline number's unit —
              // not /500m paces sitting next to a total time, which reads as two different
              // quantities at a glance.
              <span className="font-mono-nums text-xs text-text-tertiary">
                ({formatTimeTenths(predicted2k.range[0] * 4)}–{formatTimeTenths(predicted2k.range[1] * 4)})
              </span>
            )}
          </div>
        ) : (
          <p className="mt-1 text-sm text-text-tertiary">Not enough recent continuous pieces to predict yet.</p>
        )}
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-text-tertiary">{label}</div>
      <div className="font-mono-nums text-base font-medium text-text-primary">{value}</div>
    </div>
  );
}
