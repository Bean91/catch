import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchNutritionTargets, saveNutritionTargets } from "../../lib/api";
import type { NutritionTargetSettings } from "../../lib/types";
import { Card } from "../ui/Card";
import { CardSkeleton } from "../ui/Skeleton";

const inputCls = "font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary";

export function NutritionTargetsCard() {
  const queryClient = useQueryClient();
  const targetsQuery = useQuery({ queryKey: ["nutrition-targets"], queryFn: fetchNutritionTargets });
  const [form, setForm] = useState<NutritionTargetSettings | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (targetsQuery.data && !dirty) setForm(targetsQuery.data.settings);
  }, [targetsQuery.data, dirty]);

  const save = useMutation({
    mutationFn: (patch: Partial<NutritionTargetSettings>) => saveNutritionTargets(patch),
    onSuccess: (data) => {
      setDirty(false);
      queryClient.setQueryData(["nutrition-targets"], data);
      queryClient.invalidateQueries({ queryKey: ["nutrition-day"] });
      queryClient.invalidateQueries({ queryKey: ["nutrition-week"] });
    },
  });

  if (targetsQuery.isLoading || !form) return <CardSkeleton lines={3} />;

  function update<K extends keyof NutritionTargetSettings>(key: K, value: NutritionTargetSettings[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
    setDirty(true);
  }

  return (
    <Card title="Nutrition targets">
      <p className="mb-3 text-xs text-text-tertiary">
        Starting points, not prescriptions — protein and carb targets scale with body weight and the day's training load; adjust
        these with a coach or dietitian.
      </p>
      <div className="flex flex-col gap-3">
        <label className="flex items-center gap-3 text-sm text-text-secondary">
          Protein (g/kg)
          <input type="number" step="0.1" min="0" value={form.protein_g_per_kg} onChange={(e) => update("protein_g_per_kg", Number(e.target.value))} className={inputCls} />
        </label>
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <p className="text-xs text-text-tertiary">Carbs (g/kg), by training tier</p>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              Rest
              <input type="number" step="0.1" min="0" value={form.carb_g_per_kg_rest} onChange={(e) => update("carb_g_per_kg_rest", Number(e.target.value))} className={inputCls} />
            </label>
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              Moderate
              <input type="number" step="0.1" min="0" value={form.carb_g_per_kg_moderate} onChange={(e) => update("carb_g_per_kg_moderate", Number(e.target.value))} className={inputCls} />
            </label>
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              Double day
              <input type="number" step="0.1" min="0" value={form.carb_g_per_kg_double_day} onChange={(e) => update("carb_g_per_kg_double_day", Number(e.target.value))} className={inputCls} />
            </label>
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              Pre-race
              <input type="number" step="0.1" min="0" value={form.carb_g_per_kg_pre_race} onChange={(e) => update("carb_g_per_kg_pre_race", Number(e.target.value))} className={inputCls} />
            </label>
          </div>
        </div>
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <p className="text-xs text-text-tertiary">Calorie target source</p>
          <div className="flex items-center gap-2">
            {(["garmin_total", "manual"] as const).map((src) => (
              <button
                key={src}
                type="button"
                onClick={() => update("kcal_target_source", src)}
                className={`min-h-11 rounded-md border px-3.5 text-sm font-medium transition-colors ${
                  form.kcal_target_source === src ? "border-accent text-accent" : "border-border text-text-tertiary"
                }`}
              >
                {src === "garmin_total" ? "Garmin total burn" : "Manual"}
              </button>
            ))}
            {form.kcal_target_source === "manual" && (
              <input
                type="number"
                min="0"
                value={form.manual_kcal_target ?? ""}
                onChange={(e) => update("manual_kcal_target", e.target.value ? Number(e.target.value) : null)}
                placeholder="kcal/day"
                className={inputCls}
              />
            )}
          </div>
        </div>
        {dirty && (
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => save.mutate(form)}
              disabled={save.isPending}
              className="min-h-11 rounded-md border border-accent bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save targets"}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}
