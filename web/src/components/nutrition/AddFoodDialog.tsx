import * as Dialog from "@radix-ui/react-dialog";
import { lazy, Suspense, useEffect, useState } from "react";
import { createManualFood, fetchMyFoods, fetchSavedMeals, logFood, logSavedMeal, searchFoods, starFood } from "../../lib/api";
import type { Food, Meal, MyFoodRow, SavedMealRow } from "../../lib/types";

const BarcodeScanner = lazy(() => import("./BarcodeScanner").then((m) => ({ default: m.BarcodeScanner })));

type Step = "search" | "quantity" | "manual" | "scan";

export function AddFoodDialog({
  open,
  onClose,
  meal,
  ts,
  onLogged,
}: {
  open: boolean;
  onClose: () => void;
  meal: Meal;
  ts: string;
  onLogged: () => void;
}) {
  const [step, setStep] = useState<Step>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Food[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Food | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [unit, setUnit] = useState<"g" | "serving">("serving");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [myFoods, setMyFoods] = useState<MyFoodRow[]>([]);
  const [savedMeals, setSavedMeals] = useState<SavedMealRow[]>([]);
  // Open Food Facts' free-text search is opt-in (its own docs warn against search-as-you-
  // type, and a 250ms debounce doesn't change that the trigger is still every keystroke
  // pause, not an explicit action) — tracks whether the current query has had it included
  // yet, so "Also search Open Food Facts" only shows once per query and only before it's
  // been tapped.
  const [offIncluded, setOffIncluded] = useState(false);
  const [searchingOff, setSearchingOff] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStep("search");
    setQuery("");
    setResults([]);
    setSelected(null);
    setError(null);
    fetchMyFoods().then(setMyFoods).catch(() => undefined);
    fetchSavedMeals().then(setSavedMeals).catch(() => undefined);
  }, [open]);

  useEffect(() => {
    setOffIncluded(false);
    if (step !== "search" || !query.trim()) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    // `cancelled` guards against a slower, earlier query's response landing after a faster,
    // later one — the timer's own clearTimeout only stops a call that hasn't fired yet; it
    // can't stop one already in flight.
    let cancelled = false;
    const handle = setTimeout(() => {
      searchFoods(query)
        .then((r) => {
          if (!cancelled) setResults(r);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [query, step]);

  const searchOff = async () => {
    if (!query.trim()) return;
    setSearchingOff(true);
    try {
      const r = await searchFoods(query, true);
      setResults(r);
      setOffIncluded(true);
    } finally {
      setSearchingOff(false);
    }
  };

  const pickFood = (food: Food) => {
    setSelected(food);
    setUnit(food.serving_size ? "serving" : "g");
    setQuantity("1");
    setStep("quantity");
  };

  const submitQuantity = async () => {
    if (!selected) return;
    const q = Number(quantity);
    if (!Number.isFinite(q) || q <= 0) return;
    setSaving(true);
    setError(null);
    try {
      await logFood({ ts, meal, foodId: selected.id, quantity: q, unit });
      onLogged();
      onClose();
    } catch {
      setError("Couldn't log that food — try again.");
    } finally {
      setSaving(false);
    }
  };

  const logEntireSavedMeal = async (savedMealId: number) => {
    setSaving(true);
    try {
      await logSavedMeal(savedMealId, meal, ts);
      onLogged();
      onClose();
    } catch {
      setError("Couldn't log that meal — try again.");
    } finally {
      setSaving(false);
    }
  };

  const onBarcodeDetected = async (barcode: string) => {
    setStep("search");
    const { lookupBarcode } = await import("../../lib/api");
    const result = await lookupBarcode(barcode);
    if (result.found) {
      const { found, ...food } = result;
      void found;
      pickFood(food);
    } else {
      setSelected({
        id: 0, source: "manual", barcode, name: "", brand: null, serving_size: null, serving_unit: "g",
        kcal_100g: null, protein_100g: null, carbs_100g: null, fat_100g: null, fiber_100g: null, sugar_100g: null, sodium_100g: null, verified: false,
      });
      setStep("manual");
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-30 max-h-[85vh] w-[min(92vw,440px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
          {step === "search" && (
            <>
              <Dialog.Title className="text-base font-semibold text-text-primary">Add food</Dialog.Title>
              <div className="mt-3 flex gap-2">
                <input
                  autoFocus
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search foods…"
                  className="min-h-11 flex-1 rounded-md border border-border bg-bg px-3 text-base text-text-primary"
                />
                <button
                  type="button"
                  onClick={() => setStep("scan")}
                  className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-primary transition-colors hover:border-accent"
                >
                  Scan
                </button>
              </div>
              <div className="mt-3 flex flex-col gap-1.5">
                {searching && <div className="py-4 text-center text-sm text-text-tertiary">Searching…</div>}
                {!searching && query.trim() && results.length === 0 && (
                  <div className="py-4 text-center text-sm text-text-tertiary">No matches — add it manually below.</div>
                )}
                {results.map((food) => (
                  <button
                    key={food.id}
                    type="button"
                    onClick={() => pickFood(food)}
                    className="flex min-h-11 items-center justify-between rounded-md border border-border px-3 py-2 text-left text-sm transition-colors hover:border-accent"
                  >
                    <span>
                      <span className="text-text-primary">{food.name}</span>
                      {food.brand && <span className="text-text-tertiary"> · {food.brand}</span>}
                    </span>
                    <span className="font-mono-nums text-xs text-text-tertiary">{food.kcal_100g != null ? `${Math.round(food.kcal_100g)}kcal/100g` : ""}</span>
                  </button>
                ))}
                {!searching && query.trim() && !offIncluded && (
                  <button
                    type="button"
                    onClick={searchOff}
                    disabled={searchingOff}
                    className="min-h-9 rounded-md border border-dashed border-border text-xs text-text-tertiary transition-colors hover:border-accent hover:text-text-secondary disabled:opacity-40"
                  >
                    {searchingOff ? "Searching Open Food Facts…" : "Also search Open Food Facts"}
                  </button>
                )}
              </div>

              {!query.trim() && myFoods.length > 0 && (
                <div className="mt-4">
                  <p className="mb-1.5 text-xs text-text-tertiary">My foods</p>
                  <div className="flex flex-wrap gap-1.5">
                    {myFoods.map((f) => (
                      <button
                        key={f.my_food_id}
                        type="button"
                        onClick={() => pickFood(f)}
                        className="min-h-9 rounded-full border border-border px-3 text-xs text-text-primary transition-colors hover:border-accent"
                      >
                        {f.label ?? f.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {!query.trim() && savedMeals.length > 0 && (
                <div className="mt-4">
                  <p className="mb-1.5 text-xs text-text-tertiary">Saved meals</p>
                  <div className="flex flex-wrap gap-1.5">
                    {savedMeals.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        disabled={saving}
                        onClick={() => logEntireSavedMeal(m.id)}
                        className="min-h-9 rounded-full border border-border px-3 text-xs text-text-primary transition-colors hover:border-accent disabled:opacity-40"
                      >
                        {m.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {error && <p className="mt-3 text-sm text-text-secondary">{error}</p>}

              <button
                type="button"
                onClick={() => {
                  setSelected({
                    id: 0, source: "manual", barcode: null, name: query, brand: null, serving_size: null, serving_unit: "g",
                    kcal_100g: null, protein_100g: null, carbs_100g: null, fat_100g: null, fiber_100g: null, sugar_100g: null, sodium_100g: null, verified: false,
                  });
                  setStep("manual");
                }}
                className="mt-3 min-h-11 w-full rounded-md border border-dashed border-border text-sm text-text-tertiary transition-colors hover:border-accent hover:text-text-secondary"
              >
                Can't find it? Add manually
              </button>
            </>
          )}

          {step === "scan" && (
            <Suspense fallback={<div className="py-10 text-center text-sm text-text-tertiary">Loading scanner…</div>}>
              <BarcodeScanner onDetect={onBarcodeDetected} onClose={() => setStep("search")} />
            </Suspense>
          )}

          {step === "quantity" && selected && (
            <>
              <Dialog.Title className="text-base font-semibold text-text-primary">{selected.name}</Dialog.Title>
              {selected.brand && <Dialog.Description className="text-sm text-text-tertiary">{selected.brand}</Dialog.Description>}
              <div className="mt-4 flex items-end gap-2">
                <div className="flex-1">
                  <label htmlFor="add-food-qty" className="block text-xs text-text-tertiary">
                    Quantity
                  </label>
                  <input
                    id="add-food-qty"
                    type="number"
                    inputMode="decimal"
                    step="any"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    className="min-h-11 w-full rounded-md border border-border bg-bg px-3 text-base text-text-primary"
                  />
                </div>
                <div>
                  <label htmlFor="add-food-unit" className="block text-xs text-text-tertiary">
                    Unit
                  </label>
                  <select
                    id="add-food-unit"
                    value={unit}
                    onChange={(e) => setUnit(e.target.value as "g" | "serving")}
                    className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary"
                  >
                    <option value="g">grams</option>
                    <option value="serving" disabled={!selected.serving_size}>
                      serving{selected.serving_size ? ` (${selected.serving_size}${selected.serving_unit ?? "g"})` : " — unknown size"}
                    </option>
                  </select>
                </div>
              </div>
              {error && <p className="mt-2 text-sm text-text-secondary">{error}</p>}
              <div className="mt-4 flex gap-2">
                <button type="button" onClick={() => setStep("search")} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-primary transition-colors hover:border-accent">
                  Back
                </button>
                <button
                  type="button"
                  onClick={() => starFood(selected.id).catch(() => undefined)}
                  className="min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary transition-colors hover:border-accent"
                >
                  ★ Save to My Foods
                </button>
                <button
                  type="button"
                  onClick={submitQuantity}
                  disabled={saving}
                  className="min-h-11 flex-1 rounded-md border border-accent bg-accent px-3 text-sm font-medium text-accent-contrast disabled:opacity-40"
                >
                  {saving ? "Logging…" : "Log it"}
                </button>
              </div>
            </>
          )}

          {step === "manual" && selected && (
            <ManualFoodForm
              initial={selected}
              onCancel={() => setStep("search")}
              onSaved={(food) => pickFood(food)}
            />
          )}

          {step === "search" && (
            <Dialog.Close asChild>
              <button type="button" onClick={onClose} className="mt-4 min-h-11 w-full rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent">
                Cancel
              </button>
            </Dialog.Close>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ManualFoodForm({ initial, onCancel, onSaved }: { initial: Food; onCancel: () => void; onSaved: (food: Food) => void }) {
  const [name, setName] = useState(initial.name);
  const [brand, setBrand] = useState(initial.brand ?? "");
  const [servingSize, setServingSize] = useState(initial.serving_size != null ? String(initial.serving_size) : "");
  const [kcal, setKcal] = useState("");
  const [protein, setProtein] = useState("");
  const [carbs, setCarbs] = useState("");
  const [fat, setFat] = useState("");
  const [saving, setSaving] = useState(false);

  const num = (s: string) => (s.trim() === "" ? null : Number(s));

  const submit = async () => {
    if (!name.trim() || kcal.trim() === "") return;
    setSaving(true);
    try {
      const food = await createManualFood({
        barcode: initial.barcode,
        name: name.trim(),
        brand: brand.trim() || null,
        serving_size: num(servingSize),
        serving_unit: "g",
        kcal_100g: num(kcal),
        protein_100g: num(protein),
        carbs_100g: num(carbs),
        fat_100g: num(fat),
      });
      onSaved(food);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Dialog.Title className="text-base font-semibold text-text-primary">Add food manually</Dialog.Title>
      {initial.barcode && <Dialog.Description className="text-xs text-text-tertiary">Barcode {initial.barcode} — not found in any database yet.</Dialog.Description>}
      <div className="mt-3 flex flex-col gap-2.5">
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
        <input placeholder="Brand (optional)" value={brand} onChange={(e) => setBrand(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
        <p className="text-xs text-text-tertiary">Per 100g:</p>
        <div className="grid grid-cols-2 gap-2">
          <input placeholder="kcal" type="number" inputMode="decimal" value={kcal} onChange={(e) => setKcal(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
          <input placeholder="protein g" type="number" inputMode="decimal" value={protein} onChange={(e) => setProtein(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
          <input placeholder="carbs g" type="number" inputMode="decimal" value={carbs} onChange={(e) => setCarbs(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
          <input placeholder="fat g" type="number" inputMode="decimal" value={fat} onChange={(e) => setFat(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
        </div>
        <input placeholder="Serving size, g (optional)" type="number" inputMode="decimal" value={servingSize} onChange={(e) => setServingSize(e.target.value)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-base text-text-primary" />
      </div>
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={onCancel} className="min-h-11 flex-1 rounded-md border border-border text-sm text-text-primary transition-colors hover:border-accent">
          Back
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={saving || !name.trim() || kcal.trim() === ""}
          className="min-h-11 flex-1 rounded-md border border-accent bg-accent text-sm font-medium text-accent-contrast disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save & continue"}
        </button>
      </div>
    </>
  );
}
