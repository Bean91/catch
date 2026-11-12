// ?mock=1 fixtures for the workout library. Mutable in-memory state so create / duplicate /
// archive / schedule can be exercised with no backend. The totals below are a deliberately small
// stand-in for the server's catch/analytics/workout_library.py — a mock is a canned response, and
// the real browser never computes them (it asks POST /api/library/templates/preview).
import { addDays, todayISO, weekStart } from "./dates";
import { createMockPlanned, setMockTemplateId } from "./mockCalendar";
import type {
  PlannedWorkout,
  ScheduleInput,
  SessionType,
  TemplateBlock,
  TemplateInput,
  TemplateIssue,
  TemplatePreview,
  TemplateScope,
  TemplateStructure,
  TemplateSummary,
  WorkoutTemplate,
  WorkoutType,
  ZoneLabel,
} from "./types";

const EXAMPLE_LABEL = "Example — not prescribed training";
const DEFAULT_SESSION: Record<WorkoutType, SessionType> = {
  erg_intervals: "erg", steady_state: "erg", rate_ladder: "erg", distance_piece: "erg",
  time_piece: "erg", strength: "strength", on_water: "on_water", custom: "other",
};

export function mockSummary(structure: TemplateStructure, targetZone: ZoneLabel | null): TemplateSummary {
  const blocks = structure.blocks ?? [];
  let work = 0, workM = 0, rest = 0, seen = 0;
  let workKnown = true, estimated = false;
  const zones: Record<string, number> = {};
  const total = blocks.reduce((n, b) => n + (b.reps || 1), 0);
  for (const b of blocks) {
    const reps = b.reps || 1;
    const split = b.split_s ?? (b.watts ? 500 * Math.cbrt(2.8 / b.watts) : null);
    let d: number | null = null;
    if (b.work_s != null) d = b.work_s;
    else if (b.work_m != null && split) { d = (b.work_m / 500) * split; estimated = true; }
    if (d == null) workKnown = false; else work += reps * d;
    if (b.work_m != null) workM += reps * b.work_m;
    const z = b.zone ?? targetZone;
    if (z && d != null) zones[z] = (zones[z] ?? 0) + (reps * d) / 60;
    seen += reps;
    rest += Math.max(reps - (seen === total ? 1 : 0), 0) * (b.rest_s ?? 0);
  }
  const wu = structure.warmup, cd = structure.cooldown;
  const segKnown = !(wu?.distance_m) && !(cd?.distance_m);
  const seg = ((wu?.duration_min ?? 0) + (cd?.duration_min ?? 0)) * 60;
  const known = blocks.length > 0 && workKnown && segKnown;
  const totalS = known ? work + rest + seg : null;
  return {
    block_count: blocks.length, rep_count: total, work_duration_s: blocks.length && workKnown ? work : null,
    rest_duration_s: blocks.length ? rest : null, warmup_duration_s: wu?.duration_min ? wu.duration_min * 60 : null,
    cooldown_duration_s: cd?.duration_min ? cd.duration_min * 60 : null,
    work_distance_m: blocks.length && blocks.every((b) => b.work_m != null) ? workM : null,
    total_duration_s: totalS, total_distance_m: blocks.length && !wu?.duration_min && !cd?.duration_min && blocks.every((b) => b.work_m != null) ? workM : null,
    duration_basis: totalS == null ? "unknown" : estimated ? "estimated" : "exact", distance_basis: "unknown",
    work_rest_ratio: workKnown && rest > 0 && work > 0 ? work / rest : null,
    zone_minutes: zones, strength_exercise_count: structure.strength_items?.length ?? 0,
  };
}

function signature(structure: TemplateStructure): string | null {
  const blocks = structure.blocks ?? [];
  if (!blocks.length) return null;
  const part = (b: TemplateBlock) => `${b.reps}x${b.work_m != null ? `${b.work_m}m` : `${b.work_s}s`}/r${Math.round(b.rest_s ?? 0)}`;
  return blocks.length === 1 ? part(blocks[0]) : blocks.map(part).join("+");
}

function make(id: number, input: TemplateInput, extra: Partial<WorkoutTemplate> = {}): WorkoutTemplate {
  const session = input.session_type ?? DEFAULT_SESSION[input.workout_type];
  const now = new Date().toISOString();
  return {
    id, name: input.name, description: input.description ?? null, workout_type: input.workout_type, session_type: session,
    sport_family: session === "erg" || session === "on_water" ? "rowing" : session === "strength" ? "strength" : null,
    purpose: input.purpose ?? null, difficulty: input.difficulty ?? null, target_zone: input.target_zone ?? null,
    tags: input.tags ?? [], structure: input.structure, is_example: false, example_label: null, duplicated_from_id: null,
    archived: false, signature: signature(input.structure), summary: mockSummary(input.structure, input.target_zone ?? null),
    created_at: now, updated_at: now, ...extra,
  };
}

const EXAMPLES: TemplateInput[] = [
  { name: "Example: 60-minute steady row", workout_type: "steady_state", difficulty: "easy", target_zone: "UT2", description: "An illustrative single continuous block. Pick your own effort, rate and duration.", structure: { blocks: [{ reps: 1, work_s: 3600, zone: "UT2", rate_min: 18, rate_max: 20 }] } },
  { name: "Example: 4 x 500m with rest", workout_type: "erg_intervals", difficulty: "hard", description: "An illustrative short-interval layout with a warm-up and cool-down.", structure: { warmup: { duration_min: 10 }, blocks: [{ reps: 4, work_m: 500, rest_s: 60 }], cooldown: { duration_min: 5 } } },
  { name: "Example: 6 x 3 minutes", workout_type: "erg_intervals", difficulty: "moderate", target_zone: "AT", description: "An illustrative timed-interval layout.", structure: { warmup: { duration_min: 10 }, blocks: [{ reps: 6, work_s: 180, rest_s: 120, zone: "AT" }], cooldown: { duration_min: 5 } } },
  { name: "Example: rate ladder 18-26", workout_type: "rate_ladder", difficulty: "moderate", description: "An illustrative ladder: the same time at a stepped stroke rate.", structure: { blocks: [18, 20, 22, 24, 26].map((r, i) => ({ reps: 1, work_s: 240, rest_s: i < 4 ? 60 : null, rate_min: r, rate_max: r })) } },
  { name: "Example: 5000m piece", workout_type: "distance_piece", difficulty: "moderate", description: "A single distance piece. Add your own target split if you want a duration estimate.", structure: { blocks: [{ reps: 1, work_m: 5000 }] } },
];

let templates: WorkoutTemplate[] = [];
let nextId = 100;

function seed() {
  templates = [
    make(1, { name: "Threshold 4 x 5 min", workout_type: "erg_intervals", difficulty: "moderate", target_zone: "AT", tags: ["threshold", "erg"], purpose: "Steady work at the top of the aerobic range", structure: { warmup: { duration_min: 10 }, blocks: [{ reps: 4, work_s: 300, rest_s: 120, zone: "AT", rate_min: 24, rate_max: 26 }], cooldown: { duration_min: 5 } } }),
    make(2, { name: "Sunday long steady", workout_type: "steady_state", difficulty: "easy", target_zone: "UT2", tags: ["base"], structure: { blocks: [{ reps: 1, work_s: 4800, zone: "UT2", rate_min: 18, rate_max: 20 }] } }),
    make(3, { name: "6 x 500m (no split set)", workout_type: "erg_intervals", difficulty: "hard", tags: ["speed"], description: "Distance only — no duration until a split is chosen.", structure: { blocks: [{ reps: 6, work_m: 500, rest_s: 90 }] } }),
    make(4, { name: "Old session", workout_type: "time_piece", structure: { blocks: [{ reps: 1, work_s: 1800 }] } }, { archived: true }),
    ...EXAMPLES.map((e, i) => make(20 + i, e, { is_example: true, example_label: EXAMPLE_LABEL, tags: ["example"] })),
  ];
  nextId = 100;
}
seed();

export function resetMockLibrary() {
  seed();
}

export function mockTemplates(opts: { scope?: TemplateScope; q?: string; workout_type?: string; difficulty?: string }): WorkoutTemplate[] {
  const scope = opts.scope ?? "mine";
  return templates
    .filter((t) => (scope === "archived" ? t.archived : !t.archived))
    .filter((t) => (scope === "mine" ? !t.is_example : scope === "examples" ? t.is_example : true))
    .filter((t) => !opts.workout_type || t.workout_type === opts.workout_type)
    .filter((t) => !opts.difficulty || t.difficulty === opts.difficulty)
    .filter((t) => !opts.q || `${t.name} ${t.description ?? ""} ${t.tags.join(" ")}`.toLowerCase().includes(opts.q.toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function mockTemplate(id: number): WorkoutTemplate {
  const t = templates.find((x) => x.id === id);
  if (!t) throw new Error(`No workout template with id ${id}`);
  return t;
}

export function validateMock(input: TemplateInput): TemplateIssue[] {
  const issues: TemplateIssue[] = [];
  if (!input.name?.trim()) issues.push({ path: "name", message: "A name is required." });
  const blocks = input.structure.blocks ?? [];
  blocks.forEach((b, i) => {
    if ((b.work_s == null) === (b.work_m == null)) issues.push({ path: `structure.blocks[${i}]`, message: "Give exactly one of work_s (time) or work_m (distance)." });
    if (!(b.reps >= 1 && b.reps <= 100)) issues.push({ path: `structure.blocks[${i}].reps`, message: "reps must be a whole number from 1 to 100." });
  });
  if (input.workout_type === "rate_ladder" && blocks.length < 2) issues.push({ path: "structure.blocks", message: "A rate ladder needs at least two steps." });
  if (input.workout_type === "erg_intervals" && !(blocks.length > 1 || blocks.some((b) => b.reps > 1))) issues.push({ path: "structure.blocks", message: "Intervals need more than one rep or more than one block." });
  if (input.workout_type === "strength" && !(input.structure.strength_items ?? []).length) issues.push({ path: "structure.strength_items", message: "Add at least one exercise." });
  if (["steady_state", "distance_piece", "time_piece", "on_water"].includes(input.workout_type) && !blocks.length) issues.push({ path: "structure.blocks", message: "Add at least one block." });
  return issues;
}

export function mockPreview(input: TemplateInput): TemplatePreview {
  const issues = validateMock(input);
  if (issues.length) return { ok: false, issues, summary: null };
  return { ok: true, issues: [], summary: mockSummary(input.structure, input.target_zone ?? null), signature: signature(input.structure), planned: {} };
}

export function createMockTemplate(input: TemplateInput): WorkoutTemplate {
  const issues = validateMock(input);
  if (issues.length) throw new Error(`${issues[0].path}: ${issues[0].message}`);
  const t = make(nextId++, input);
  templates.push(t);
  return t;
}

export function updateMockTemplate(id: number, patch: Partial<TemplateInput>): WorkoutTemplate {
  const t = mockTemplate(id);
  if (t.is_example) throw new Error("Examples are read-only — duplicate it to make your own copy.");
  const merged: TemplateInput = { ...t, ...patch, structure: patch.structure ?? t.structure } as TemplateInput;
  const issues = validateMock(merged);
  if (issues.length) throw new Error(`${issues[0].path}: ${issues[0].message}`);
  const next = make(id, merged, { archived: t.archived, created_at: t.created_at, duplicated_from_id: t.duplicated_from_id });
  templates = templates.map((x) => (x.id === id ? next : x));
  return next;
}

export function duplicateMockTemplate(id: number, name?: string): WorkoutTemplate {
  const t = mockTemplate(id);
  const copy = make(nextId++, { ...t, name: name ?? `${t.name} (copy)`, tags: t.tags.filter((x) => x !== "example") } as TemplateInput, { duplicated_from_id: t.id });
  templates.push(copy);
  return copy;
}

export function archiveMockTemplate(id: number, archived: boolean): WorkoutTemplate {
  const t = mockTemplate(id);
  t.archived = archived;
  return t;
}

export function scheduleMockTemplate(id: number, input: ScheduleInput): PlannedWorkout[] {
  const t = mockTemplate(id);
  if (t.archived) throw new Error("This template is archived — unarchive it before scheduling.");
  const rows = createMockPlanned({
    date: input.date, session_type: t.session_type, title: t.name, start_time: input.start_time ?? null,
    duration_min: t.summary.total_duration_s != null ? t.summary.total_duration_s / 60 : null, distance_m: t.summary.total_distance_m,
    target_zone: t.target_zone, description: t.description,
    repeat: input.repeat ? { weekdays: input.repeat.weekdays, until: input.repeat.until ?? null, count: input.repeat.count ?? null } : null,
  });
  return setMockTemplateId(rows.map((r) => r.id), t.id);
}

export const MOCK_LIBRARY_DATES = { today: todayISO(), week: weekStart(todayISO()), next: addDays(todayISO(), 1) };
