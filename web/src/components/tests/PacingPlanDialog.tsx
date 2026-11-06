import * as Dialog from "@radix-ui/react-dialog";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { makePacingPlan } from "../../lib/api";
import { formatSplit } from "../../lib/format";
import { ERG_TEST_TYPES, type ErgTestType, type PacingPlan, type PacingStyle } from "../../lib/types";

const STYLE_LABELS: { value: PacingStyle; label: string }[] = [
  { value: "even", label: "Even" },
  { value: "fast_start_settle", label: "Fast start, settle" },
  { value: "negative_split", label: "Negative split" },
];

// No m:ss -> seconds parser exists elsewhere in the app yet (Event.goal_time is stored as a
// free-text string, never parsed) — small enough to keep local rather than add to format.ts
// for one caller.
function parseGoalTime(input: string): number | null {
  const match = input.trim().match(/^(\d+):(\d{1,2}(?:\.\d+)?)$/);
  if (!match) return null;
  const minutes = Number(match[1]);
  const seconds = Number(match[2]);
  if (!Number.isFinite(minutes) || !Number.isFinite(seconds) || seconds >= 60) return null;
  return minutes * 60 + seconds;
}

const STANDARD_DISTANCES: Partial<Record<ErgTestType, number>> = { "500m": 500, "1000m": 1000, "2000m": 2000, "5000m": 5000, "6000m": 6000 };

export function PacingPlanDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [testType, setTestType] = useState<ErgTestType>("2000m");
  const [goalTimeText, setGoalTimeText] = useState("7:30");
  const [style, setStyle] = useState<PacingStyle>("even");
  const [distanceM, setDistanceM] = useState("5000");
  const [plan, setPlan] = useState<PacingPlan | null>(null);
  const [savedEventName, setSavedEventName] = useState<string | null>(null);

  const needsDistance = STANDARD_DISTANCES[testType] == null;
  const goalTimeS = parseGoalTime(goalTimeText);

  const build = useMutation({
    mutationFn: () =>
      makePacingPlan({
        test_type: testType,
        goal_time_s: goalTimeS!,
        style,
        distance_m: needsDistance ? Number(distanceM) || undefined : undefined,
        save_to_next_event: true,
      }),
    onSuccess: ({ plan: p, saved_to_event }) => {
      setPlan(p);
      setSavedEventName(saved_to_event?.name ?? null);
    },
  });

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) {
          setPlan(null);
          setSavedEventName(null);
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-30 max-h-[88vh] w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="text-base font-semibold text-text-primary">Build a pacing plan</Dialog.Title>

          {!plan ? (
            <div className="mt-4 flex flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary">Test type</span>
                <select value={testType} onChange={(e) => setTestType(e.target.value as ErgTestType)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-sm text-text-primary">
                  {ERG_TEST_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>

              {needsDistance && (
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium text-text-primary">
                    {testType === "30min_r20" || testType === "60min" ? "Target distance to cover (m)" : "Distance (m)"}
                  </span>
                  <input
                    type="number"
                    inputMode="numeric"
                    value={distanceM}
                    onChange={(e) => setDistanceM(e.target.value)}
                    className="min-h-11 rounded-md border border-border bg-bg px-3 font-mono-nums text-sm text-text-primary"
                  />
                </label>
              )}

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary">Goal time (m:ss)</span>
                <input
                  value={goalTimeText}
                  onChange={(e) => setGoalTimeText(e.target.value)}
                  placeholder="7:30"
                  className="min-h-11 rounded-md border border-border bg-bg px-3 font-mono-nums text-sm text-text-primary"
                />
                {goalTimeText && goalTimeS == null && <span className="text-xs text-[var(--band-red-text)]">Use m:ss, e.g. 7:30</span>}
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary">Pacing style</span>
                <select value={style} onChange={(e) => setStyle(e.target.value as PacingStyle)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-sm text-text-primary">
                  {STYLE_LABELS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                disabled={goalTimeS == null || build.isPending}
                onClick={() => build.mutate()}
                className="min-h-11 rounded-md bg-accent text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {build.isPending ? "Building…" : "Build plan"}
              </button>
            </div>
          ) : (
            <div className="mt-4 flex flex-col gap-3">
              <p className="text-sm text-text-secondary">{plan.explanation}</p>
              {savedEventName && <p className="text-xs text-text-tertiary">Saved to your next event: {savedEventName}.</p>}
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-text-tertiary">
                    <th className="py-1 font-normal">Distance</th>
                    <th className="py-1 font-normal">Split</th>
                    <th className="py-1 font-normal">Cumulative</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.splits.map((s) => (
                    <tr key={s.split_index} className="text-text-primary">
                      <td className="py-1">{s.distance_m}m</td>
                      <td className="font-mono-nums py-1">{formatSplit(s.target_split_s)}</td>
                      <td className="font-mono-nums py-1">{formatSplit(s.target_cum_s)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button type="button" onClick={() => setPlan(null)} className="min-h-11 rounded-md border border-border text-sm font-medium text-text-primary">
                Build another
              </button>
            </div>
          )}

          <Dialog.Close asChild>
            <button type="button" className="mt-4 min-h-11 w-full rounded-md border border-border text-sm font-medium text-text-primary">
              Close
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
