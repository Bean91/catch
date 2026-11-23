import * as Dialog from "@radix-ui/react-dialog";
import { useRef, useState } from "react";
import { ApiError, estimateMealPhoto, savePhotoEstimate } from "../../lib/api";
import { resizeImage } from "../../lib/image";
import { pickNativePhoto } from "../../lib/native/camera";
import { isNative } from "../../lib/native/platform";
import { MEALS, type Meal, type PhotoEstimateItem, type PhotoEstimateResult } from "../../lib/types";
import { ModalContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

const MEAL_LABELS: Record<Meal, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
  pre_workout: "Pre-workout",
  post_workout: "Post-workout",
};

export function PhotoEstimateDialog({ open, onClose, defaultMeal, ts, onLogged }: { open: boolean; onClose: () => void; defaultMeal: Meal; ts: string; onLogged: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<"idle" | "estimating" | "ready" | "saving" | "error">("idle");
  const [items, setItems] = useState<PhotoEstimateItem[]>([]);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [meal, setMeal] = useState<Meal>(defaultMeal);

  const reset = () => {
    setStatus("idle");
    setItems([]);
    setNotes("");
    setError(null);
  };

  const choosePhoto = async () => {
    if (!isNative()) return fileInputRef.current?.click();
    try {
      const file = await pickNativePhoto();
      if (file) void onFilePicked(file);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't open the camera.");
    }
  };

  const onFilePicked = async (file: File) => {
    setStatus("estimating");
    setError(null);
    try {
      const resized = await resizeImage(file);
      const result: PhotoEstimateResult = await estimateMealPhoto(resized);
      setItems(result.items);
      setNotes(result.notes);
      setStatus("ready");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't estimate that photo — try again or enter the meal manually.");
      setStatus("error");
    }
  };

  const updateItem = (i: number, patch: Partial<PhotoEstimateItem>) => {
    setItems((prev) => prev.map((item, idx) => (idx === i ? { ...item, ...patch } : item)));
  };

  const removeItem = (i: number) => setItems((prev) => prev.filter((_, idx) => idx !== i));

  const save = async () => {
    setStatus("saving");
    try {
      await savePhotoEstimate(items, meal, ts);
      onLogged();
      onClose();
      reset();
    } catch {
      setError("Couldn't save the estimate — try again.");
      setStatus("ready");
    }
  };

  const close = () => {
    onClose();
    reset();
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && close()}>
      <ModalContent width="md">
          <Dialog.Title className="text-lg font-semibold text-text-primary">Photo estimate</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-tertiary">
            A rough, editable macro estimate from a photo — always labelled as an estimate, and the photo itself is never stored.
          </Dialog.Description>

          {status === "idle" && (
            <button
              type="button"
              onClick={choosePhoto}
              className="mt-4 min-h-24 w-full rounded-md border border-dashed border-border text-sm text-text-tertiary transition-colors hover:border-accent hover:text-text-secondary"
            >
              Take or choose a photo
            </button>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFilePicked(file);
              e.target.value = "";
            }}
          />

          {status === "estimating" && <div className="py-8 text-center text-sm text-text-tertiary">Estimating macros…</div>}

          {(status === "ready" || status === "saving") && (
            <>
              <label className="mt-4 block text-xs text-text-tertiary">
                Meal
                <select
                  value={meal}
                  onChange={(e) => setMeal(e.target.value as Meal)}
                  className={controlSkin + " mt-1 block min-h-11 w-full"}
                >
                  {MEALS.map((m) => (
                    <option key={m} value={m}>
                      {MEAL_LABELS[m]}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-3 flex flex-col gap-2">
                {items.map((item, i) => (
                  <div key={i} className="rounded-md border border-border p-2.5">
                    <div className="flex items-center gap-2">
                      <input
                        value={item.name}
                        onChange={(e) => updateItem(i, { name: e.target.value })}
                        className={controlSkin + " min-h-9 min-w-0 flex-1"}
                      />
                      <button type="button" onClick={() => removeItem(i)} aria-label={`Remove ${item.name}`} className="flex min-h-9 min-w-9 items-center justify-center text-text-tertiary hover:text-band-red">
                        ×
                      </button>
                    </div>
                    <div className="mt-2 grid grid-cols-4 gap-1.5 text-xs">
                      {(["kcal", "protein_g", "carbs_g", "fat_g"] as const).map((field) => (
                        <label key={field} className="flex flex-col gap-0.5">
                          <span className="text-text-tertiary">{field === "kcal" ? "kcal" : field.replace("_g", "")}</span>
                          <input
                            type="number"
                            inputMode="decimal"
                            value={item[field]}
                            onChange={(e) => updateItem(i, { [field]: Number(e.target.value) } as Partial<PhotoEstimateItem>)}
                            className={controlSkin + " min-h-9 w-full"}
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              {notes && <p className="mt-3 text-xs text-text-tertiary">{notes}</p>}
              {error && <p className="mt-2 text-sm text-text-secondary">{error}</p>}
              <div className="mt-4 flex gap-2">
                <button type="button" onClick={reset} className={buttonClass("secondary", "md")}>
                  Retake
                </button>
                <button
                  type="button"
                  onClick={save}
                  disabled={status === "saving" || items.length === 0}
                  className={buttonClass("primary", "md", "flex-1")}
                >
                  {status === "saving" ? "Saving…" : "Log this estimate"}
                </button>
              </div>
            </>
          )}

          {status === "error" && (
            <>
              <p className="mt-4 text-sm text-text-secondary">{error}</p>
              <button type="button" onClick={reset} className={buttonClass("secondary", "md", "mt-3 w-full")}>
                Try again
              </button>
            </>
          )}

          <Dialog.Close asChild>
            <button type="button" onClick={close} className={buttonClass("secondary", "md", "mt-3 w-full")}>
              Close
            </button>
          </Dialog.Close>
        </ModalContent>
    </Dialog.Root>
  );
}
