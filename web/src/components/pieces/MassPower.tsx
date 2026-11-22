import { formatShortDate } from "../../lib/format";
import type { BodyMassPower } from "../../lib/types";

export const WAP_UNIT = "W/kg²ᐟ³";
export const WAP_EXPLAINER =
  "Weight-adjusted power is average watts ÷ body mass^⅔. It adjusts power for size, comparing lighter and heavier rowers more fairly than W/kg; your raw watts are unchanged.";

/** Session 34: W/kg and weight-adjusted power (W/kg^(2/3)) beside the raw watts, both from the server (computed with the weigh-in that
 *  belongs to the effort's own day — never today's). Rowing only; renders nothing for a bike. */
export function MassPower({ watts, mass, modality = "rowing_erg", compact = false }: { watts: number | null | undefined; mass: BodyMassPower; modality?: string; compact?: boolean }) {
  if (modality !== "rowing_erg" || watts == null) return null;
  if (mass.weight_adjusted_watts == null) {
    return (
      <p className="text-xs text-text-tertiary" data-testid="mass-power-unavailable">
        Weight-adjusted power: — needs a weigh-in from the 30 days before this effort (or the week after).
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1" data-testid="mass-power">
      <p className="font-mono-nums text-sm text-text-primary">
        <span data-testid="mass-power-wap">{mass.weight_adjusted_watts.toFixed(2)}</span> {WAP_UNIT}
        {mass.w_per_kg != null && <span className="text-text-secondary"> · {mass.w_per_kg.toFixed(2)} W/kg</span>}
        <span className="text-text-secondary"> · {Math.round(watts)} W</span>
      </p>
      {!compact && (
        <p className="text-xs text-text-tertiary">
          {WAP_EXPLAINER} Weigh-in used: {mass.weight_kg_used?.toFixed(1)} kg{mass.weight_date ? ` on ${formatShortDate(mass.weight_date)}` : ""}.
        </p>
      )}
    </div>
  );
}
