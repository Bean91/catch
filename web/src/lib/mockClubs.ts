// Fixtures for the clubs UI (?mock=1). In-memory, per page load. This file stands in for the server, so it fabricates the `capabilities` and
// approval rules the REAL server decides; the production browser bundle never computes any of that.
//   ?mock=1&role=athlete|coach|admin|owner   your role in "River Rowing Club" (default admin)
//   &junior=1[&jrole=athlete|coach|admin|owner]    adds "Junior Squad", a junior club (default role athlete)
//   &noprofile=1                             you have no club profile yet
import type {
  ClubModDetail, ClubModReport, Club, ClubAuditEvent, ClubAudience, ClubBoard, ClubChallengeDetail, ClubChallengeRow, ClubInvite, ClubInvitePreview, ClubJoinRequestRow, ClubMember, ClubMyRequest, ClubPost, ClubProfile,
  ClubRole, ClubSessionItem, ClubStanding, ClubSummary, ClubsMine, NewChallengeInput, NewClubInput,
} from "./types";

const params = typeof location === "undefined" ? new URLSearchParams() : new URLSearchParams(location.search);
const MY_ROLE = (params.get("role") as ClubRole | null) ?? "admin";
const JUNIOR = params.get("junior") === "1";
const JUNIOR_ROLE = (params.get("jrole") as ClubRole | null) ?? "athlete";

const BANDS = ["adult", "U19", "U18", "U17", "U16", "U15", "U14"];
const today = () => new Date().toISOString().slice(0, 10);
const plus = (days: number) => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);

const STAFF: ClubRole[] = ["owner", "admin", "coach"];

function caps(role: ClubRole | null, audience: ClubAudience): Record<string, boolean> | null {
  if (!role) return null;
  const staff = STAFF.includes(role);
  const admin = role === "owner" || role === "admin";
  return {
    view: true, edit_club: admin, edit_logo: admin, delete_club: role === "owner", transfer_ownership: role === "owner", set_roles: admin, remove_member: staff,
    see_requests: staff, see_audit: staff, post: staff, take_down_post: staff, delete_post: admin, hide_result: staff, join_challenge: true, link_workout: true,
    share_result: true, report: true, block: true, leave: role !== "owner",
    publish_directly: audience === "junior" ? role === "coach" || role === "owner" : staff,
    decide_athlete_requests: audience === "junior" ? role === "coach" || role === "owner" : staff, decide_coach_requests: admin,
    create_athlete_invite: staff, create_coach_invite: admin,
  };
}

type ClubData = {
  club: Club;
  members: ClubMember[];
  posts: ClubPost[];
  sessions: ClubSessionItem[];
  challenges: ClubChallengeDetail[];
  requests: ClubJoinRequestRow[];
  invites: ClubInvite[];
  audit: ClubAuditEvent[];
  board: ClubBoard;
  rules: string;
};

let nextId = 100;
let profile: ClubProfile = params.get("noprofile") === "1"
  ? { exists: false, bands: BANDS, min_age: 13, guardian_below: 16 }
  : { exists: true, handle: "You Rower", age_band: "adult", age_class: "adult", guardian_consent: false, bands: BANDS, min_age: 13, guardian_below: 16 };

function member(ref: string, handle: string, role: ClubRole, isMe = false): ClubMember {
  return { member_ref: ref, handle, role, joined: "2026-03", is_me: isMe, blocked: false, can_manage: false };
}

function baseClub(id: string, name: string, audience: ClubAudience, role: ClubRole | null, extra: Partial<Club> = {}): Club {
  return {
    club_id: id, name, description: null, location: null, visibility: "private", audience, join_policy: audience === "junior" ? "request" : "invite", rules: null,
    status: "active", has_logo: false, member_count: 14, my_role: role, capabilities: caps(role, audience), created_at: "2026-01-10T12:00:00Z", ...extra,
  };
}

function standing(rank: number, name: string, value: string, raw: number, me = false): ClubStanding {
  return { rank, name, value, raw, is_me: me, member_ref: `s-${name}` };
}

function challengeRow(id: number, title: string, metric: ClubChallengeRow["metric"], goal: number | null, extra: Partial<ClubChallengeDetail> = {}): ClubChallengeDetail {
  return {
    id, title, description: null, metric, sport: "rowing", start: plus(-7), end: plus(21), goal, status: "active", phase: "open", participants: 3, joined: false, my_value: null,
    can_join: true, can_approve: false, rules: [
      "Distance counts up to 100 km in total.", "No more than 30 km a day and 150 km a week can count, so training harder than that earns nothing extra.",
      "Only rowing sessions count.", "Only activities recorded by a connected source (Garmin, Concept2, Whoop) count; results typed into Catch don't, and a Concept2 result must be flagged verified by Concept2. Garmin and Whoop don't say whether a workout was entered by hand, so Catch can't tell. Each activity counts once, for one account.",
      "Equal scores share a rank (1, 2, 2, 4). There is no hidden tie-break.", "Joining is open until the end date. Standings settle 2 days after the end, then freeze.",
      "Nothing about weight, calories, recovery or sleep is used or shown.",
    ],
    standings: [standing(1, "Mira Oar", "42.0 km", 42000), standing(2, "Tom Catch", "31.5 km", 31500), standing(2, "Ana Stroke", "31.5 km", 31500), standing(4, "Dev Finish", "12.0 km", 12000)],
    my_detail: null, excused_weeks: [], settles_on: plus(23), target_per_week: null, min_session_minutes: 20, ...extra,
  };
}

function seedRiver(): ClubData {
  const role = MY_ROLE;
  const club = baseClub("river", "River Rowing Club", "adult", role, {
    description: "Sunday rows from the boathouse, an erg night in winter, and one regatta a year.", location: "Boston, MA", join_policy: "invite",
    rules: "Be on time. Look out for each other. No wake near moored boats.", pending: STAFF.includes(role) ? { requests: 1, posts: 0 } : undefined,
    my_prefs: { include_public_results: false, share_numbers: false, rules_accepted: true },
  });
  const members = [
    member("m-owner", "Riley Owner", "owner", role === "owner"), member("m-admin", "Sam Admin", "admin", role === "admin"), member("m-coach", "Casey Coach", "coach", role === "coach"),
    member("m-mira", "Mira Oar", "athlete"), member("m-tom", "Tom Catch", "athlete"), member("m-ana", "Ana Stroke", "athlete"), member("m-dev", "Dev Finish", "athlete"),
  ];
  if (role === "athlete") members.push(member("m-me", "You Rower", "athlete", true));
  return {
    club, members, rules: club.rules ?? "",
    posts: [
      { id: 1, title: "Sunday row moved to 7am", body: "Low tide, so we launch an hour earlier. Boathouse opens at 6:30.", status: "published", author: "Casey Coach", created_at: new Date().toISOString(), can_approve: false, decision_reason: null },
    ],
    sessions: [
      { id: 1, title: "Steady 60", type: "erg", date: plus(1), start_time: "06:30", duration_min: 60, distance_m: null, description: "Rate 18-20, conversational.", status: "published", participants: 5, i_took_part: false, can_approve: false },
      { id: 2, title: "2k test day", type: "test", date: plus(6), start_time: "07:00", duration_min: null, distance_m: 2000, description: null, status: "published", participants: 0, i_took_part: false, can_approve: false },
    ],
    challenges: [challengeRow(1, "Metres Cup", "distance", 100000)],
    requests: [{ request_id: 1, handle: "Jess Newcomer", role: "athlete", age_class: "adult", message: "I row Sundays at another club and just moved here.", guardian_consent: null, created_at: new Date().toISOString(), can_decide: STAFF.includes(role) }],
    invites: [], audit: [{ action: "club_created", by: "Riley Owner", about: null, reason: "adult club, private", at: "2026-01-10T12:00:00Z" }],
    board: {
      board_key: "2000m", board_label: "2,000 m", note: "Only verified results are ranked. Equal results share a rank. Members choose what they share here; nothing else about them is shown.",
      ranked: [
        { rank: 1, name: "Mira Oar", result: "6:31.2", split_500m: "1:37.8", verification: "verified", verification_label: "Verified", source: "club", is_me: false, result_id: null, member_ref: "m-mira" },
        { rank: 2, name: "Tom Catch", result: "6:44.0", split_500m: "1:41.0", verification: "verified", verification_label: "Verified", source: "club", is_me: false, result_id: null, member_ref: "m-tom" },
      ],
      unverified: [{ rank: 1, name: "Ana Stroke", result: "6:58.5", split_500m: "1:44.6", verification: "provider_linked", verification_label: "Provider-linked", source: "club", is_me: false, result_id: null, member_ref: "m-ana" }],
    },
  };
}

function seedJunior(): ClubData {
  const role = JUNIOR_ROLE;
  const club = baseClub("junior", "Junior Squad", "junior", role, {
    description: "Under-19 squad. Everyone here is approved by a coach.", rules: "Be kind. Row hard. Respect your coach. Nothing leaves the club.", member_count: 9,
    pending: role === "coach" || role === "owner" ? { requests: 1, posts: 1 } : undefined, my_prefs: { include_public_results: false, share_numbers: false, rules_accepted: true },
  });
  const members = [member("j-owner", "Pat Owner", "owner", role === "owner"), member("j-coach", "Coach Dana", "coach", role === "coach"), member("j-1", "Kit Junior", "athlete"), member("j-2", "Lou Junior", "athlete")];
  if (role === "athlete") members.push(member("j-me", "You Junior", "athlete", true));
  if (role === "admin") members.push(member("j-me", "You Admin", "admin", true));
  const pendingPost: ClubPost = { id: 2, title: "Regatta weekend", body: "Saturday, 8am at the boathouse. Parent forms due Friday.", status: "pending", author: "Pat Owner", created_at: new Date().toISOString(), can_approve: role === "coach" || role === "owner", decision_reason: null };
  return {
    club, members, rules: club.rules ?? "",
    posts: [{ id: 1, title: "Welcome to the squad", body: "Practice is Tuesday and Thursday at 6am.", status: "published", author: "Coach Dana", created_at: new Date().toISOString(), can_approve: false, decision_reason: null }, ...(role === "athlete" ? [] : [pendingPost])],
    sessions: [{ id: 1, title: "Technique row", type: "on_water", date: plus(2), start_time: "06:00", duration_min: 75, distance_m: null, description: null, status: "published", participants: 3, i_took_part: false, can_approve: false }],
    challenges: [challengeRow(1, "Squad Cup", "sessions", 8, { standings: [standing(1, "Kit Junior", "6 sessions", 6), standing(2, "Lou Junior", "5 sessions", 5)], rules: ["Sessions count up to 8.", "A session must last at least 20 minutes to count.", "Equal scores share a rank (1, 2, 2, 4). There is no hidden tie-break.", "Nothing about weight, calories, recovery or sleep is used or shown."] })],
    requests: [{ request_id: 1, handle: "Rae Hopeful", role: "athlete", age_class: "youth", message: null, guardian_consent: true, created_at: new Date().toISOString(), can_decide: role === "coach" || role === "owner" }],
    invites: [], audit: [], board: { board_key: "2000m", board_label: "2,000 m", note: "Only verified results are ranked.", ranked: [], unverified: [] },
  };
}

const data: Record<string, ClubData> = { river: seedRiver() };
if (JUNIOR) data.junior = seedJunior();

const discoverable: Club[] = [
  baseClub("open", "Open Water Club", "adult", null, { visibility: "public", join_policy: "open", description: "Friendly masters crew. All levels, any boat.", location: "Boston, MA", member_count: 128, rules: "Be kind." }),
  baseClub("harbor", "Harbor Masters", "adult", null, { visibility: "public", join_policy: "request", description: "Competitive masters; regatta season April-October.", location: "Cambridge, MA", member_count: 46 }),
];

let myRequests: ClubMyRequest[] = [];

function mine(): Club[] {
  return Object.values(data).map((d) => d.club);
}

function audit(d: ClubData, action: string, reason: string) {
  d.audit.unshift({ action, by: "You Rower", about: null, reason, at: new Date().toISOString() });
}

function need(id: string): ClubData {
  const d = data[id];
  if (!d) throw new Error("Not found.");
  return d;
}

function roleOf(d: ClubData): ClubRole {
  return d.club.my_role as ClubRole;
}

function liveStatus(d: ClubData): "pending" | "published" {
  const c = d.club.capabilities;
  return c && c.publish_directly ? "published" : "pending";
}

export function mockClubsMine(): ClubsMine {
  return { clubs: mine(), profile, requests: myRequests };
}

export function mockClubsDiscover(q?: string): Club[] {
  const needle = (q ?? "").trim().toLowerCase();
  return discoverable.filter((c) => !data[c.club_id] && (!needle || c.name.toLowerCase().includes(needle)));
}

export function mockSaveProfile(input: { handle: string; age_band: string; attest_min_age: boolean; guardian_consent: boolean }): ClubProfile {
  if (!input.attest_min_age) throw new Error("Confirm you are 13 or older to use clubs.");
  if (!/^[A-Za-z0-9][A-Za-z0-9 _-]{1,22}[A-Za-z0-9]$/.test(input.handle.trim())) throw new Error("handle must be 3-24 characters: letters, numbers, spaces, - or _");
  const youth = input.age_band !== "adult";
  const needsGuardian = youth && Number(input.age_band.slice(1)) <= 16;
  if (needsGuardian && !input.guardian_consent) throw new Error("A parent or guardian must agree before someone under 16 can join a club. Tick the guardian box to confirm they do.");
  profile = { exists: true, handle: input.handle.trim(), age_band: input.age_band, age_class: youth ? "youth" : "adult", guardian_consent: needsGuardian && input.guardian_consent, bands: BANDS, min_age: 13, guardian_below: 16 };
  return profile;
}

export function mockCreateClub(input: NewClubInput): Club {
  if (profile.age_class !== "adult") throw new Error("Only adults can start a club. Ask a coach to start a junior club.");
  if (input.name.trim().length < 3) throw new Error("a club name is 3-40 characters");
  if (input.audience === "junior" && (input.visibility !== "private" || input.join_policy !== "request")) throw new Error("a junior club is always private and every new member needs a coach's approval");
  const id = `new-${nextId++}`;
  const club = baseClub(id, input.name.trim(), input.audience, "owner", { description: input.description ?? null, location: input.location ?? null, visibility: input.visibility, join_policy: input.join_policy, rules: input.rules ?? null, member_count: 1 });
  data[id] = { club, rules: input.rules ?? "", members: [member("me", profile.handle ?? "You", "owner", true)], posts: [], sessions: [], challenges: [], requests: [], invites: [], audit: [], board: { board_key: "2000m", board_label: "2,000 m", note: "", ranked: [], unverified: [] } };
  return club;
}

export function mockGetClub(id: string): Club {
  const d = data[id];
  if (d) return { ...d.club, member_count: d.members.length || d.club.member_count };
  const pub = discoverable.find((c) => c.club_id === id);
  if (!pub) throw new Error("Not found.");
  return pub;
}

export function mockMembers(id: string): { members: ClubMember[]; count: number } {
  const d = need(id);
  const me = roleOf(d);
  const rank: Record<ClubRole, number> = { owner: 3, admin: 2, coach: 1, athlete: 0 };
  const staffView = STAFF.includes(me);
  const members = d.members.map((m) => ({
    ...m,
    handle: m.blocked && !staffView ? "Blocked member" : m.handle,
    can_manage: !m.is_me && ((me === "owner" && m.role !== "owner") || (me === "admin" && rank[m.role] < 2) || (me === "coach" && m.role === "athlete")),
    ...(d.club.audience === "junior" && STAFF.includes(me) && m.role === "athlete" ? { guardian_consent: true } : {}),
  }));
  return { members, count: members.length };
}

export function mockSetRole(id: string, ref: string, role: ClubRole) {
  const d = need(id);
  const m = d.members.find((x) => x.member_ref === ref);
  if (!m) throw new Error("Not found.");
  if (d.club.audience === "junior" && m.role === "athlete" && role !== "athlete") throw new Error("a junior club's athletes are young members and its coaches and admins are adults");
  m.role = role;
  audit(d, "role_changed", `to ${role}`);
  return { member_ref: ref, role };
}

export function mockRemoveMember(id: string, ref: string, reason: string) {
  const d = need(id);
  if (!reason.trim()) throw new Error("A reason is required.");
  d.members = d.members.filter((m) => m.member_ref !== ref);
  d.audit.unshift({ action: "member_removed", by: "You Rower", about: "a member", reason, at: new Date().toISOString() });
  return { removed: true };
}

export function mockLeave(id: string) {
  const d = need(id);
  if (roleOf(d) === "owner") throw new Error("Your role in this club can't do that.");
  delete data[id];
  return { left: true };
}

export function mockTransfer(id: string, ref: string, confirm: boolean) {
  const d = need(id);
  if (!confirm) return { transferred: false, preview: "That member becomes the owner. You become an admin. Nothing changes until you confirm." };
  const m = d.members.find((x) => x.member_ref === ref);
  if (!m) throw new Error("Not found.");
  m.role = "owner";
  d.club.my_role = "admin";
  d.club.capabilities = caps("admin", d.club.audience);
  return { transferred: true };
}

export function mockDeleteClub(id: string, confirm: boolean) {
  const d = need(id);
  if (!confirm) return { deleted: false, preview: `This permanently deletes ${d.club.name}: its members, posts, sessions and challenges. Nothing is deleted until you confirm.` };
  delete data[id];
  return { deleted: true };
}

export function mockUpdateClub(id: string, patch: Partial<NewClubInput>): Club {
  const d = need(id);
  Object.assign(d.club, Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined)));
  audit(d, "club_updated", "settings changed");
  return d.club;
}

export function mockPrefs(id: string, patch: { include_public_results?: boolean; share_numbers?: boolean }) {
  const d = need(id);
  d.club.my_prefs = { ...(d.club.my_prefs ?? { include_public_results: false, share_numbers: false, rules_accepted: true }), ...patch };
  return d.club.my_prefs;
}

export function mockInvites(id: string): ClubInvite[] {
  return need(id).invites;
}

export function mockCreateInvite(id: string, role: "athlete" | "coach", days?: number, maxUses?: number): ClubInvite {
  const d = need(id);
  const inv: ClubInvite = { invite_id: nextId++, role, state: "active", expires_at: new Date(Date.now() + (days ?? 7) * 86400000).toISOString(), max_uses: maxUses ?? null, uses: 0, token: `mock-token-${role}-${nextId}`, created_at: new Date().toISOString() };
  d.invites.unshift({ ...inv, token: null });
  audit(d, "invite_created", `${role} invite`);
  return inv;
}

export function mockRevokeInvite(id: string, inviteId: number) {
  const d = need(id);
  const inv = d.invites.find((i) => i.invite_id === inviteId);
  if (inv) inv.state = "revoked";
  return inv;
}

export function mockRequests(id: string): ClubJoinRequestRow[] {
  return need(id).requests;
}

export function mockDecideRequest(id: string, requestId: number, approve: boolean, reason?: string) {
  const d = need(id);
  if (!approve && !(reason ?? "").trim()) throw new Error("A reason is required.");
  d.requests = d.requests.filter((r) => r.request_id !== requestId);
  if (d.club.pending) d.club.pending.requests = d.requests.length;
  audit(d, approve ? "request_approved" : "request_rejected", reason ?? "approved");
  return { status: approve ? "approved" : "rejected" };
}

export function mockPreviewInvite(token: string): ClubInvitePreview {
  if (!token || token === "bad") throw new Error("This invite link isn't valid any more.");
  const junior = token.includes("junior");
  return {
    club_id: junior ? "junior-x" : "river-x", name: junior ? "Junior Squad" : "River Rowing Club", description: junior ? "Under-19 squad." : "Sunday rows from the boathouse.", audience: junior ? "junior" : "adult",
    visibility: "private", join_policy: junior ? "request" : "invite", rules: "Be kind. Row hard. Respect your coach.", role: token.includes("coach") ? "coach" : "athlete", already_member: false,
    needs_profile: !profile.exists, cannot_join_because: junior && profile.age_class === "adult" && !token.includes("coach") ? "a junior club's athletes are young members and its coaches and admins are adults" : (!junior && profile.age_class === "youth" ? "adult clubs are for adults: young members join a junior club by invitation" : null),
    will_need_approval: junior,
  };
}

export function mockJoin(input: { token?: string; club_id?: string; message?: string; accept_rules?: boolean }) {
  if (!profile.exists) throw new Error("Choose a club handle and age group first.");
  const open = discoverable.find((c) => c.club_id === input.club_id);
  if (open && open.join_policy === "open") {
    const club = { ...open, my_role: "athlete" as ClubRole, capabilities: caps("athlete", "adult") };
    data[club.club_id] = { club, rules: club.rules ?? "", members: [member("me", profile.handle ?? "You", "athlete", true)], posts: [], sessions: [], challenges: [], requests: [], invites: [], audit: [], board: { board_key: "2000m", board_label: "2,000 m", note: "", ranked: [], unverified: [] } };
    return { status: "joined", club_id: club.club_id };
  }
  const name = open?.name ?? (input.token?.includes("junior") ? "Junior Squad" : "River Rowing Club");
  if (input.token?.includes("junior") || open) {
    myRequests.unshift({ request_id: nextId++, club_id: open?.club_id ?? "junior-x", club_name: name, role: input.token?.includes("coach") ? "coach" : "athlete", status: "pending", created_at: new Date().toISOString(), decision_reason: null });
    return { status: "requested", club_id: open?.club_id ?? "junior-x", needs: input.token?.includes("junior") ? "a coach's approval" : "approval from the club" };
  }
  const id = `joined-${nextId++}`;
  const club = baseClub(id, name, "adult", "athlete", { description: "Sunday rows from the boathouse.", rules: "Be kind.", member_count: 15 });
  data[id] = { club, rules: club.rules ?? "", members: [member("me", profile.handle ?? "You", "athlete", true)], posts: [], sessions: [], challenges: [], requests: [], invites: [], audit: [], board: { board_key: "2000m", board_label: "2,000 m", note: "", ranked: [], unverified: [] } };
  return { status: "joined", club_id: id };
}

export function mockWithdraw(requestId: number) {
  myRequests = myRequests.filter((r) => r.request_id !== requestId);
  return { withdrawn: true };
}

export function mockPosts(id: string): ClubPost[] {
  const d = need(id);
  const staff = STAFF.includes(roleOf(d));
  return d.posts.filter((p) => staff || p.status === "published").map((p) => ({ ...p, can_approve: p.status === "pending" && (roleOf(d) === "coach" || roleOf(d) === "owner") && d.club.audience === "junior" ? true : p.status === "pending" && d.club.audience === "adult" && staff }));
}

export function mockPost(id: string, title: string, body: string) {
  const d = need(id);
  if (!title.trim() || !body.trim()) throw new Error("a title is 1-80 characters");
  const status = liveStatus(d);
  d.posts.unshift({ id: nextId++, title: title.trim(), body: body.trim(), status, author: "You Rower", created_at: new Date().toISOString(), can_approve: false, decision_reason: null });
  audit(d, "post_created", status === "published" ? "published" : "held for a coach's approval");
  return { id: nextId, status, message: status === "published" ? null : "In a junior club a coach approves a post before members see it." };
}

export function mockDecidePost(id: string, kind: string, postId: number, action: string, reason?: string) {
  const d = need(id);
  if (action !== "approve" && !(reason ?? "").trim()) throw new Error("A reason is required.");
  const list = kind === "announcement" ? d.posts : kind === "session" ? d.sessions : d.challenges;
  const row = (list as { id: number; status: string }[]).find((x) => x.id === postId);
  if (!row) throw new Error("Not found.");
  row.status = action === "approve" ? (kind === "challenge" ? "active" : "published") : action === "reject" ? "rejected" : kind === "announcement" ? "hidden" : "cancelled";
  audit(d, `${kind}_${action}`, reason ?? "approved");
  return { id: postId, status: row.status };
}

export function mockCalendar(id: string): ClubSessionItem[] {
  const d = need(id);
  const staff = STAFF.includes(roleOf(d));
  return d.sessions.filter((s) => staff || s.status === "published").map((s) => ({ ...s, can_approve: s.status === "pending" && !!d.club.capabilities?.publish_directly }));
}

export function mockCreateSession(id: string, input: { title: string; session_type: string; date: string; start_time?: string; duration_min?: number; distance_m?: number; description?: string }) {
  const d = need(id);
  if (!input.title.trim()) throw new Error("a title is 1-80 characters");
  const status = liveStatus(d);
  d.sessions.push({ id: nextId++, title: input.title.trim(), type: input.session_type, date: input.date, start_time: input.start_time ?? null, duration_min: input.duration_min ?? null, distance_m: input.distance_m ?? null, description: input.description ?? null, status, participants: 0, i_took_part: false, can_approve: false });
  return { id: nextId, status, message: status === "published" ? null : "In a junior club a coach approves a session before members see it." };
}

export function mockLink(id: string, sessionId: number, share: boolean) {
  const s = need(id).sessions.find((x) => x.id === sessionId);
  if (!s) throw new Error("Not found.");
  if (!s.i_took_part) s.participants += 1;
  s.i_took_part = true;
  return { took_part: true, shared_numbers: share };
}

export function mockUnlink(id: string, sessionId: number) {
  const s = need(id).sessions.find((x) => x.id === sessionId);
  if (s && s.i_took_part) {
    s.i_took_part = false;
    s.participants = Math.max(0, s.participants - 1);
  }
  return { took_part: false };
}

export function mockSummary(id: string): ClubSummary {
  const d = need(id);
  const taken = d.sessions.reduce((n, s) => n + s.participants, 0);
  const sup = (count: number) => ({ count, shared: 2, total: null, mean: null, suppressed: true });
  return {
    sessions: d.sessions.length, participations: taken, members: d.members.length, mean_participants: d.sessions.length ? Math.round((taken / d.sessions.length) * 10) / 10 : null,
    attendance_rate: d.sessions.length && d.members.length ? Math.round((taken / (d.sessions.length * d.members.length)) * 100) / 100 : null, distance_m: sup(taken), duration_s: sup(taken),
    note: "Totals appear only when at least 3 members chose to share a number. No recovery, sleep, weight or nutrition data is ever included.", from: plus(-90), to: today(),
  };
}

export function mockChallenges(id: string): ClubChallengeRow[] {
  const d = need(id);
  const staff = STAFF.includes(roleOf(d));
  return d.challenges.filter((c) => staff || c.status === "active").map((c) => ({ ...c, can_approve: c.status === "pending" && !!d.club.capabilities?.publish_directly }));
}

export function mockCreateChallenge(id: string, input: NewChallengeInput) {
  const d = need(id);
  if ((input.metric === "distance" || input.metric === "time" || input.metric === "sessions") && !input.goal) throw new Error("set a goal: a challenge counts up to it and no further, so extra volume never earns more");
  if (input.start < today()) throw new Error("a challenge can't start in the past");
  const live = liveStatus(d) === "published";
  const row = challengeRow(nextId++, input.title, input.metric, input.goal ?? null, { start: input.start, end: input.end, status: live ? "active" : "pending", phase: live ? "open" : "pending", participants: 0, standings: [] });
  d.challenges.push(row);
  return { id: row.id, status: row.status, rules: row.rules, message: live ? null : "In a junior club a coach approves a challenge before members see it." };
}

export function mockChallenge(id: string, challengeId: number): ClubChallengeDetail {
  const c = need(id).challenges.find((x) => x.id === challengeId);
  if (!c) throw new Error("Not found.");
  return c;
}

export function mockJoinChallenge(id: string, challengeId: number) {
  const c = mockChallenge(id, challengeId);
  c.joined = true;
  c.can_join = false;
  c.my_value = "8.0 km";
  c.participants += 1;
  c.standings = [...c.standings, standing(5, "You Rower", "8.0 km", 8000, true)];
  return { joined: true, value: c.my_value };
}

export function mockLeaveChallenge(id: string, challengeId: number) {
  const c = mockChallenge(id, challengeId);
  c.joined = false;
  c.can_join = true;
  c.my_value = null;
  c.participants = Math.max(0, c.participants - 1);
  c.standings = c.standings.filter((s) => !s.is_me);
  return { joined: false };
}

export function mockExcuse(id: string, challengeId: number, week: string, excused: boolean) {
  const c = mockChallenge(id, challengeId);
  const set = new Set(c.excused_weeks);
  if (excused) set.add(week);
  else set.delete(week);
  c.excused_weeks = [...set].sort();
  return { excused_weeks: c.excused_weeks, value: c.my_value ?? "" };
}

export function mockBoard(id: string): ClubBoard {
  return need(id).board;
}

export function mockShareResult(id: string, note?: string) {
  const d = need(id);
  d.board.ranked.push({ rank: d.board.ranked.length + 1, name: "You Rower", result: "6:59.9", split_500m: "1:44.9", verification: "verified", verification_label: "Verified", source: "club", is_me: true, result_id: nextId++, member_ref: "me" });
  void note;
  return { shared: true, id: nextId, board_key: "2000m", verification: "verified" };
}

export function mockWithdrawResult(id: string, resultId: number) {
  const d = need(id);
  d.board.ranked = d.board.ranked.filter((r) => r.result_id !== resultId);
  return { withdrawn: true };
}

export function mockReport(id: string, targetType: string, reason: string) {
  const d = need(id);
  if (!["harassment", "unsafe", "inappropriate", "impersonation", "spam", "other"].includes(reason)) throw new Error("Choose what you're reporting and why.");
  void targetType;
  void d;
  return { reported: true, message: "Thanks. A platform moderator will review this. The club's staff are not told who reported." };
}

export function mockBlock(id: string, ref: string, blocked: boolean) {
  const m = need(id).members.find((x) => x.member_ref === ref);
  if (m) m.blocked = blocked;
  return { blocked };
}

export function mockAudit(id: string): ClubAuditEvent[] {
  return need(id).audit;
}

// --- Moderator (?mock=1&mod=1) ---------------------------------------------------------------------------------------------
let modReports: ClubModReport[] = [
  { club_id: "river", club_name: "River Rowing Club", club_status: "active", audience: "adult", target_type: "announcement", target_id: "1", reports: 2, reasons: ["inappropriate", "spam"], first_at: new Date().toISOString() },
  { club_id: "junior", club_name: "Junior Squad", club_status: "active", audience: "junior", target_type: "member", target_id: "j-1", reports: 1, reasons: ["harassment"], first_at: new Date().toISOString() },
];

export function mockModQueue(): { reports: ClubModReport[] } {
  return { reports: modReports };
}

export function mockModDetail(id: string): ClubModDetail {
  const r = modReports.filter((x) => x.club_id === id);
  return {
    club: { club_id: id, name: id === "junior" ? "Junior Squad" : "River Rowing Club", audience: id === "junior" ? "junior" : "adult", visibility: "private", status: "active", member_count: 14, description: null, rules: null },
    reports: r.map((x) => ({ target_type: x.target_type, target_id: x.target_id, reason: x.reasons[0], detail: null, at: x.first_at, about: x.target_type === "member" ? "Kit Junior" : null })),
    announcements: [{ id: 1, title: "Sunday row moved to 7am", body: "Low tide, so we launch an hour earlier.", status: "published" }],
    events: [{ action: "club_created", actor_kind: "staff", reason: "adult club, private", at: "2026-01-10T12:00:00Z" }],
  };
}

export function mockModAction(id: string, action: string, reason: string) {
  if (!reason.trim()) throw new Error("A reason is required.");
  modReports = modReports.filter((x) => x.club_id !== id);
  return { action };
}
