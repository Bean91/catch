import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { dismissIllness } from "../../lib/api";
import { BandBadge } from "../ui/Badge";
import { Card } from "../ui/Card";
import type { DismissReason, IllnessState } from "../../lib/types";

const SIGNAL_LABELS: Record<string, string> = {
  resting_hr: "Resting HR",
  hrv: "HRV",
  respiration: "Respiration",
  checkin: "Check-in (mood/soreness)",
};

const DISMISS_REASONS: { value: DismissReason; label: string }[] = [
  { value: "alcohol", label: "Alcohol" },
  { value: "travel", label: "Travel" },
  { value: "late_night", label: "Late night" },
  { value: "vaccine", label: "Vaccine" },
  { value: "other", label: "Other" },
];

/** Task Part B.3: shown only when illness.level !== "none" — the exact fixed wording from
 * the backend (never a locally-written diagnosis-sounding string), which signals deviated,
 * and for "likely" a visible note that the daily recommendation already caps intensity. */
export function IllnessCard({ date, illness }: { date: string; illness: IllnessState }) {
  const queryClient = useQueryClient();
  const [showDismiss, setShowDismiss] = useState(false);

  const dismiss = useMutation({
    mutationFn: (reason: DismissReason) => dismissIllness(date, reason),
    onSuccess: () => {
      setShowDismiss(false);
      queryClient.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const deviatedSignals = Object.entries(illness.signals)
    .filter(([, s]) => s.deviated)
    .map(([name]) => SIGNAL_LABELS[name] ?? name);

  return (
    <Card
      title="Illness early warning"
      action={<BandBadge band={illness.level === "likely" ? "red" : "yellow"} label={illness.level === "likely" ? "Likely" : "Watch"} />}
    >
      <p className="text-sm text-text-primary">{illness.explanation}</p>
      {deviatedSignals.length > 0 && (
        <p className="mt-2 text-xs text-text-secondary">Signals: {deviatedSignals.join(", ")}.</p>
      )}
      {illness.level === "likely" && (
        <p className="mt-2 rounded-md bg-surface-2 px-3 py-2 text-xs text-text-secondary">
          Today's recommendation is capped — no tests, no TR/AN work.
        </p>
      )}

      {!showDismiss ? (
        <button
          type="button"
          onClick={() => setShowDismiss(true)}
          className="mt-3 min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-primary"
        >
          This has an explanation…
        </button>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {DISMISS_REASONS.map((r) => (
            <button
              key={r.value}
              type="button"
              disabled={dismiss.isPending}
              onClick={() => dismiss.mutate(r.value)}
              className="min-h-11 rounded-md border border-border px-3 text-sm text-text-primary disabled:opacity-50"
            >
              {r.label}
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}
