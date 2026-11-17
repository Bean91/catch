import type {
  LbBoardFilters,
  LbBoardInfo,
  LbBoardResponse,
  LbEntry,
  LbModEntry,
  LbModQueue,
  LbPrefs,
  LbPreview,
  LbProfile,
  LbResult,
  LbResultRef,
  LbSettingsPatch,
  LbState,
  Verification,
} from "./types";

// Mock state for the leaderboards (?mock=1). In-memory per page load. The mock does its own tiny ranking so the screens can be walked
// end to end; the real server is the only place ranking, eligibility and age rules live.

const BOARDS: LbBoardInfo[] = [
  { board_key: "500m", label: "500 m", kind: "distance", ranks_by: "fastest time" },
  { board_key: "1000m", label: "1,000 m", kind: "distance", ranks_by: "fastest time" },
  { board_key: "2000m", label: "2,000 m", kind: "distance", ranks_by: "fastest time" },
  { board_key: "5000m", label: "5,000 m", kind: "distance", ranks_by: "fastest time" },
  { board_key: "6000m", label: "6,000 m", kind: "distance", ranks_by: "fastest time" },
  { board_key: "30min", label: "30 minutes", kind: "timed", ranks_by: "furthest distance" },
  { board_key: "60min", label: "60 minutes", kind: "timed", ranks_by: "furthest distance" },
];
const AGE_BANDS = ["U14", "U15", "U16", "U17", "U18", "U19", "19-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"];

function e(id: string, name: string, board: string, result: string, tenths: number, v: Verification, extra: Partial<LbEntry> = {}): LbEntry & { tenths: number } {
  const label = BOARDS.find((b) => b.board_key === board)!.label;
  return {
    entry_id: id, athlete_id: `a-${id}`, name, board_key: board, board_label: label, result, split_500m: board.endsWith("m") ? "1:38.0" : null,
    verification: v, verification_label: v === "verified" ? "Verified" : v === "provider_linked" ? "Provider-linked" : "Unverified",
    age_label: null, age_provenance: null, weight_class: null, date_label: null, note: null, tenths, ...extra,
  };
}

const FIXTURES: (LbEntry & { tenths: number })[] = [
  e("e1", "River Otter", "2000m", "6:18.4", 3784, "verified", { age_label: "30-39", age_provenance: "as reported to Concept2" }),
  e("e2", "Anonymous rower", "2000m", "6:24.0", 3840, "verified", { age_label: "U19", age_provenance: "self-declared" }),
  e("e3", "Sculler 9", "2000m", "6:24.0", 3840, "verified", { weight_class: "Lightweight", date_label: "2026" }),
  e("e4", "Weekend Warrior", "2000m", "6:41.7", 4017, "verified", { age_label: "50-59", age_provenance: "as reported to Concept2" }),
  e("e5", "Tape Measure", "2000m", "6:10.0", 3700, "provider_linked"),
  e("e6", "Typed In", "2000m", "6:30.0", 3900, "unverified"),
  e("e7", "River Otter", "5000m", "17:02.1", 10221, "verified"),
  e("e8", "Sculler 9", "30min", "8,214 m", 8214, "verified"),
];

let state: LbState = {
  available: true,
  is_moderator: typeof window !== "undefined" && window.location.search.includes("mod=1"),
  settings: { opted_in: false, date_precision: "none", show_age_band: false, show_weight_class: false, age_source: null, self_declared_band: null, min_age_attested: false, guardian_attested: false, consent_version: null },
  athlete: null,
  publications: [],
  clubs: [],
  moderation: { events: [], appeals: [] },
  age_bands: AGE_BANDS,
  date_precisions: ["none", "year", "month", "day"],
  min_age: 13,
  guardian_below: 16,
};
let published: (LbEntry & { tenths: number; status: "active" | "hidden" | "removed" })[] = [];
let withdrawnRefs = new Set<string>();
let nextEvent = 1;

const RESULTS: LbResult[] = [
  { ref: { kind: "concept2_result", id: 101 }, board_key: "2000m", board_label: "2,000 m", result: "6:34.2", split_500m: "1:38.6", verification: "verified", verification_label: "Verified", verification_explained: "", performed_on: "2026-10-14", published: null, entry_id: null },
  { ref: { kind: "concept2_result", id: 102 }, board_key: "5000m", board_label: "5,000 m", result: "17:40.0", split_500m: "1:46.0", verification: "provider_linked", verification_label: "Provider-linked", verification_explained: "", performed_on: "2026-10-02", published: null, entry_id: null },
  { ref: { kind: "piece", id: 7 }, board_key: "6000m", board_label: "6,000 m", result: "21:20.0", split_500m: "1:46.7", verification: "unverified", verification_label: "Unverified", verification_explained: "", performed_on: "2026-09-20", published: null, entry_id: null },
];
const MEANING: Record<Verification, string> = {
  verified: "Fetched through your own Concept2 account and flagged verified by Concept2. Catch can authenticate where this result came from; it does not confirm who rowed it or the conditions.",
  provider_linked: "From a source you connected, but not every verified condition is met (for example Concept2 hasn't flagged it verified).",
  unverified: "Typed or photographed by you. Catch has no way to authenticate it.",
};

function rank<T extends { tenths: number; board_key: string }>(rows: T[]): (T & { rank: number })[] {
  const timed = rows[0]?.board_key.endsWith("min");
  const sorted = [...rows].sort((a, b) => (timed ? b.tenths - a.tenths : a.tenths - b.tenths));
  let rk = 0;
  let prev: number | null = null;
  return sorted.map((r, i) => {
    if (r.tenths !== prev) {
      rk = i + 1;
      prev = r.tenths;
    }
    return { ...r, rank: rk };
  });
}

function strip(r: LbEntry & { tenths?: number; status?: string }): LbEntry {
  const { tenths: _t, status: _s, ...rest } = r as LbEntry & { tenths?: number; status?: string };
  return rest;
}

export function mockLbBoards() {
  return { boards: BOARDS, age_bands: AGE_BANDS };
}

export function mockLbBoard(key: string, f: LbBoardFilters): LbBoardResponse {
  const mine = published.filter((p) => p.board_key === key && p.status === "active");
  let rows = [...FIXTURES.filter((x) => x.board_key === key), ...mine].map((x) => ({ ...x }));
  if (f.age) rows = rows.filter((x) => x.age_label === f.age);
  if (f.weight === "lightweight") rows = rows.filter((x) => x.weight_class === "Lightweight");
  const verified = rank(rows.filter((x) => x.verification === "verified")).map((x) => ({ ...strip(x), rank: x.rank, is_you: mine.some((m) => m.entry_id === x.entry_id) }));
  const others = f.verification === "include_unverified" ? rank(rows.filter((x) => x.verification !== "verified")).map((x) => ({ ...strip(x), rank: x.rank, is_you: mine.some((m) => m.entry_id === x.entry_id) })) : [];
  const info = BOARDS.find((b) => b.board_key === key)!;
  return {
    context: { board_key: key, label: info.label, ranks_by: info.ranks_by, age: f.age ?? null, weight: f.weight ?? "any", club: f.club ?? null, verification: f.verification ?? "verified", ranked_athletes: verified.length, ties: "Equal results share a rank (1, 2, 2, 4). One best result per athlete." },
    entries: verified,
    unverified: others,
    you: [...verified, ...others].find((x) => x.is_you) ?? null,
    total: verified.length,
    offset: 0,
    limit: 50,
  };
}

export function mockLbMe(): LbState {
  return JSON.parse(JSON.stringify(state));
}

function ensureAthlete(handle: string | null | undefined, mode: "handle" | "anonymous") {
  state.athlete = { athlete_id: "a-me", handle: handle ?? state.athlete?.handle ?? null, display_mode: mode, active: true };
}

export function mockLbSaveSettings(p: LbSettingsPatch): LbState["settings"] {
  const s = state.settings;
  if (p.date_precision) s.date_precision = p.date_precision;
  if (p.show_age_band !== undefined) s.show_age_band = p.show_age_band;
  if (p.show_weight_class !== undefined) s.show_weight_class = p.show_weight_class;
  if (p.self_declared_band !== undefined) {
    s.self_declared_band = p.self_declared_band;
    s.age_source = p.self_declared_band ? "self_declared" : null;
  }
  if (p.attest_min_age) s.min_age_attested = true;
  if (p.attest_guardian) s.guardian_attested = true;
  if (state.athlete && (p.handle !== undefined || p.display_mode)) ensureAthlete(p.handle ?? state.athlete.handle, p.display_mode ?? state.athlete.display_mode);
  return { ...s };
}

export function mockLbOptIn(p: LbSettingsPatch & { confirm?: boolean }): LbState {
  if (!p.confirm) throw new Error("Confirm that you want to appear on public leaderboards.");
  if (p.display_mode !== "anonymous" && !p.handle) throw new Error("Choose a public handle, or switch to anonymous.");
  mockLbSaveSettings(p);
  ensureAthlete(p.handle, p.display_mode ?? "handle");
  state.settings.opted_in = true;
  state.settings.consent_version = 1;
  return mockLbMe();
}

export function mockLbOptOut(): LbState {
  published.forEach((p) => {
    state.moderation.events.unshift({ id: nextEvent++, entry_id: p.entry_id, from_status: p.status, to_status: "withdrawn", actor_kind: "user", reason_code: "user_opted_out", reason_text: "The athlete opted out of public leaderboards.", created_at: new Date().toISOString() });
  });
  published = [];
  state.publications.forEach((p) => (p.status = "withdrawn"));
  state.settings.opted_in = false;
  if (state.athlete) state.athlete.active = false;
  return mockLbMe();
}

export function mockLbResults(): LbResult[] {
  return RESULTS.map((r) => {
    const pub = state.publications.find((p) => p.entry_id === r.entry_id && p.status !== "withdrawn");
    return { ...r, verification_explained: MEANING[r.verification], published: pub ? (pub.status as LbResult["published"]) : null, entry_id: pub ? pub.entry_id : null };
  });
}

function view(ref: LbResultRef, prefs: LbPrefs, id: string): LbEntry & { tenths: number } {
  const r = RESULTS.find((x) => x.ref.kind === ref.kind && x.ref.id === ref.id)!;
  const s = state.settings;
  const precision = prefs.date_precision ?? s.date_precision;
  const showAge = prefs.show_age_band ?? s.show_age_band;
  const showWeight = prefs.show_weight_class ?? s.show_weight_class;
  const tenths = r.board_key.endsWith("min") ? 8000 : r.board_key === "2000m" ? 3942 : r.board_key === "5000m" ? 10600 : 12800;
  return {
    ...e(id, state.athlete?.display_mode === "anonymous" ? "Anonymous rower" : state.athlete?.handle ?? "You", r.board_key, r.result, tenths, r.verification, {
      age_label: showAge && s.self_declared_band ? s.self_declared_band : null,
      age_provenance: showAge && s.self_declared_band ? "self-declared" : null,
      weight_class: showWeight ? "Open (heavyweight)" : null,
      date_label: precision === "none" ? null : precision === "year" ? "2026" : precision === "month" ? "2026-10" : "2026-10-14",
      note: prefs.note_public ? prefs.note ?? null : null,
    }),
    athlete_id: "a-me",
  };
}

export function mockLbPreview(ref: LbResultRef, prefs: LbPrefs): LbPreview {
  if (!state.settings.opted_in) throw new Error("Opt in to public leaderboards first.");
  if (!state.settings.self_declared_band && !state.settings.min_age_attested) throw new Error("Confirm your age first: attest that you are old enough, or add an age band.");
  const v = strip(view(ref, prefs, "preview"));
  const disclosures = ["Everything in this preview is public to signed-in Catch users. Nothing else about you or your training is shared.", v.date_label ? "Only the year of the result is shown, not the exact date." : "No date is shown."];
  return { entry: v, preview_hash: JSON.stringify(v), disclosures, ranked: v.verification === "verified" };
}

export function mockLbPublish(ref: LbResultRef, prefs: LbPrefs, confirm: boolean, hash: string): { published: boolean; entry: LbEntry } {
  if (!confirm) throw new Error("Confirm publishing after reviewing the preview.");
  const pv = mockLbPreview(ref, prefs);
  if (pv.preview_hash !== hash) throw new Error("The preview is out of date. Review it again before publishing.");
  const id = `mine-${published.length + 1}`;
  const full = { ...view(ref, prefs, id), status: "active" as const };
  published.push(full);
  state.publications.unshift({ entry_id: id, board_key: full.board_key, verification: full.verification, status: "active", note: prefs.note ?? null, note_public: !!prefs.note_public, created_at: new Date().toISOString() });
  RESULTS.forEach((r) => {
    if (r.ref.kind === ref.kind && r.ref.id === ref.id) r.entry_id = id;
  });
  return { published: true, entry: strip(full) };
}

export function mockLbWithdraw(entryId: string, confirm: boolean): { withdrawn: boolean } {
  if (!confirm) throw new Error("Confirm taking this result down.");
  const p = state.publications.find((x) => x.entry_id === entryId);
  if (p) {
    state.moderation.events.unshift({ id: nextEvent++, entry_id: entryId, from_status: p.status, to_status: "withdrawn", actor_kind: "user", reason_code: "user_withdrawn", reason_text: "Withdrawn by the athlete.", created_at: new Date().toISOString() });
    p.status = "withdrawn";
  }
  published = published.filter((x) => x.entry_id !== entryId);
  withdrawnRefs.add(entryId);
  return { withdrawn: true };
}

export function mockLbProfile(id: string): LbProfile {
  if (id === "a-me") {
    return { athlete_id: "a-me", name: state.athlete?.display_mode === "anonymous" ? "Anonymous rower" : state.athlete?.handle ?? "You", results: published.filter((p) => p.status === "active").map(strip) };
  }
  const rows = FIXTURES.filter((x) => x.athlete_id === id || x.entry_id === id.replace(/^a-/, ""));
  if (!rows.length) throw new Error("Not found.");
  return { athlete_id: id, name: rows[0].name, results: rows.map(strip) };
}

export function mockLbReport(_entryId: string, reason: string): { reported: boolean; hidden_for_review: boolean } {
  if (!reason) throw new Error("reason required");
  return { reported: true, hidden_for_review: false };
}

export function mockLbAppeal(entryId: string, text: string) {
  if (!text.trim()) throw new Error("Say why you think this decision should change.");
  const a = { id: state.moderation.appeals.length + 1, entry_id: entryId, text, status: "open" as const, resolution_text: null, created_at: new Date().toISOString(), resolved_at: null };
  state.moderation.appeals.unshift(a);
  return a;
}

export function mockLbCreateClub(name: string) {
  const club = { club_id: `c${state.clubs.length + 1}`, name };
  state.clubs.push(club);
  return { ...club, join_code: "A1B2C3D4" };
}
export function mockLbJoinClub(code: string) {
  if (code.trim().toUpperCase() !== "A1B2C3D4") throw new Error("That join code isn't valid.");
  const club = { club_id: "c-joined", name: "River Rowing Club" };
  if (!state.clubs.some((c) => c.club_id === club.club_id)) state.clubs.push(club);
  return club;
}
export function mockLbLeaveClub(id: string) {
  state.clubs = state.clubs.filter((c) => c.club_id !== id);
  return { left: true };
}

let modQueue: LbModQueue = {
  reports: [{ entry_id: "e6", reporters: 2, last_reported_at: "2026-11-10T09:00:00Z", status: "active", board_key: "2000m", reasons: ["not_a_real_result", "not_a_real_result"] }],
  appeals: [{ id: 1, entry_id: "e5", text: "This is my result; the Concept2 logbook shows it.", status: "open", resolution_text: null, created_at: "2026-11-11T09:00:00Z", resolved_at: null, entry_status: "hidden" }],
  non_active: [{ entry_id: "e5", status: "hidden", board_key: "2000m" }],
};
export function mockLbModQueue(): LbModQueue {
  return JSON.parse(JSON.stringify(modQueue));
}
export function mockLbModEntry(id: string): LbModEntry {
  return {
    entry: { entry_id: id, board_key: "2000m", value: 3900, verification: "unverified", status: "active", handle: "Typed In", age_label: null, weight_class: null, date_label: null, note: null },
    events: [],
  };
}
export function mockLbModerate(id: string, action: string, reason: string) {
  if (!reason.trim()) throw new Error("A reason is required.");
  modQueue.reports = modQueue.reports.filter((r) => r.entry_id !== id);
  return { status: action === "remove" ? "removed" : action === "hide" ? "hidden" : "active" };
}
export function mockLbResolve(id: number, outcome: string, reason: string) {
  if (!reason.trim()) throw new Error("A reason is required.");
  modQueue.appeals = modQueue.appeals.filter((a) => a.id !== id);
  return { id, status: outcome };
}
