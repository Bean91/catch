import { useState } from "react";
import { deleteFoodLog, updateFoodLog } from "../../lib/api";
import type { FoodLogRow, Meal } from "../../lib/types";

const MEAL_LABELS: Record<Meal, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
  pre_workout: "Pre-workout",
  post_workout: "Post-workout",
};

function LogRow({ log, onChanged }: { log: FoodLogRow; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [quantity, setQuantity] = useState(String(log.quantity));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const q = Number(quantity);
    if (!Number.isFinite(q) || q <= 0) return;
    setSaving(true);
    try {
      await updateFoodLog(log.id, { quantity: q });
      setEditing(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    await deleteFoodLog(log.id);
    onChanged();
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2 rounded-md bg-surface-2 px-3 py-2">
        <span className="flex-1 truncate text-sm text-text-primary">{log.food_name}</span>
        <input
          type="number"
          inputMode="decimal"
          autoFocus
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          className="min-h-9 w-16 rounded-md border border-border bg-surface px-2 text-base text-text-primary"
        />
        <span className="text-xs text-text-tertiary">{log.unit}</span>
        <button type="button" onClick={save} disabled={saving} className="min-h-9 rounded-md border border-accent bg-accent px-2.5 text-xs font-medium text-accent-contrast disabled:opacity-40">
          Save
        </button>
        <button type="button" onClick={() => setEditing(false)} className="min-h-9 rounded-md border border-border px-2.5 text-xs text-text-secondary">
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-2">
      <button type="button" onClick={() => setEditing(true)} className="flex min-h-9 flex-1 items-center gap-2 text-left">
        <span className="truncate text-sm text-text-primary">{log.food_name ?? "Food"}</span>
        <span className="text-xs text-text-tertiary">
          {log.quantity}
          {log.unit === "serving" ? " serving" : "g"}
        </span>
        {log.estimated && <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-tertiary">estimate</span>}
      </button>
      <span className="font-mono-nums text-sm text-text-secondary">{log.kcal != null ? Math.round(log.kcal) : "—"}</span>
      <button type="button" onClick={remove} aria-label={`Delete ${log.food_name ?? "food"}`} className="flex min-h-9 min-w-9 items-center justify-center rounded-md text-text-tertiary transition-colors hover:text-band-red">
        ×
      </button>
    </div>
  );
}

export function MealSection({
  meal,
  logs,
  onAdd,
  onChanged,
  onCopyYesterday,
  canCopyYesterday,
}: {
  meal: Meal;
  logs: FoodLogRow[];
  onAdd: () => void;
  onChanged: () => void;
  onCopyYesterday: () => void;
  canCopyYesterday: boolean;
}) {
  const kcal = logs.reduce((sum, l) => sum + (l.kcal ?? 0), 0);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between px-1">
        <h4 className="text-sm font-medium text-text-secondary">{MEAL_LABELS[meal]}</h4>
        {logs.length > 0 && <span className="font-mono-nums text-xs text-text-tertiary">{Math.round(kcal)} kcal</span>}
      </div>
      <div className="flex flex-col gap-0.5">
        {logs.map((log) => (
          <LogRow key={log.id} log={log} onChanged={onChanged} />
        ))}
      </div>
      <div className="mt-1 flex gap-2">
        <button
          type="button"
          onClick={onAdd}
          className="min-h-9 flex-1 rounded-md border border-dashed border-border text-xs font-medium text-text-tertiary transition-colors hover:border-accent hover:text-text-secondary"
        >
          + Add
        </button>
        {canCopyYesterday && (
          <button
            type="button"
            onClick={onCopyYesterday}
            className="min-h-9 rounded-md border border-dashed border-border px-2 text-xs text-text-tertiary transition-colors hover:border-accent hover:text-text-secondary"
          >
            Copy yesterday's
          </button>
        )}
      </div>
    </div>
  );
}
