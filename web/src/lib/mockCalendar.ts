// ?mock=1 fixtures for the calendar. Mutable in-memory state so the UI can be exercised
// (create / move / link / skip / delete) with no backend. Dates are relative to the
// browser's *local* today, never a UTC slice.
import { addDays, daysBetween, todayISO, weekStart } from "./dates";
import type {
  CalendarCompleted,
  CalendarDay,
  CalendarPayload,
  EventInput,
  EventOverview,
  EventProjection,
  MatchSuggestion,
  PhaseInput,
  PlanWeekSummary,
  PlannedDisplayStatus,
  PlannedInput,
  PlannedWorkout,
  ReviewFlag,
  SessionType,
  PlanPhase,
  UpcomingEvent,
} from "./types";

const today = () => todayISO();
const MON = () => weekStart(today());

const FAMILY: Record<string, string | null> = { erg: "rowing", on_water: "rowing", run: "running", bike: "cycling", strength: "strength" };
const TITLES: Record<string, string> = {
  erg: "Erg session", on_water: "On-water session", run: "Run", bike: "Ride", strength: "Strength",
  cross: "Cross-training", test: "Test", rest: "Rest day", other: "Session",
};

let nextPlannedId = 100;
let nextEventId = 50;
let nextPhaseId = 10;

function planned(p: Partial<PlannedWorkout> & { id: number; date: string; session_type: SessionType; title: string }): PlannedWorkout {
  return {
    start_time: null, sport_family: FAMILY[p.session_type] ?? null, duration_min: null, distance_m: null, target_zone: null,
    intensity_note: null, description: null, structure: [], status: "planned", display_status: "planned", linked_canonical_id: null,
    series_id: null, template_id: null, event_id: null, notes: null, coach_feedback: null, planned_minutes: p.duration_min ?? 0, ...p,
  };
}

function seed() {
  const m = MON();
  const t = today();
  const w2 = addDays(m, 14); // two Mondays ahead: a calm 200-minute week...
  const w3 = addDays(m, 21); // ...followed by a 420-minute one, which is what raises the review flag
  return {
    planned: [
      planned({ id: 1, date: addDays(t, -9), session_type: "erg", title: "Steady UT2", duration_min: 70, target_zone: "UT2", linked_canonical_id: 11 }),
      planned({ id: 2, date: addDays(t, -8), session_type: "strength", title: "Legs + core", duration_min: 45, linked_canonical_id: 12 }),
      planned({ id: 3, date: addDays(t, -3), session_type: "erg", title: "Steady UT2", duration_min: 60, target_zone: "UT2" }),
      planned({ id: 4, date: addDays(t, -2), session_type: "on_water", title: "Long row", duration_min: 80, target_zone: "UT2" }),
      planned({ id: 5, date: addDays(t, -1), session_type: "bike", title: "Easy spin", duration_min: 45, target_zone: "UT2", status: "skipped" }),
      planned({ id: 6, date: t, session_type: "erg", title: "4 × 5 min at threshold", duration_min: 55, target_zone: "AT", structure: [{ reps: 4, work_min: 5, rest_min: 2, zone: "AT" }], coach_feedback: "Keep the rate under 26." }),
      planned({ id: 7, date: addDays(t, 1), session_type: "rest", title: "Rest day" }),
      planned({ id: 8, date: addDays(t, 2), session_type: "erg", title: "Pyramid", duration_min: 75, target_zone: "UT1" }),
      planned({ id: 9, date: addDays(t, 3), session_type: "strength", title: "Upper body", duration_min: 45 }),
      planned({ id: 10, date: w2, session_type: "erg", title: "Steady UT2", duration_min: 100, target_zone: "UT2" }),
      planned({ id: 13, date: addDays(w2, 3), session_type: "on_water", title: "Row", duration_min: 100, target_zone: "UT2" }),
      planned({ id: 14, date: w3, session_type: "erg", title: "Long UT2", duration_min: 140, target_zone: "UT2" }),
      planned({ id: 15, date: addDays(w3, 2), session_type: "on_water", title: "Long row", duration_min: 140, target_zone: "UT2" }),
      planned({ id: 16, date: addDays(w3, 4), session_type: "erg", title: "Steady UT2", duration_min: 140, target_zone: "UT2" }),
    ] as PlannedWorkout[],
    completed: [
      { id: 11, title: "Erg 70 min", sport_family: "rowing", category: "erg", start: `${addDays(t, -9)}T07:00:00`, duration_min: 68, distance_m: 15200, avg_hr: 138, is_test: false, test_type: null, notes: null, rpe: 4, excluded_from_totals: false, linked_planned_id: null },
      { id: 12, title: "Strength", sport_family: "strength", category: "strength", start: `${addDays(t, -8)}T17:00:00`, duration_min: 50, distance_m: null, avg_hr: 110, is_test: false, test_type: null, notes: null, rpe: null, excluded_from_totals: false, linked_planned_id: null },
      { id: 6, title: "Morning row", sport_family: "rowing", category: "on_water", start: `${addDays(t, -2)}T06:30:00`, duration_min: 78, distance_m: 16500, avg_hr: 147, is_test: false, test_type: null, notes: "Felt smooth.", rpe: 5, excluded_from_totals: false, linked_planned_id: null },
    ] as CalendarCompleted[],
    events: [
      { id: 1, ref: "event:1", name: "Head of the Charles", date: addDays(today(), 38), type: "race", distance: "5000m", distance_m: 5000, boat_class: "1x", priority: "A", goal_time: "19:30", result: null, location: "Boston, MA", goals: "Top 10. Clean start, even second 2.5k.", notes: null, has_pacing_plan: false, days_to_go: 38, taper: false },
      { id: 2, ref: "event:2", name: "Club 2k test", date: addDays(today(), 12), type: "2k_test", distance: "2000m", distance_m: 2000, boat_class: null, priority: "B", goal_time: "6:45", result: null, location: "Home erg", goals: null, notes: null, has_pacing_plan: true, days_to_go: 12, taper: false },
    ] as UpcomingEvent[],
    phases: [
      {
        id: 1, kind: "specific_prep", name: "Build to the 2k", start_date: addDays(m, -14), end_date: addDays(m, 27), goals: "Raise threshold power; two strength sessions a week.",
        target_minutes_per_week: 420, target_sessions_per_week: 6, target_strength_sessions_per_week: 2, target_zone_pct: { UT2: { min: 70 }, AN: { max: 5 } }, event_id: 2,
        coach_approved: true, coach_approved_at: new Date(Date.now() - 6 * 86400000).toISOString(), coach_approved_by: "Coach Sam", coach_approved_note: "Looks right for this block.", edited_since_approval: false,
      },
    ] as PlanPhase[],
  };
}

let state = seed();

export function resetMockCalendar() {
  state = seed();
}

function displayStatus(p: PlannedWorkout): PlannedDisplayStatus {
  if (p.session_type === "rest") return "rest";
  if (p.linked_canonical_id != null) return "linked";
  if (p.status === "skipped") return "skipped";
  if (p.date < today()) return "not_logged";
  return "planned";
}

function view(p: PlannedWorkout): PlannedWorkout {
  const completed = state.completed.find((c) => c.id === p.linked_canonical_id);
  void completed;
  return { ...p, display_status: displayStatus(p) };
}

function suggestions(): MatchSuggestion[] {
  // Same shape as the server's matcher: candidate pairs, closest day first, then a one-to-one
  // greedy assignment (so a workout is never offered for two sessions).
  const used = new Set<number>(state.planned.map((p) => p.linked_canonical_id).filter((v): v is number => v != null));
  const pairs: { gap: number; planned: PlannedWorkout; completed: CalendarCompleted }[] = [];
  for (const p of state.planned) {
    if (p.linked_canonical_id != null || p.session_type === "rest" || p.status === "skipped") continue;
    for (const c of state.completed) {
      if (declined.has(`${p.id}:${c.id}`)) continue;
      const gap = Math.abs(daysBetween((c.start ?? "").slice(0, 10), p.date));
      const fam = FAMILY[p.session_type];
      if (gap > 1 || (fam && c.sport_family !== fam)) continue;
      pairs.push({ gap, planned: p, completed: c });
    }
  }
  pairs.sort((a, b) => a.gap - b.gap);
  const out: MatchSuggestion[] = [];
  const usedPlanned = new Set<number>();
  for (const { gap, planned: p, completed: c } of pairs) {
    if (used.has(c.id) || usedPlanned.has(p.id)) continue;
    used.add(c.id);
    usedPlanned.add(p.id);
    out.push({ planned_id: p.id, canonical_id: c.id, score: gap === 0 ? 0.9 : 0.7, reasons: [gap === 0 ? "same day" : "one day apart", "same sport", "similar duration"] });
  }
  return out;
}

function phaseView(p: PlanPhase): PlanPhase {
  return { ...p };
}

export function mockCalendar(from: string, to: string): CalendarPayload {
  const days: CalendarDay[] = [];
  for (let d = from; d <= to; d = addDays(d, 1)) {
    const phase = state.phases.find((p) => p.start_date <= d && d <= p.end_date);
    days.push({
      date: d,
      planned: state.planned.filter((p) => p.date === d).map(view),
      completed: state.completed
        .filter((c) => (c.start ?? "").slice(0, 10) === d)
        .map((c) => ({ ...c, linked_planned_id: state.planned.find((p) => p.linked_canonical_id === c.id)?.id ?? null })),
      events: state.events.filter((e) => e.date === d),
      phase_id: phase?.id ?? null,
    });
  }
  return {
    from, to, today: today(), days,
    phases: state.phases.filter((p) => p.start_date <= to && p.end_date >= from).map(phaseView),
    suggestions: suggestions().filter((s) => state.planned.some((p) => p.id === s.planned_id && p.date >= from && p.date <= to)),
  };
}

export function mockPlanWeekSummary(week: string): PlanWeekSummary {
  const start = weekStart(week);
  const end = addDays(start, 6);
  const rows = state.planned.filter((p) => p.date >= start && p.date <= end && p.session_type !== "rest");
  const live = rows.filter((p) => p.status !== "skipped");
  const zoneMin: Record<string, number> = { UT2: 0, UT1: 0, AT: 0, TR: 0, AN: 0 };
  for (const p of live) if (p.target_zone) zoneMin[p.target_zone] += p.duration_min ?? 0;
  const plannedMin = live.reduce((a, p) => a + (p.duration_min ?? 0), 0);
  const pct = (z: Record<string, number>) => {
    const t = Object.values(z).reduce((a, b) => a + b, 0);
    return t ? Object.fromEntries(Object.entries(z).map(([k, v]) => [k, Math.round((v / t) * 1000) / 10])) : {};
  };
  const done = state.completed.filter((c) => {
    const d = (c.start ?? "").slice(0, 10);
    return d >= start && d <= end && d <= today();
  });
  const doneMin = done.reduce((a, c) => a + (c.duration_min ?? 0), 0);
  const phase = state.phases.find((p) => p.start_date <= addDays(start, 3) && addDays(start, 3) <= p.end_date) ?? null;
  const targets = phase
    ? { minutes: phase.target_minutes_per_week, sessions: phase.target_sessions_per_week, strength_sessions: phase.target_strength_sessions_per_week, zone_pct: phase.target_zone_pct, source: "phase" as const }
    : { minutes: 300, sessions: 5, strength_sessions: null, zone_pct: null, source: "settings" as const };
  const prev = (() => {
    const ps = addDays(start, -7);
    return state.planned.filter((p) => p.date >= ps && p.date < start && p.session_type !== "rest" && p.status !== "skipped").reduce((a, p) => a + (p.duration_min ?? 0), 0);
  })();
  const flags: ReviewFlag[] = [];
  if (prev > 0 && plannedMin - prev >= 60 && (plannedMin - prev) / prev > 0.25) {
    const approved = phase?.coach_approved ?? false;
    flags.push({
      week_start: start, kind: "increase", planned_minutes: plannedMin, reference_minutes: prev, reference: "previous planned week",
      pct_change: Math.round(((plannedMin - prev) / prev) * 1000) / 10, phase_approved: approved,
      message: approved
        ? `The planned week of ${start} is ${plannedMin} min, about ${Math.round(((plannedMin - prev) / prev) * 100)}% above the previous planned week (${prev} min). It sits in a coach-approved phase, so this is worth confirming with your coach — nothing has been changed.`
        : `Based on the data so far (not certain): The planned week of ${start} is ${plannedMin} min, about ${Math.round(((plannedMin - prev) / prev) * 100)}% above the previous planned week (${prev} min). Worth a look before you commit to it — nothing has been changed, and only you (or your coach) can decide.`,
    });
  }
  const completedZones = { UT2: doneMin * 0.78, UT1: doneMin * 0.12, AT: doneMin * 0.08, TR: doneMin * 0.02, AN: 0 };
  return {
    week_start: start, week_end: end,
    planned: {
      minutes: plannedMin, distance_m: live.reduce((a, p) => a + (p.distance_m ?? 0), 0), sessions: live.length,
      strength_sessions: live.filter((p) => p.session_type === "strength").length, skipped_sessions: rows.length - live.length,
      zone_minutes: zoneMin, zone_pct: pct(zoneMin),
    },
    completed: {
      minutes: doneMin, sessions: done.length, strength_sessions: done.filter((c) => c.sport_family === "strength").length,
      zone_minutes: completedZones, zone_pct: pct(completedZones), zones_available: start <= MON(),
    },
    targets, comparison: [], phase: phase ? phaseView(phase) : null, review_flags: flags,
  };
}

export function createMockPlanned(body: PlannedInput): PlannedWorkout[] {
  const dates = [body.date];
  if (body.repeat) {
    const wds = body.repeat.weekdays?.length ? body.repeat.weekdays : [((new Date(body.date + "T00:00:00").getDay() + 6) % 7)];
    const limit = body.repeat.until ?? addDays(body.date, 7 * ((body.repeat.count ?? 4) + 1));
    dates.length = 0;
    for (let d = body.date; d <= limit && dates.length < (body.repeat.count ?? 200); d = addDays(d, 1)) {
      if (wds.includes((new Date(d + "T00:00:00").getDay() + 6) % 7)) dates.push(d);
    }
  }
  const series = dates.length > 1 ? `series-${nextPlannedId}` : null;
  const rows = dates.map((d) =>
    planned({
      id: nextPlannedId++, date: d, session_type: body.session_type, title: body.title || TITLES[body.session_type],
      start_time: body.start_time ?? null, duration_min: body.duration_min ?? null, distance_m: body.distance_m ?? null,
      target_zone: body.target_zone ?? null, intensity_note: body.intensity_note ?? null, description: body.description ?? null,
      structure: body.structure ?? [], notes: body.notes ?? null, coach_feedback: body.coach_feedback ?? null, series_id: series,
      planned_minutes: body.duration_min ?? 0,
    }),
  );
  state.planned.push(...rows);
  touchPhasesFor(rows.map((r) => r.date));
  return rows.map(view);
}

// Provenance for a plan scheduled from a library template (session 22). The real server sets this in
// the same transaction; the mock does it after the fact.
export function setMockTemplateId(ids: number[], templateId: number): PlannedWorkout[] {
  const out: PlannedWorkout[] = [];
  for (const row of state.planned) {
    if (ids.includes(row.id)) {
      row.template_id = templateId;
      out.push(view(row));
    }
  }
  return out;
}

function touchPhasesFor(dates: string[]) {
  for (const ph of state.phases) if (ph.coach_approved && dates.some((d) => d >= ph.start_date && d <= ph.end_date)) ph.edited_since_approval = true;
}

export function updateMockPlanned(id: number, patch: Partial<PlannedInput>, scope: string): PlannedWorkout[] {
  const row = state.planned.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  const targets = scope === "this_and_following" && row.series_id ? state.planned.filter((p) => p.series_id === row.series_id && p.date >= row.date) : [row];
  const shift = patch.date ? daysBetween(row.date, patch.date) : 0;
  for (const t of targets) {
    const { date: _d, repeat: _r, ...rest } = patch;
    void _d;
    void _r;
    Object.assign(t, rest);
    if (patch.date) t.date = scope === "this_and_following" ? addDays(t.date, shift) : patch.date;
    if (patch.session_type && !("sport_family" in patch)) t.sport_family = FAMILY[patch.session_type] ?? null;
    t.planned_minutes = t.duration_min ?? 0;
  }
  touchPhasesFor(targets.map((t) => t.date));
  return targets.map(view);
}

export function deleteMockPlanned(id: number, scope: string): number {
  const row = state.planned.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  const doomed = scope === "this_and_following" && row.series_id ? state.planned.filter((p) => p.series_id === row.series_id && p.date >= row.date) : [row];
  state.planned = state.planned.filter((p) => !doomed.includes(p));
  return doomed.length;
}

export function linkMockPlanned(id: number, canonicalId: number): PlannedWorkout {
  const row = state.planned.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  if (state.planned.some((p) => p.linked_canonical_id === canonicalId && p.id !== id)) throw new Error("That workout is already linked to another planned session");
  row.linked_canonical_id = canonicalId;
  row.status = "planned";
  return view(row);
}

export function unlinkMockPlanned(id: number): PlannedWorkout {
  const row = state.planned.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  row.linked_canonical_id = null;
  return view(row);
}

export function skipMockPlanned(id: number, skipped: boolean): PlannedWorkout {
  const row = state.planned.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  row.status = skipped ? "skipped" : "planned";
  return view(row);
}

export function declineMockMatch(plannedId: number, canonicalId: number): void {
  // The mock matcher is stateless; remember the decline by parking the pair in a set.
  declined.add(`${plannedId}:${canonicalId}`);
}
const declined = new Set<string>();

function eventDays(date: string): number {
  return daysBetween(today(), date);
}

export function mockUpcomingEvents(limit = 5): UpcomingEvent[] {
  return state.events
    .filter((e) => e.date >= today())
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, limit)
    .map((e) => ({ ...e, days_to_go: eventDays(e.date), taper: (e.priority === "A" || e.priority === "B") && eventDays(e.date) <= 14 }));
}

export function mockEvents(): UpcomingEvent[] {
  return state.events.map((e) => ({ ...e, days_to_go: eventDays(e.date) }));
}

export function createMockEvent(body: EventInput): UpcomingEvent {
  const e: UpcomingEvent = {
    id: nextEventId++, ref: `event:${nextEventId}`, name: body.name, date: body.date, type: body.type, distance: body.distance ?? null,
    distance_m: body.distance_m ?? null, boat_class: body.boat_class ?? null, priority: (body.priority as UpcomingEvent["priority"]) ?? null,
    goal_time: body.goal_time ?? null, result: null, location: body.location ?? null, goals: body.goals ?? null, notes: body.notes ?? null,
    has_pacing_plan: false, days_to_go: eventDays(body.date), taper: false,
  };
  state.events.push(e);
  return e;
}

export function updateMockEvent(id: number, patch: Partial<EventInput>): UpcomingEvent {
  const e = state.events.find((x) => x.id === id);
  if (!e) throw new Error("not found");
  Object.assign(e, patch);
  e.days_to_go = eventDays(e.date);
  return e;
}

export function deleteMockEvent(id: number): void {
  state.events = state.events.filter((e) => e.id !== id);
  for (const p of state.planned) if (p.event_id === id) p.event_id = null;
  for (const ph of state.phases) if (ph.event_id === id) ph.event_id = null;
}

export function mockEventOverview(id: number): EventOverview {
  const e = state.events.find((x) => x.id === id);
  if (!e) throw new Error("not found");
  const ev = { ...e, days_to_go: eventDays(e.date), taper: (e.priority === "A" || e.priority === "B") && eventDays(e.date) <= 14 };
  const phase = state.phases.find((p) => p.start_date <= today() && today() <= p.end_date) ?? null;
  return {
    event: ev, weeks_to_go: Math.max(0, Math.round((ev.days_to_go / 7) * 10) / 10), phase,
    planned_sessions_before_event: state.planned.filter((p) => p.date >= today() && p.date <= e.date && p.session_type !== "rest").length,
    test_type: e.distance_m === 2000 ? "2000m" : null,
    tests: [
      { kind: "test", canonical_id: 21, piece_id: null, test_type: "2000m", title: "2k test", date: addDays(today(), -60), distance_m: 2000, duration_s: 412 },
      { kind: "test", canonical_id: 22, piece_id: null, test_type: "2000m", title: "2k test", date: addDays(today(), -30), distance_m: 2000, duration_s: 409 },
      { kind: "test", canonical_id: 23, piece_id: null, test_type: "2000m", title: "2k test", date: addDays(today(), -9), distance_m: 2000, duration_s: 406.5 },
    ],
    pacing_plan: e.has_pacing_plan ? { goal_time_s: 405, style: "even", distance_m: 2000, splits: [0, 1, 2, 3].map((i) => ({ split_index: i, target_split_s: 101.25 })) } : null,
    linked_phases: state.phases.filter((p) => p.event_id === id),
  };
}

export function mockEventProjection(id: number): EventProjection {
  const e = state.events.find((x) => x.id === id);
  if (!e) throw new Error("not found");
  const base = { event_id: id, event_date: e.date, days_to_go: eventDays(e.date), goal_time_s: e.goal_time === "6:45" ? 405 : null };
  if (e.distance_m !== 2000) {
    return {
      ...base, test_type: null, available: false, trend: null, predict_2k: null, history: [], gap_to_goal_s: null, uncertainty: null,
      reason: "Projections exist for standard erg test distances (500 m to 6 km). Set this event's distance to one of those to see one.",
      assumptions: [],
    };
  }
  return {
    ...base, test_type: "2000m", available: true, reason: null, value_s: 402.8, range_s: [400.1, 405.5],
    trend: { value: 402.8, range: [400.1, 405.5], n_points: 3, slope_s_per_day: -0.06, explanation: "Linear trend through 3 results." },
    predict_2k: { value: 100.7, predicted_time_s: 402.8, band: "moderate", explanation: "Scaled from recent efforts with Paul's law." },
    history: [
      { date: addDays(today(), -60), duration_s: 412 }, { date: addDays(today(), -30), duration_s: 409 }, { date: addDays(today(), -9), duration_s: 406.5 },
    ],
    assumptions: [
      "Straight-line trend through 3 confirmed 2000m result(s), extended to the event date.",
      "Assumes training and conditions between now and then resemble the period the results came from.",
      "Erg results only: wind, current, water and race-day conditions are not modelled.",
      "The 2k estimate scales recent efforts at other distances with Paul's law (about +5 s per 500 m for each doubling of distance).",
    ],
    uncertainty: "The band is ±1 standard deviation of how far past results sit from the trend line — a rough guide to spread, not a guarantee. Only 3 result(s) back it, so treat it loosely.",
    gap_to_goal_s: base.goal_time_s ? 402.8 - base.goal_time_s : null,
  };
}

export function mockPhases(): PlanPhase[] {
  return state.phases.map(phaseView);
}

export function createMockPhase(body: PhaseInput): PlanPhase {
  if (state.phases.some((p) => body.start_date <= p.end_date && p.start_date <= body.end_date)) throw new Error("That date range overlaps another training phase");
  const row: PlanPhase = {
    id: nextPhaseId++, kind: body.kind, name: body.name, start_date: body.start_date, end_date: body.end_date, goals: body.goals ?? null,
    target_minutes_per_week: body.target_minutes_per_week ?? null, target_sessions_per_week: body.target_sessions_per_week ?? null,
    target_strength_sessions_per_week: body.target_strength_sessions_per_week ?? null, target_zone_pct: body.target_zone_pct ?? null,
    event_id: body.event_id ?? null, coach_approved: false, coach_approved_at: null, coach_approved_by: null, coach_approved_note: null, edited_since_approval: false,
  };
  state.phases.push(row);
  return row;
}

export function updateMockPhase(id: number, patch: Partial<PhaseInput>): PlanPhase {
  const row = state.phases.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  const start = patch.start_date ?? row.start_date;
  const end = patch.end_date ?? row.end_date;
  if (state.phases.some((p) => p.id !== id && start <= p.end_date && p.start_date <= end)) throw new Error("That date range overlaps another training phase");
  Object.assign(row, patch);
  if (row.coach_approved) row.edited_since_approval = true;
  return row;
}

export function deleteMockPhase(id: number): void {
  state.phases = state.phases.filter((p) => p.id !== id);
}

export function approveMockPhase(id: number, by: string | null, note: string | null): PlanPhase {
  const row = state.phases.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  Object.assign(row, { coach_approved: true, coach_approved_at: new Date().toISOString(), coach_approved_by: by, coach_approved_note: note, edited_since_approval: false });
  return row;
}

export function unapproveMockPhase(id: number): PlanPhase {
  const row = state.phases.find((p) => p.id === id);
  if (!row) throw new Error("not found");
  Object.assign(row, { coach_approved: false, coach_approved_at: null, coach_approved_by: null, coach_approved_note: null, edited_since_approval: false });
  return row;
}
