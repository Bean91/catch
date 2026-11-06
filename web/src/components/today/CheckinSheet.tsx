import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { postCheckin } from "../../lib/api";
import type { CheckIn } from "../../lib/types";

const NIGGLE_AREAS = ["Left knee", "Right knee", "Lower back", "Left shoulder", "Right shoulder", "Hamstring", "Rib", "Other"];

function Slider({ label, value, onChange, lowLabel, highLabel }: { label: string; value: number; onChange: (v: number) => void; lowLabel: string; highLabel: string }) {
  return (
    <label className="flex flex-col gap-2">
      <span className="flex items-center justify-between text-sm font-medium text-text-primary">
        {label}
        <span className="font-mono-nums text-text-secondary">{value}/5</span>
      </span>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        // Larger hit area than the default thumb — this sheet is meant for a fast morning
        // tap, not fine-grained adjustment, so DESIGN.md's 44px touch-target rule matters
        // more here than on NotesBox's RPE slider.
        className="h-11 w-full accent-[var(--accent)]"
      />
      <span className="flex justify-between text-xs text-text-tertiary">
        <span>{lowLabel}</span>
        <span>{highLabel}</span>
      </span>
    </label>
  );
}

/** Task Part A.1: 4 sliders + an optional niggle (body area + 1-3 severity) + a free-text
 * note, one screen, dismissible, editable later the same day. Soreness/stress/sleep-quality
 * sliders read 1=none/low/poor -> 5=severe/high/great; mood reads 1=low -> 5=high (see
 * catch/analytics/checkin.py's docstring for the matching scoring direction). */
export function CheckinSheet({ open, onOpenChange, existing }: { open: boolean; onOpenChange: (open: boolean) => void; existing: CheckIn | null }) {
  const queryClient = useQueryClient();
  const [soreness, setSoreness] = useState(3);
  const [stress, setStress] = useState(3);
  const [mood, setMood] = useState(3);
  const [sleepQuality, setSleepQuality] = useState(3);
  const [niggleArea, setNiggleArea] = useState<string>("");
  const [niggleSeverity, setNiggleSeverity] = useState<number | null>(null);
  const [note, setNote] = useState("");

  // Prefill from whatever's already logged today — reopening to edit later the same day
  // must never show blank defaults over real saved values.
  useEffect(() => {
    if (!open) return;
    setSoreness(existing?.soreness ?? 3);
    setStress(existing?.stress ?? 3);
    setMood(existing?.mood ?? 3);
    setSleepQuality(existing?.sleep_quality ?? 3);
    setNiggleArea(existing?.niggle_area ?? "");
    setNiggleSeverity(existing?.niggle_severity ?? null);
    setNote(existing?.note ?? "");
  }, [open, existing]);

  const save = useMutation({
    mutationFn: () =>
      postCheckin({
        soreness,
        stress,
        mood,
        sleep_quality: sleepQuality,
        niggle_area: niggleArea || null,
        niggle_severity: niggleArea ? niggleSeverity : null,
        note: note || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["today"] });
      queryClient.invalidateQueries({ queryKey: ["today-checkin"] });
      onOpenChange(false);
    },
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        {/* z-30, matching AddFoodDialog/PhotoEstimateDialog's convention — without it this
            sheet's bottom edge (where Save/Skip live) rendered *under* BottomNav's z-20 at
            390px, since a bottom-anchored sheet is the first dialog in this app to actually
            reach that zone (every prior Dialog.Content was centered and never got close).
            Caught by screenshot, not by the touch suite (Radix traps focus/clicks correctly
            regardless of paint order — this was purely visual). */}
        <Dialog.Content className="fixed inset-x-0 bottom-0 z-30 max-h-[88vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,420px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border">
          <Dialog.Title className="text-base font-semibold text-text-primary">Morning check-in</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">Ten seconds — this feeds your recovery number and nothing else.</Dialog.Description>

          <div className="mt-5 flex flex-col gap-5">
            <Slider label="Muscle soreness" value={soreness} onChange={setSoreness} lowLabel="None" highLabel="Severe" />
            <Slider label="Life stress" value={stress} onChange={setStress} lowLabel="Low" highLabel="High" />
            <Slider label="Mood / motivation" value={mood} onChange={setMood} lowLabel="Low" highLabel="High" />
            <Slider label="Sleep quality" value={sleepQuality} onChange={setSleepQuality} lowLabel="Poor" highLabel="Great" />

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-text-primary">Niggle (optional)</span>
              <select
                value={niggleArea}
                onChange={(e) => {
                  setNiggleArea(e.target.value);
                  if (e.target.value && niggleSeverity == null) setNiggleSeverity(1);
                }}
                className="min-h-11 w-full rounded-md border border-border bg-bg px-3 text-sm text-text-primary"
              >
                <option value="">No niggle today</option>
                {NIGGLE_AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
              {niggleArea && (
                <div className="flex gap-2" role="radiogroup" aria-label="Niggle severity">
                  {[1, 2, 3].map((s) => (
                    <button
                      key={s}
                      type="button"
                      role="radio"
                      aria-checked={niggleSeverity === s}
                      onClick={() => setNiggleSeverity(s)}
                      className={`min-h-11 flex-1 rounded-md border text-sm font-medium transition-colors ${
                        niggleSeverity === s ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"
                      }`}
                    >
                      {s === 1 ? "Mild" : s === 2 ? "Moderate" : "Severe"}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Anything else? (optional)"
              rows={2}
              className="w-full resize-none rounded-md border border-border bg-surface-2 p-3 text-sm text-text-primary placeholder:text-text-tertiary focus-visible:outline-none"
            />
          </div>

          <div className="mt-5 flex gap-3">
            <Dialog.Close asChild>
              <button type="button" className="min-h-11 flex-1 rounded-md border border-border text-sm font-medium text-text-primary">
                Skip for today
              </button>
            </Dialog.Close>
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="min-h-11 flex-1 rounded-md bg-accent text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
