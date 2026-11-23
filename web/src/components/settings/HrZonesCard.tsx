import { useQuery } from "@tanstack/react-query";
import { fetchZones } from "../../lib/api";
import { formatNumber, formatShortDate } from "../../lib/format";
import type { Settings } from "../../lib/types";
import { Card } from "../ui/Card";
import { ErrorState } from "../ui/EmptyState";
import { controlSkin } from "../ui/Field";

const ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"] as const;
const inputCls = `${controlSkin} min-h-11 font-mono-nums w-20 px-2`;

/** Session 33: heart-rate zones — the method, the resting and max heart rate they use (and where each came from), the boundaries
 * in bpm. Every number in the bpm column comes from the server (GET /api/zones); the browser does no zone maths. Edits go through
 * the page's one Save, like the rest of Settings, and past workouts are recalculated in the background. */
export function HrZonesCard({ form, update }: { form: Settings; update: <K extends keyof Settings>(key: K, value: Settings[K]) => void }) {
  const zonesQuery = useQuery({ queryKey: ["zones"], queryFn: fetchZones, staleTime: 5 * 60_000 });
  const view = zonesQuery.data;
  const basis = view?.basis;
  const method = form.hr_zone_method ?? "hrr";
  const pctKey = method === "hrr" ? "hrr_pct" : "hr_pct";
  const pctLabel = method === "hrr" ? "% of HR reserve" : "% of max HR";

  return (
    <Card title="Heart-rate zones">
      <div className="flex flex-col gap-4" data-testid="hr-zones-card">
        <div role="radiogroup" aria-label="How zones are set" className="flex flex-col gap-2">
          {(
            [
              ["hrr", "Heart-rate reserve", "Uses your resting and max heart rate (Karvonen): resting + (max − resting) × %."],
              ["max_pct", "% of max heart rate", "Uses your max heart rate only."],
            ] as const
          ).map(([value, label, help]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={method === value}
              onClick={() => update("hr_zone_method", value)}
              className={`flex min-h-11 flex-col items-start rounded-md border px-3 py-2 text-left text-sm ${method === value ? "border-accent bg-accent/10" : "border-border"}`}
            >
              <span className="font-medium text-text-primary">
                <span aria-hidden="true">{method === value ? "● " : "○ "}</span>
                {label}
              </span>
              <span className="text-xs text-text-tertiary">{help}</span>
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
            Max heart rate
            <input
              type="number"
              inputMode="numeric"
              aria-label="Max heart rate"
              value={form.max_hr ?? ""}
              onChange={(e) => update("max_hr", e.target.value ? Number(e.target.value) : null)}
              className={inputCls}
            />
            <span className="text-xs text-text-tertiary">bpm</span>
          </label>
          {form.max_hr == null && <p className="text-xs text-text-secondary">Catch won't guess a max heart rate — enter yours to see heart-rate zones.</p>}
          {view?.observed_max_hr && view.observed_max_hr.value !== form.max_hr && (
            <p className="text-xs text-text-tertiary">
              Highest heart rate your workouts recorded in the last year: <span className="font-mono-nums text-text-primary">{view.observed_max_hr.value}</span> bpm
              {view.observed_max_hr.date && <> ({formatShortDate(view.observed_max_hr.date)})</>}.{" "}
              <button type="button" onClick={() => update("max_hr", view.observed_max_hr!.value)} className="min-h-9 font-medium text-accent hover:underline">
                Use this
              </button>{" "}
              — only if it was a real all-out effort; a sensor spike reads high.
            </p>
          )}
        </div>

        {method === "hrr" && (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm text-text-secondary" data-testid="rhr-used">
              {basis && basis.resting_hr != null && basis.rhr_source !== "setting" && form.resting_hr == null ? (
                <>
                  Resting heart rate used: <span className="font-mono-nums text-text-primary">{formatNumber(basis.resting_hr)}</span> bpm — the median of{" "}
                  {basis.rhr_readings} mornings{basis.rhr_window && <> ({formatShortDate(basis.rhr_window[0])}–{formatShortDate(basis.rhr_window[1])})</>}
                  {basis.rhr_source === "measured_stale" ? ", the most recent available" : ""}. Each workout uses the median of the 14 days before it.
                </>
              ) : form.resting_hr != null ? (
                <>Resting heart rate used: your own value below, for every workout.</>
              ) : (
                <>No resting heart rate measured yet — zones use % of max heart rate until a watch or ring reports one, or you enter it.</>
              )}
            </p>
            <label className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
              Your resting heart rate (optional)
              <input
                type="number"
                inputMode="numeric"
                aria-label="Resting heart rate"
                value={form.resting_hr ?? ""}
                placeholder="measured"
                onChange={(e) => update("resting_hr", e.target.value ? Number(e.target.value) : null)}
                className={inputCls}
              />
              {form.resting_hr != null && (
                <button type="button" onClick={() => update("resting_hr", null)} className="min-h-11 text-xs font-medium text-accent hover:underline">
                  Use the measured value
                </button>
              )}
            </label>
          </div>
        )}

        {basis?.reason && <p className="rounded-md bg-surface-2 p-2 text-xs text-text-secondary">{basis.reason}</p>}

        <div className="overflow-x-auto">
          <table className="w-full max-w-md text-sm">
            <thead>
              <tr className="text-left text-xs text-text-tertiary">
                <th className="py-1 font-normal">Zone</th>
                <th className="py-1 font-normal">{pctLabel} (from)</th>
                <th className="py-1 font-normal">bpm</th>
              </tr>
            </thead>
            <tbody>
              {ZONE_ORDER.map((zone, i) => {
                const row = view?.zones.find((z) => z.zone === zone);
                return (
                  <tr key={zone}>
                    <td className="py-1.5 text-text-primary">{zone}</td>
                    <td className="py-1.5">
                      <input
                        type="number"
                        aria-label={`${zone} ${pctLabel}`}
                        value={form.zones[pctKey]?.[zone] ?? ""}
                        onChange={(e) => update("zones", { ...form.zones, [pctKey]: { ...form.zones[pctKey], [zone]: Number(e.target.value) } })}
                        className={inputCls}
                      />
                    </td>
                    <td className="font-mono-nums py-1.5 text-text-secondary">
                      {row?.hr_lo != null ? `${formatNumber(row.hr_lo)}${row.hr_hi != null ? `–${formatNumber(row.hr_hi)}` : "+"}` : "—"}
                      {i === 0 && row?.hr_lo != null && <span className="sr-only"> (and below)</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {zonesQuery.isError && <ErrorState message="Couldn't load the zone boundaries." onRetry={() => zonesQuery.refetch()} />}
        <p className="text-xs text-text-tertiary">
          The bpm column shows your saved values. Saving a change recalculates past workouts' zones in the background; recorded heart rates are never
          changed. Defaults follow the GB Rowing training bands — confirm with your coach.
        </p>
      </div>
    </Card>
  );
}
