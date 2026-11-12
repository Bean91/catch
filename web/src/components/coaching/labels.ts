import type { FocusArea, TechniqueCategory } from "../../lib/types";

export const TECHNIQUE_CATEGORIES: { value: TechniqueCategory; label: string }[] = [
  { value: "catch", label: "Catch" },
  { value: "drive", label: "Drive" },
  { value: "finish", label: "Finish" },
  { value: "recovery", label: "Recovery" },
  { value: "sequencing", label: "Sequencing" },
  { value: "posture", label: "Posture" },
  { value: "rate_control", label: "Rate control" },
  { value: "blade_boat_handling", label: "Blade / boat handling" },
];

export const FOCUS_AREAS: { value: FocusArea; label: string }[] = [
  ...TECHNIQUE_CATEGORIES,
  { value: "pacing", label: "Pacing" },
  { value: "fitness", label: "Fitness" },
  { value: "strength", label: "Strength" },
  { value: "racing", label: "Racing" },
  { value: "other", label: "Other" },
];

export function focusLabel(v: string): string {
  return FOCUS_AREAS.find((f) => f.value === v)?.label ?? v;
}

// Catch has no measure of technique quality, so the copy says so wherever notes appear.
export const NOT_MEASURED = "These are written observations. Catch can't see technique in this data, so nothing here is scored or rated.";
