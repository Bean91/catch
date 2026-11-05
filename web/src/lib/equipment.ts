// Small TS port of catch/analytics/equipment.py — duplicated intentionally so the offline
// gym logger can show a real effective-load preview while logging a set with no network at
// all (the whole point of the offline-first design — see PLAN.md's session 14 Part A.1).
// The server recomputes the same numbers from scratch on sync and is always the value of
// record; this is a preview only. Keep in sync by hand if the equipment math ever changes.
import type { EquipmentType } from "./types";

export const DEFAULT_BARBELL_KG = 20.0;
export const DEFAULT_UNKNOWN_SMITH_BAR_KG = 10.0;
export const DEFAULT_PLATES_KG = [25, 20, 15, 10, 5, 2.5, 1.25];
export const BAND_TAG_KG: Record<string, number> = { light: 10, medium: 20, heavy: 35 };

export interface LoadResult {
  effectiveLoadKg: number | null;
  isEstimated: boolean;
  note?: string;
}

export interface EffectiveLoadInput {
  equipmentType: EquipmentType;
  loadKg: number | null;
  barWeightKg: number | null;
  pulleyMultiplier: number | null;
  addedWeightKg: number | null;
  assistanceKg: number | null;
  bilateral: boolean;
  bandTag: string | null;
  stationConfig: GymStationConfig | null;
  bodyweightKg: number | null;
}

export interface GymStationConfig {
  base_weight_kg?: number;
  stack_kg_per_increment?: number;
  pulley_multiplier?: number;
}

export function computeEffectiveLoad(input: EffectiveLoadInput): LoadResult {
  const { equipmentType, loadKg, barWeightKg, pulleyMultiplier, addedWeightKg, assistanceKg, bilateral, bandTag, stationConfig, bodyweightKg } = input;
  const load = loadKg ?? 0;

  switch (equipmentType) {
    case "barbell":
      return { effectiveLoadKg: load + (barWeightKg ?? DEFAULT_BARBELL_KG), isEstimated: false };
    case "smith":
      if (barWeightKg == null) {
        return {
          effectiveLoadKg: load + DEFAULT_UNKNOWN_SMITH_BAR_KG,
          isEstimated: true,
          note: "Smith bar weight not set for this gym — using a rough default; enter it once in gym setup.",
        };
      }
      return { effectiveLoadKg: load + barWeightKg, isEstimated: false };
    case "dumbbell":
    case "kettlebell":
      return { effectiveLoadKg: bilateral ? load * 2 : load, isEstimated: false };
    case "machine_plate":
      return { effectiveLoadKg: load + (stationConfig?.base_weight_kg ?? 0), isEstimated: false };
    case "machine_selectorized":
      return {
        effectiveLoadKg: load * (stationConfig?.stack_kg_per_increment ?? 1) + (stationConfig?.base_weight_kg ?? 0),
        isEstimated: false,
      };
    case "cable":
      return { effectiveLoadKg: load * (pulleyMultiplier ?? stationConfig?.pulley_multiplier ?? 1), isEstimated: false };
    case "bodyweight":
      if (bodyweightKg == null) {
        return { effectiveLoadKg: null, isEstimated: true, note: "No bodyweight on file yet — log a weight in Body." };
      }
      return { effectiveLoadKg: bodyweightKg, isEstimated: false };
    case "weighted":
      if (bodyweightKg == null) {
        return { effectiveLoadKg: addedWeightKg ?? 0, isEstimated: true, note: "No bodyweight on file — this is added weight only." };
      }
      return { effectiveLoadKg: bodyweightKg + (addedWeightKg ?? 0), isEstimated: false };
    case "assisted":
      if (bodyweightKg == null) {
        return { effectiveLoadKg: null, isEstimated: true, note: "No bodyweight on file yet — log a weight in Body." };
      }
      return { effectiveLoadKg: Math.max(0, bodyweightKg - (assistanceKg ?? 0)), isEstimated: false };
    case "band": {
      const kg = bandTag ? BAND_TAG_KG[bandTag] : undefined;
      return {
        effectiveLoadKg: kg ?? null,
        isEstimated: true,
        note: kg != null ? "Band resistance is an approximate tag-based estimate." : `Unknown band tag ${bandTag}.`,
      };
    }
    default:
      return { effectiveLoadKg: loadKg, isEstimated: false };
  }
}

/** Greedy plate calculator — `totalPlateLoadKg` is plates only, both sides combined (the
 * same number `computeEffectiveLoad`'s barbell/smith branches take). Returns one side's
 * plates and any un-representable remainder. */
export function platesPerSide(totalPlateLoadKg: number, availableKg: number[] = DEFAULT_PLATES_KG): { plates: number[]; remainder: number } {
  const sorted = [...availableKg].sort((a, b) => b - a);
  let remaining = Math.max(0, totalPlateLoadKg) / 2;
  const plates: number[] = [];
  for (const plate of sorted) {
    while (remaining + 1e-6 >= plate) {
      plates.push(plate);
      remaining -= plate;
    }
  }
  return { plates, remainder: Math.max(0, Math.round(remaining * 1000) / 1000) };
}

/** catch/analytics/strength.py's Epley e1RM, capped at 10 reps for the estimate. */
export function epley1Rm(weightKg: number, reps: number): number {
  if (reps <= 0 || weightKg <= 0) return 0;
  const capped = Math.min(reps, 10);
  return weightKg * (1 + capped / 30);
}
