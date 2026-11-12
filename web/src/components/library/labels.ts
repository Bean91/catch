import { formatClock, formatMetres } from "../../lib/duration";
import type { Difficulty, TemplateBlock, TemplateSegment, WorkoutType } from "../../lib/types";

export const WORKOUT_TYPES: { value: WorkoutType; label: string; hint: string }[] = [
  { value: "erg_intervals", label: "Erg intervals", hint: "Repeated work and rest, by distance or time" },
  { value: "steady_state", label: "Steady state", hint: "One continuous block" },
  { value: "rate_ladder", label: "Rate ladder", hint: "Steps at a stepped stroke rate" },
  { value: "distance_piece", label: "Distance piece", hint: "One piece for a distance" },
  { value: "time_piece", label: "Time piece", hint: "One piece for a time" },
  { value: "strength", label: "Strength", hint: "A list of exercises" },
  { value: "on_water", label: "On water", hint: "Blocks on the water" },
  { value: "custom", label: "Custom", hint: "Anything else" },
];

export function workoutTypeLabel(v: string): string {
  return WORKOUT_TYPES.find((t) => t.value === v)?.label ?? v;
}

export const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  { value: "easy", label: "Easy" },
  { value: "moderate", label: "Moderate" },
  { value: "hard", label: "Hard" },
];

export const SESSION_TYPE_CHOICES: Record<WorkoutType, string[]> = {
  erg_intervals: ["erg"],
  steady_state: ["erg", "on_water", "run", "bike", "cross", "other"],
  rate_ladder: ["erg", "on_water"],
  distance_piece: ["erg", "on_water"],
  time_piece: ["erg", "on_water"],
  strength: ["strength"],
  on_water: ["on_water"],
  custom: ["erg", "on_water", "run", "bike", "strength", "cross", "other"],
};

export const EXAMPLE_NOTICE = "Examples show how a session can be written down. They are not training advice or a prescription — duplicate one to make it your own.";

export function blockWork(b: TemplateBlock): string {
  return b.work_m != null ? formatMetres(b.work_m) : formatClock(b.work_s);
}

export function blockTargets(b: TemplateBlock): string[] {
  const out: string[] = [];
  if (b.rate_min != null || b.rate_max != null) {
    const lo = b.rate_min ?? b.rate_max;
    const hi = b.rate_max ?? b.rate_min;
    out.push(lo === hi ? `${lo} spm` : `${lo}–${hi} spm`);
  }
  if (b.split_s) out.push(`${formatClock(b.split_s, true)} /500 m`);
  if (b.watts) out.push(`${b.watts} W`);
  if (b.zone) out.push(b.zone);
  return out;
}

export function segmentText(s: TemplateSegment | null | undefined): string | null {
  if (!s || (s.duration_min == null && s.distance_m == null)) return null;
  const amount = s.duration_min != null ? `${s.duration_min} min` : formatMetres(s.distance_m);
  return s.zone ? `${amount} · ${s.zone}` : amount;
}
