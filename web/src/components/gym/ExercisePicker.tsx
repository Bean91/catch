import * as Dialog from "@radix-ui/react-dialog";
import { useMemo, useState } from "react";
import { createExercise } from "../../lib/api";
import type { EquipmentType, Exercise, MovementPattern } from "../../lib/types";
import { EmptyState } from "../ui/EmptyState";
import { ModalContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

const EQUIPMENT_OPTIONS: { value: EquipmentType; label: string }[] = [
  { value: "barbell", label: "Barbell" },
  { value: "dumbbell", label: "Dumbbell" },
  { value: "kettlebell", label: "Kettlebell" },
  { value: "machine_plate", label: "Plate-loaded machine" },
  { value: "machine_selectorized", label: "Selectorized machine" },
  { value: "smith", label: "Smith machine" },
  { value: "cable", label: "Cable" },
  { value: "bodyweight", label: "Bodyweight" },
  { value: "weighted", label: "Weighted (bodyweight + added)" },
  { value: "assisted", label: "Assisted (bodyweight − assistance)" },
  { value: "band", label: "Band" },
  { value: "other", label: "Other" },
];

const MOVEMENT_OPTIONS: MovementPattern[] = [
  "squat", "hinge", "lunge", "push_horizontal", "push_vertical", "pull_horizontal", "pull_vertical", "carry", "core", "other",
];

export function ExercisePicker({
  open,
  onOpenChange,
  exercises,
  onPick,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  exercises: Exercise[];
  onPick: (exercise: Exercise) => void;
  onCreated: (exercise: Exercise) => void;
}) {
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newEquipment, setNewEquipment] = useState<EquipmentType>("barbell");
  const [newPattern, setNewPattern] = useState<MovementPattern>("other");
  const [saving, setSaving] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return exercises;
    return exercises.filter((e) => e.name.toLowerCase().includes(q));
  }, [query, exercises]);

  async function handleCreate() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const exercise = await createExercise({
        name: newName.trim(),
        default_equipment_type: newEquipment,
        movement_pattern: newPattern,
        unilateral: false,
        primary_muscles: [],
        secondary_muscles: [],
      });
      onCreated(exercise);
      setCreating(false);
      setNewName("");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <ModalContent width="md" className="flex flex-col">
          <Dialog.Title className="text-lg font-semibold text-text-primary">Add exercise</Dialog.Title>

          {creating ? (
            <div className="mt-4 flex flex-col gap-3">
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Exercise name"
                className={controlSkin + " w-auto min-h-11"}
              />
              <select
                value={newEquipment}
                onChange={(e) => setNewEquipment(e.target.value as EquipmentType)}
                className={controlSkin + " w-auto min-h-11"}
              >
                {EQUIPMENT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <select
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value as MovementPattern)}
                className={controlSkin + " w-auto min-h-11"}
              >
                {MOVEMENT_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p.replace("_", " ")}
                  </option>
                ))}
              </select>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setCreating(false)}
                  className={buttonClass("secondary", "md", "flex-1")}
                >
                  Back
                </button>
                <button
                  type="button"
                  disabled={!newName.trim() || saving}
                  onClick={handleCreate}
                  className={buttonClass("primary", "md", "flex-1")}
                >
                  {saving ? "Saving…" : "Add"}
                </button>
              </div>
            </div>
          ) : (
            <>
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search exercises…"
                className={controlSkin + " w-auto mt-3 min-h-11"}
              />
              <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
                {filtered.length === 0 ? (
                  <EmptyState message="No exercise matches that search." />
                ) : (
                  <ul className="flex flex-col gap-1">
                    {filtered.slice(0, 50).map((e) => (
                      <li key={e.id}>
                        <button
                          type="button"
                          onClick={() => onPick(e)}
                          className="flex min-h-11 w-full items-center justify-between rounded-md px-2.5 text-left text-sm text-text-primary transition-colors hover:bg-surface-2"
                        >
                          <span className="min-w-0 wrap-anywhere">{e.name}</span>
                          <span className="text-xs text-text-tertiary">{e.default_equipment_type.replace("_", " ")}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <button
                type="button"
                onClick={() => {
                  setCreating(true);
                  setNewName(query);
                }}
                className="mt-3 min-h-11 w-full rounded-md border border-dashed border-border text-sm font-medium text-text-secondary transition-colors hover:border-accent hover:text-accent"
              >
                + Add a custom exercise
              </button>
            </>
          )}
        </ModalContent>
    </Dialog.Root>
  );
}
