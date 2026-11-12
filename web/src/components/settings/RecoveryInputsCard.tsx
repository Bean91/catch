import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Settings } from "../../lib/types";
import { saveSettings } from "../../lib/api";
import { Card } from "../ui/Card";

const SIGNALS = ["hrv_rmssd", "resting_hr", "sleep_seconds"] as const;
const SOURCES = [
  { id: "garmin", label: "Garmin" },
  { id: "whoop", label: "Whoop" },
] as const;

/** Which device's number wins when both Garmin and Whoop have one. Values are never averaged:
 *  exactly one provider supplies each input per day (docs/analytics.md §30). */
export function RecoveryInputsCard({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient();
  const current = settings.wellness_priority?.hrv_rmssd?.[0] ?? "garmin";
  const save = useMutation({
    mutationFn: (first: string) => {
      const order = [first, ...SOURCES.map((s) => s.id).filter((s) => s !== first)];
      return saveSettings({ wellness_priority: Object.fromEntries(SIGNALS.map((s) => [s, order])) } as Partial<Settings>);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["settings"], updated);
      queryClient.invalidateQueries({ queryKey: ["today"] });
    },
  });

  return (
    <Card title="Recovery inputs">
      <div className="flex flex-col gap-3">
        <p className="text-sm text-text-secondary">
          When both Garmin and Whoop report overnight HRV, resting heart rate or sleep, Catch uses one device's number, never an average. Catch's
          recovery score is its own formula and never uses Whoop's recovery score.
        </p>
        <div role="radiogroup" aria-label="Preferred device" className="flex gap-2">
          {SOURCES.map((s) => (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={current === s.id}
              onClick={() => current !== s.id && save.mutate(s.id)}
              disabled={save.isPending}
              className={`min-h-11 rounded-md border px-4 text-sm font-medium transition-colors ${
                current === s.id ? "border-accent text-accent" : "border-border text-text-tertiary"
              }`}
            >
              {current === s.id ? "● " : "○ "}
              {s.label} first
            </button>
          ))}
        </div>
        <p className="text-xs text-text-tertiary">
          Switching devices can make the baseline mix two sources for about a week; the recovery details say when that's the case. Skin temperature
          only comes from Whoop.
        </p>
      </div>
    </Card>
  );
}
