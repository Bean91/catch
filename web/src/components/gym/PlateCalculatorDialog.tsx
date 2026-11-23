import * as Dialog from "@radix-ui/react-dialog";
import { useMemo, useState } from "react";
import { DEFAULT_PLATES_KG, platesPerSide } from "../../lib/equipment";
import { ModalContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

/** Barbell/smith only (task Part A.4) — `plateLoadKg` is the plates-only number the set is
 * already logging (not the bar), so the per-side breakdown matches exactly what the lifter
 * typed, with no separate "subtract the bar" step for them to get wrong. */
export function PlateCalculatorDialog({
  open,
  onOpenChange,
  initialPlateLoadKg,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialPlateLoadKg: number;
}) {
  const [total, setTotal] = useState(initialPlateLoadKg);
  const { plates, remainder } = useMemo(() => platesPerSide(total), [total]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <ModalContent width="sm">
          <Dialog.Title className="text-lg font-semibold text-text-primary">Plate calculator</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">Plates only, both sides combined.</Dialog.Description>
          <input
            type="number"
            inputMode="decimal"
            value={total}
            onChange={(e) => setTotal(Number(e.target.value) || 0)}
            className={controlSkin + " mt-4 min-h-11 w-full text-center font-mono-nums"}
          />
          <div className="mt-4 rounded-md bg-surface-2 p-4">
            <div className="text-xs text-text-tertiary">Per side</div>
            {plates.length === 0 ? (
              <div className="mt-1 text-sm text-text-tertiary">No plates needed.</div>
            ) : (
              <div className="mt-1 flex flex-wrap gap-2">
                {plates.map((p, i) => (
                  <span key={i} className="rounded-md bg-accent/15 px-2.5 py-1 font-mono-nums text-sm text-accent">
                    {p}
                  </span>
                ))}
              </div>
            )}
            {remainder > 0 && (
              <div className="mt-2 text-xs text-text-tertiary">
                {remainder}kg per side can't be made exactly with {DEFAULT_PLATES_KG.join("/")}kg plates.
              </div>
            )}
          </div>
          <Dialog.Close asChild>
            <button type="button" className={buttonClass("secondary", "md", "mt-4 w-full")}>
              Close
            </button>
          </Dialog.Close>
        </ModalContent>
    </Dialog.Root>
  );
}
