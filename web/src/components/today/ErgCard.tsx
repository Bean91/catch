import { Link } from "react-router-dom";
import type { ErgPiece, Predicted2k } from "../../lib/types";
import { formatDistance, formatDuration, formatShortDate, formatSplit, formatTimeTenths } from "../../lib/format";
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

      <TwoKEstimate p={predicted2k} />
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

const CONFIDENCE: Record<string, string> = { high: "High confidence", moderate: "Moderate confidence", low: "Low confidence" };

/** Session 32: an estimate is labelled as one, in words, with its range and what it was built from — and a measured 2k, when there
 * is one, is shown as its own line, never replaced by the estimate (DESIGN.md "Estimates and measurements"). */
function TwoKEstimate({ p }: { p: Predicted2k }) {
  const time = p.predicted_time_s ?? (p.value != null ? p.value * 4 : null);
  const range = p.range_s ?? (p.range ? ([p.range[0] * 4, p.range[1] * 4] as [number, number]) : null);
  const basis = (p.components ?? []).length;
  const measured = p.measured_2k?.latest ?? null;
  const confidence = p.confidence ?? p.band;
  return (
    <div className="mt-4 border-t border-border pt-3" data-testid="two-k">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs text-text-tertiary">
          Estimated 2k
          <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">estimate</span>
        </span>
        {confidence !== "insufficient_data" && <span className="text-xs text-text-secondary">{CONFIDENCE[confidence] ?? confidence}</span>}
      </div>
      {time != null ? (
        <>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono-nums text-2xl font-semibold text-text-primary">{formatTimeTenths(time)}</span>
            {range && (
              <span className="font-mono-nums text-xs text-text-tertiary">
                likely {formatTimeTenths(range[0])}–{formatTimeTenths(range[1])}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-text-tertiary">
            From {basis} recent hard effort{basis === 1 ? "" : "s"}
            {p.stale ? " — none in the last 4 months, so treat it loosely" : ""}. An estimate, not a result.
          </p>
        </>
      ) : (
        <p className="mt-1 text-sm text-text-tertiary">{p.explanation || "Not enough recent hard efforts to estimate a 2k yet."}</p>
      )}
      {measured && (
        <div className="mt-2 flex items-baseline justify-between text-xs">
          <span className="text-text-secondary">Measured 2k</span>
          <span className="font-mono-nums text-text-primary">
            {formatTimeTenths(measured.time_s)}
            <span className="ml-1 text-text-tertiary">{formatShortDate(measured.date)}</span>
          </span>
        </div>
      )}
    </div>
  );
}
