// ?mock=1 goals. Progress figures are fixed per seeded goal; a goal created in the mock starts at zero (the browser holds no goal
// maths — the server computes every figure).
import { addDays, todayISO, weekStart } from "./dates";
import type { Goal, GoalInput } from "./types";

const t = () => todayISO();
let nextId = 10;

function seed(): Goal[] {
  const mon = weekStart(t());
  return [
    {
      id: 1, ref: "goal:1", text: "Row 400 km this block", kind: "distance_total", sport: "rowing", target_value: 400000, unit: "m",
      start_date: addDays(t(), -40), end_date: addDays(t(), 20), target_date: addDays(t(), 20), status: "active", params: null,
      created_at: addDays(t(), -40), completed_at: null,
      progress: { kind: "distance_total", unit: "m", target: 400000, state: "active", days_left: 20, measurable: true, current: 251300, pct: 62.8, achieved: false },
    },
    {
      id: 2, ref: "goal:2", text: "300 minutes a week", kind: "weekly_volume", sport: null, target_value: 300, unit: "min/week",
      start_date: addDays(mon, -21), end_date: addDays(mon, 27), target_date: addDays(mon, 27), status: "active", params: null,
      created_at: addDays(mon, -21), completed_at: null, recovery_today: "yellow",
      progress: {
        kind: "weekly_volume", unit: "min/week", target: 300, state: "active", days_left: 27, measurable: true, current: 140, pct: 46.7, weeks_met: 2, weeks_finished: 3,
        weeks: [
          { week_start: addDays(mon, -21), value: 320, met: true, current: false },
          { week_start: addDays(mon, -14), value: 260, met: false, current: false },
          { week_start: addDays(mon, -7), value: 335, met: true, current: false },
          { week_start: mon, value: 140, met: false, current: true },
        ],
      },
    },
    {
      id: 3, ref: "goal:3", text: "2,000 m at 1:42.0 split", kind: "target_split", sport: "rowing", target_value: 102, unit: "s",
      start_date: addDays(t(), -60), end_date: addDays(t(), 45), target_date: addDays(t(), 45), status: "active", params: { distance_m: 2000 },
      created_at: addDays(t(), -60), completed_at: null,
      progress: { kind: "target_split", unit: "s", target: 102, state: "active", days_left: 45, measurable: true, current: 103.1, gap: 1.1, achieved: false, efforts: 3, best_ref: "/workouts/1", pct: null },
    },
    {
      id: 4, ref: "goal:4", text: "Learn to row square blade", kind: "text", sport: null, target_value: null, unit: null,
      start_date: null, end_date: null, target_date: addDays(t(), -5), status: "done", params: null, created_at: addDays(t(), -90), completed_at: addDays(t(), -6),
      progress: { kind: "text", unit: null, target: null, state: "done", days_left: null, measurable: false },
    },
  ];
}

let state = seed();

export function mockGoals(view: "active" | "history" | "all"): Goal[] {
  if (view === "active") return state.filter((g) => g.progress.state === "active");
  if (view === "history") return state.filter((g) => g.progress.state !== "active");
  return state;
}

export function createMockGoal(input: GoalInput): Goal {
  const kind = input.kind ?? "text";
  const g: Goal = {
    id: nextId++, ref: `goal:${nextId}`, text: input.text || "New goal", kind, sport: input.sport ?? null, target_value: input.target_value ?? null, unit: null,
    start_date: input.start_date ?? null, end_date: input.end_date ?? null, target_date: input.end_date ?? input.target_date ?? null, status: "active", params: input.params ?? null,
    created_at: t(), completed_at: null,
    progress: { kind, unit: null, target: input.target_value ?? null, state: "active", days_left: null, measurable: kind !== "text", current: kind === "text" ? undefined : 0, pct: kind === "text" ? undefined : 0, achieved: false },
  };
  state = [g, ...state];
  return g;
}

export function updateMockGoal(id: number, patch: GoalInput): Goal {
  const g = state.find((x) => x.id === id);
  if (!g) throw new Error("No goal with that id");
  Object.assign(g, Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined)));
  if (patch.status) {
    g.progress = { ...g.progress, state: patch.status === "active" ? "active" : patch.status };
    g.completed_at = patch.status === "done" ? t() : null;
  }
  return g;
}

export function deleteMockGoal(id: number): void {
  state = state.filter((g) => g.id !== id);
}
