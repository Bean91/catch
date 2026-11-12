// ?mock=1 fixtures for technique notes and coach feedback. In the mock the viewer is the athlete.
// Entries cover each state the UI has to show distinctly: private vs shared notes, a coach-written
// entry (read-only for the athlete) that was edited and answered, and one the athlete logged.
import { addDays, todayISO } from "./dates";
import type {
  FeedbackEntry,
  FeedbackFilters,
  FeedbackInput,
  FeedbackRevision,
  FocusArea,
  TechniqueNote,
  TechniqueNoteInput,
  WorkoutRef,
} from "./types";

const NOTE_DISCLAIMER = "Catch can't observe technique from this data — these are the athlete's and coach's own words, not a measurement.";
const WORKOUT: WorkoutRef = { id: 6, title: "5 x 1k with Ana", date: addDays(todayISO(), -2) };

let notes: TechniqueNote[] = [];
let feedback: FeedbackEntry[] = [];
let history: Record<number, FeedbackRevision[]> = {};
let nextNoteId = 100;
let nextFbId = 100;

function note(p: Partial<TechniqueNote> & { id: number; category: TechniqueNote["category"]; text: string }): TechniqueNote {
  return {
    visibility: "private", shared_with_coach: false, workout: null, piece: null, date: null, media: [], note: NOTE_DISCLAIMER,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...p,
  };
}

function fb(p: Partial<FeedbackEntry> & { id: number; text: string; date: string }): FeedbackEntry {
  return {
    author: { role: "coach", id: "coach:1", name: "Coach Sam" }, coach_name: null, created_via: "mcp", focus_areas: [], visibility: "shared",
    shared: true, workout: null, event: null, planned: null, athlete_response: null, athlete_response_at: null, edited: false,
    edit_count: 0, can_edit: false, can_respond: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...p,
  };
}

function seed() {
  const t = todayISO();
  notes = [
    note({ id: 1, category: "catch", text: "Reaching with the arms before the body has finished swinging over. Think hands, body, then slide.", workout: WORKOUT, date: addDays(t, -2) }),
    note({ id: 2, category: "sequencing", text: "Legs-body-arms felt cleaner in the second half.", visibility: "coach", shared_with_coach: true, workout: WORKOUT, date: addDays(t, -2) }),
    note({ id: 3, category: "posture", text: "Hips collapse when tired. Check at the 500m marks.", date: addDays(t, -9) }),
    note({ id: 4, category: "rate_control", text: "General cue: lengthen the recovery, don't rush the slide.", visibility: "coach", shared_with_coach: true, media: [{ url: "https://example.org/rate-drill", label: "Rate drill video" }] }),
  ];
  feedback = [
    fb({
      id: 1, date: addDays(t, -2), text: "Good rhythm in the last three pieces. Keep your hands moving away first at the finish.",
      focus_areas: ["finish", "sequencing"], workout: WORKOUT, athlete_response: "Will focus on the hands-away cue next session.",
      athlete_response_at: new Date().toISOString(), edited: true, edit_count: 1, created_via: "mcp",
    }),
    fb({ id: 2, date: addDays(t, -6), text: "Race plan: hold rate 30 for the first 500, then settle.", focus_areas: ["racing", "rate_control"], author: { role: "coach", id: "coach:2", name: "Coach Lee" } }),
    fb({
      id: 3, date: addDays(t, -8), text: "Told me to sit taller through the drive.", coach_name: "Coach Kim", focus_areas: ["posture"],
      author: { role: "athlete", id: "owner", name: "You" }, visibility: "private", shared: false, can_edit: true, can_respond: true, created_via: "web",
    }),
  ];
  history = {
    1: [{ revision_no: 1, kind: "edit", text: "Good rhythm in the last three pieces.", focus_areas: ["finish"], visibility: "shared", athlete_response: null, edited_by: "Coach Sam", edited_at: addDays(t, -1) + "T09:00:00Z" }],
  };
}
seed();

export function resetMockCoaching() {
  seed();
}

export function mockNotes(q: { workout_id?: number; piece_id?: number; date?: string; category?: string }): TechniqueNote[] {
  return notes
    .filter((n) => q.workout_id == null || n.workout?.id === q.workout_id)
    .filter((n) => q.piece_id == null || n.piece?.id === q.piece_id)
    .filter((n) => !q.date || n.date === q.date)
    .filter((n) => !q.category || n.category === q.category);
}

export function createMockNote(input: TechniqueNoteInput): TechniqueNote {
  if (!input.text?.trim()) throw new Error("text is required");
  const n = note({
    id: nextNoteId++, category: input.category, text: input.text.trim(), visibility: input.visibility ?? "private",
    shared_with_coach: (input.visibility ?? "private") === "coach", date: input.date ?? null, media: input.media ?? [],
    workout: input.canonical_id ? { ...WORKOUT, id: input.canonical_id } : null,
  });
  notes.unshift(n);
  return n;
}

export function updateMockNote(id: number, patch: Partial<TechniqueNoteInput>): TechniqueNote {
  const n = notes.find((x) => x.id === id);
  if (!n) throw new Error(`No technique note with id ${id}`);
  if (patch.text !== undefined) n.text = patch.text;
  if (patch.category) n.category = patch.category;
  if (patch.visibility) {
    n.visibility = patch.visibility;
    n.shared_with_coach = patch.visibility === "coach";
  }
  if (patch.media) n.media = patch.media;
  return n;
}

export function deleteMockNote(id: number) {
  notes = notes.filter((n) => n.id !== id);
}

export function mockFeedback(f: FeedbackFilters): { feedback: FeedbackEntry[]; coaches: string[] } {
  const needle = f.coach?.trim().toLowerCase();
  const rows = feedback
    .filter((e) => !needle || (e.coach_name ?? e.author.name).toLowerCase().includes(needle))
    .filter((e) => !f.category || e.focus_areas.includes(f.category as FocusArea))
    .filter((e) => !f.from || e.date >= f.from)
    .filter((e) => !f.to || e.date <= f.to)
    .sort((a, b) => (a.date < b.date ? 1 : -1));
  const coaches = [...new Set(feedback.filter((e) => e.author.role === "coach" || e.coach_name).map((e) => e.coach_name ?? e.author.name))].sort();
  return { feedback: rows, coaches };
}

export function createMockFeedback(input: FeedbackInput): FeedbackEntry {
  if (!input.text?.trim()) throw new Error("text is required");
  const e = fb({
    id: nextFbId++, date: input.date ?? todayISO(), text: input.text.trim(), coach_name: input.coach_name?.trim() || null,
    focus_areas: input.focus_areas ?? [], author: { role: "athlete", id: "owner", name: "You" }, visibility: input.visibility ?? "shared",
    shared: (input.visibility ?? "shared") === "shared", can_edit: true, created_via: "web",
  });
  feedback.unshift(e);
  return e;
}

export function updateMockFeedback(id: number, patch: Partial<FeedbackInput>): FeedbackEntry {
  const e = feedback.find((x) => x.id === id);
  if (!e) throw new Error(`No feedback entry with id ${id}`);
  if (!e.can_edit) throw new Error("Only the author can edit this feedback");
  history[id] = [...(history[id] ?? []), { revision_no: (history[id]?.length ?? 0) + 1, kind: "edit", text: e.text, focus_areas: e.focus_areas, visibility: e.visibility, athlete_response: e.athlete_response, edited_by: e.author.name, edited_at: new Date().toISOString() }];
  if (patch.text !== undefined) e.text = patch.text;
  if (patch.focus_areas) e.focus_areas = patch.focus_areas;
  if (patch.visibility) {
    e.visibility = patch.visibility;
    e.shared = patch.visibility === "shared";
  }
  e.edited = true;
  e.edit_count = history[id].filter((h) => h.kind === "edit").length;
  return e;
}

export function respondMockFeedback(id: number, response: string | null): FeedbackEntry {
  const e = feedback.find((x) => x.id === id);
  if (!e) throw new Error(`No feedback entry with id ${id}`);
  history[id] = [...(history[id] ?? []), { revision_no: (history[id]?.length ?? 0) + 1, kind: "response", text: e.text, focus_areas: e.focus_areas, visibility: e.visibility, athlete_response: e.athlete_response, edited_by: "You", edited_at: new Date().toISOString() }];
  e.athlete_response = response?.trim() || null;
  e.athlete_response_at = e.athlete_response ? new Date().toISOString() : null;
  return e;
}

export function deleteMockFeedback(id: number) {
  const e = feedback.find((x) => x.id === id);
  if (e && !e.can_edit) throw new Error("Only the author can delete this feedback");
  feedback = feedback.filter((x) => x.id !== id);
}

export function mockHistory(id: number): FeedbackRevision[] {
  if (!feedback.some((x) => x.id === id)) throw new Error(`No feedback entry with id ${id}`);
  return history[id] ?? [];
}
