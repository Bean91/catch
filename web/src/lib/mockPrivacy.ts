import type { ConsentRequest, DeviceToken, OauthGrant, PrivacySummary, Restriction, SharingState, SharingUpdate, ToolCallRow } from "./privacy";

const wait = <T,>(v: T, ms = 150): Promise<T> => new Promise((r) => setTimeout(() => r(v), ms));

const CATEGORIES = [
  ["wellness", "Recovery, sleep and body data", true],
  ["workouts", "Workouts and training", true],
  ["nutrition", "Nutrition", true],
  ["notes_checkins", "Notes and check-ins", true],
  ["memory", "Coach memory", true],
  ["calendar_library", "Calendar, plans and library", false],
  ["photos", "Photos you ask the coach to read", true],
] as const;

let sharing: SharingState = {
  consent_version: 1,
  consented: false,
  consented_at: null,
  age_band: null,
  guardian_ack: false,
  categories: CATEGORIES.map(([key, label, health]) => ({ key, label, description: `What "${label}" covers.`, health, enabled: false })),
};
let tokens: DeviceToken[] = [
  { id: 1, name: "Laptop (Claude Desktop)", role: "athlete", scope: "read", created_at: "2026-11-01T08:00:00Z", last_used_at: "2026-11-17T20:00:00Z", expires_at: "2027-01-30T08:00:00Z" },
];
let removed: Record<string, number> = {};
let restrictions: Restriction[] = [];
let grants: OauthGrant[] = [
  { grant_id: "g1", client_name: "Claude Desktop", scopes: ["catch:read"], created_at: "2026-11-10T08:00:00Z", last_used_at: "2026-11-17T20:00:00Z", expires_at: "2027-02-08T08:00:00Z" },
];

const BASE_ROWS: Record<string, number> = { conversations: 14, memory: 6, gps: 38, media: 3, notes_checkins: 112, nutrition: 540, wellness_body: 400, notification_log: 63, ai_usage: 220 };
const LABELS: Record<string, [string, string]> = {
  conversations: ["Coach conversations", "Every chat with the coach, including the tool results saved in it."],
  memory: ["Coach memory", "The facts and goals the coach remembers about you."],
  gps: ["GPS tracks, routes and weather", "Location data attached to your workouts. The workouts themselves stay."],
  media: ["Uploaded photos", "Photos of erg screens you attached to pieces, including any stored files."],
  notes_checkins: ["Notes and check-ins", "Your workout notes, morning check-ins and illness-flag responses."],
  nutrition: ["Nutrition logs", "Everything you logged or saved in Nutrition."],
  wellness_body: ["Recovery, sleep and body data", "A connected source will import them again on its next sync."],
  notification_log: ["Notification history", "The record of notifications Catch sent you."],
  ai_usage: ["AI usage history", "The log of AI calls and what they cost."],
};

export const mockPrivacy = {
  summary: (): Promise<PrivacySummary> =>
    wait({
      categories: Object.entries(LABELS).map(([key, [label, note]]) => ({ key, label, note, rows: removed[key] ? 0 : BASE_ROWS[key] })),
      totals: { workouts: 128, tables_exported: 52 },
      public: { leaderboard_profile: { active: true, display_mode: "handle" }, published_results: 2, club_memberships: 1 },
    }),
  sharing: () => wait(sharing),
  updateSharing: (b: SharingUpdate) => {
    const young = ["u19", "u18", "u17", "u16", "u15", "u14"].includes(b.age_band ?? sharing.age_band ?? "");
    const ack = b.guardian_ack || sharing.guardian_ack;
    if (!sharing.consented && !b.acknowledge) return Promise.reject(Object.assign(new Error("Read and acknowledge what is shared before turning anything on."), { status: 422 }));
    const next = sharing.categories.map((c) => ({ ...c, enabled: b.categories && c.key in b.categories ? !!b.categories[c.key] : c.enabled }));
    if (young && !ack && next.some((c) => c.enabled && c.health)) {
      return Promise.reject(Object.assign(new Error("Because you said you're under 19, a parent or guardian needs to know before health data is shared with an AI. Tick the box to confirm."), { status: 422 }));
    }
    sharing = { ...sharing, categories: next, age_band: b.age_band ?? sharing.age_band, guardian_ack: ack, consented: sharing.consented || !!b.acknowledge, consented_at: sharing.consented_at ?? new Date().toISOString() };
    return wait(sharing);
  },
  withdraw: () => {
    sharing = { ...sharing, consented: false, consented_at: null, categories: sharing.categories.map((c) => ({ ...c, enabled: false })) };
    return wait(sharing);
  },
  toolCalls: (): Promise<ToolCallRow[]> =>
    wait([
      { tool: "get_today", via: "mcp", as: "athlete", write: false, confirmed: false, outcome: "ok", at: "2026-11-17T20:00:00Z" },
      { tool: "add_note", via: "mcp", as: "athlete", write: true, confirmed: false, outcome: "preview", at: "2026-11-17T19:58:00Z" },
    ]),
  tokens: () => wait(tokens),
  revoke: (id: number) => {
    tokens = tokens.filter((t) => t.id !== id);
    return wait({ ok: true });
  },
  revokeAll: () => {
    const n = tokens.length;
    tokens = [];
    return wait({ revoked: n });
  },
  deleteCategory: (key: string) => {
    const n = removed[key] ? 0 : BASE_ROWS[key] ?? 0;
    removed = { ...removed, [key]: 1 };
    return wait({ category: key, rows_removed: n, files_removed: key === "media" ? 3 : 0 });
  },
  restrictions: () => wait({ restrictions }),
  appeal: (id: number, text: string): Promise<Restriction> => {
    restrictions = restrictions.map((r) => (r.id === id ? { ...r, appeal: { status: "open", text, resolution: null } } : r));
    return wait(restrictions.find((r) => r.id === id)!);
  },
  grants: () => wait(grants),
  endGrant: (id: string) => {
    grants = grants.filter((g) => g.grant_id !== id);
    return wait({ ok: true });
  },
  consent: (): Promise<ConsentRequest> =>
    wait({
      client_name: "Claude Desktop",
      redirect_host: "claude.ai",
      scopes: [
        { scope: "catch:read", text: "Read your training data (only the categories you've allowed the AI to see)" },
        { scope: "catch:write", text: "Propose changes: add notes, log food, plan sessions… — each one is shown to you first and saved only when you confirm" },
      ],
    }),
  decide: (approve: boolean) => wait({ redirect_url: approve ? "/settings/privacy?mock=1&approved=1" : "/settings/privacy?mock=1&denied=1" }),
  download: () => wait(undefined),
};
