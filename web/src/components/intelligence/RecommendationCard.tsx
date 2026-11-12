import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { dismissRecommendation, rateRecommendation, saveRecommendation } from "../../lib/api";
import { BandBadge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";
import type { Recommendation } from "../../lib/types";

const TYPE_LABELS: Record<string, string> = {
  training_suggestion: "Training suggestion",
  recovery_suggestion: "Recovery suggestion",
  data_quality_warning: "Data-quality warning",
  overload_warning: "Overload warning",
  plan_review: "Plan review",
};

const TYPE_BAND: Record<string, string> = {
  training_suggestion: "green",
  recovery_suggestion: "yellow",
  data_quality_warning: "calibrating",
  overload_warning: "red",
  // A prompt to look at the plan, not a verdict on the athlete: neutral, never red.
  plan_review: "calibrating",
};

function RecommendationRow({ rec }: { rec: Recommendation }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["recommendations"] });

  const dismiss = useMutation({ mutationFn: () => dismissRecommendation(rec.id), onSuccess: invalidate });
  const save = useMutation({ mutationFn: (saved: boolean) => saveRecommendation(rec.id, saved), onSuccess: invalidate });
  const rate = useMutation({ mutationFn: (rating: "useful" | "not_useful") => rateRecommendation(rec.id, rating), onSuccess: invalidate });

  return (
    <div className="border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <BandBadge band={TYPE_BAND[rec.type]} label={TYPE_LABELS[rec.type] ?? rec.type} />
        <span className="text-xs text-text-tertiary">{rec.confidence.replace("_", " ")} confidence</span>
      </div>
      <p className="text-sm font-medium text-text-primary">{rec.title}</p>
      <p className="mt-1 text-sm text-text-secondary">{rec.body}</p>

      <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1 min-h-8 text-xs text-text-tertiary underline">
        {open ? "Hide data" : "Show underlying data"}
      </button>
      {open && (
        <ul className="mt-2 flex flex-col gap-1 rounded-md border border-border bg-surface-2 p-2.5 text-xs text-text-secondary">
          {rec.evidence.map((e, i) => (
            <li key={i} className="font-mono-nums">
              {e.label}: {typeof e.value === "object" ? JSON.stringify(e.value) : String(e.value)}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate()}
          className="min-h-11 rounded-md border border-border px-3 text-sm text-text-primary disabled:opacity-50"
        >
          Dismiss
        </button>
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate(!rec.saved)}
          className="min-h-11 rounded-md border border-border px-3 text-sm text-text-primary disabled:opacity-50"
        >
          {rec.saved ? "Saved" : "Save"}
        </button>
        <button
          type="button"
          disabled={rate.isPending}
          onClick={() => rate.mutate("useful")}
          className={`min-h-11 rounded-md border px-3 text-sm disabled:opacity-50 ${rec.rating === "useful" ? "border-accent text-accent" : "border-border text-text-primary"}`}
        >
          Useful
        </button>
        <button
          type="button"
          disabled={rate.isPending}
          onClick={() => rate.mutate("not_useful")}
          className={`min-h-11 rounded-md border px-3 text-sm disabled:opacity-50 ${rec.rating === "not_useful" ? "border-accent text-accent" : "border-border text-text-primary"}`}
        >
          Not useful
        </button>
      </div>
    </div>
  );
}

export function RecommendationsCard({ recommendations }: { recommendations: Recommendation[] }) {
  if (recommendations.length === 0) {
    return <EmptyState message="No active recommendations right now." />;
  }
  return (
    <div className="flex flex-col gap-3">
      {recommendations.map((r) => (
        <RecommendationRow key={r.id} rec={r} />
      ))}
    </div>
  );
}
