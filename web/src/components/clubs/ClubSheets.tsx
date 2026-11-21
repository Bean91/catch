import { todayISO, toISODate } from "../../lib/dates";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  createClub, createClubChallenge, createClubInvite, createClubSession, fetchLbResults, fetchWorkouts, linkClubWorkout, postClubAnnouncement, reportClub, saveClubProfile, shareClubResult,
} from "../../lib/api";
import { REPORT_REASONS_CLUB, SESSION_TYPES, metricLabel } from "../../lib/clubs";
import type { Club, ClubProfile, ClubSessionItem, NewChallengeInput, NewClubInput } from "../../lib/types";
import { publicOrigin } from "../../lib/native/apiBase";
import { ErrorLine, Field, Sheet, btn, btnPrimary, inputCls, refreshClub } from "./ClubBits";

type Base = { open: boolean; onOpenChange: (open: boolean) => void };

function useSubmit<T>(fn: () => Promise<T>, onDone: (r: T) => void) {
  const [error, setError] = useState<string | null>(null);
  const m = useMutation({ mutationFn: fn, onSuccess: (r) => { setError(null); onDone(r); }, onError: (e: Error) => setError(e.message || "That didn't work.") });
  return { error, setError, pending: m.isPending, run: () => m.mutate() };
}

// ---------------------------------------------------------------- profile

export function ProfileSheet({ open, onOpenChange, profile }: Base & { profile: ClubProfile }) {
  const qc = useQueryClient();
  const [handle, setHandle] = useState(profile.handle ?? "");
  const [band, setBand] = useState(profile.age_band ?? "adult");
  const [attest, setAttest] = useState(profile.exists);
  const [guardian, setGuardian] = useState(profile.guardian_consent ?? false);
  const youth = band !== "adult";
  const s = useSubmit(() => saveClubProfile({ handle, age_band: band, attest_min_age: attest, guardian_consent: guardian }), () => { refreshClub(qc); onOpenChange(false); });
  return (
    <Sheet open={open} onOpenChange={onOpenChange} testId="profile-sheet" title="Your club profile" description="Clubs show you by a handle you choose — never your real name or email. Your age group decides which clubs you can join.">
      <Field label="Handle" hint="3–24 characters. Pick something that isn't your full name.">
        <input value={handle} onChange={(e) => setHandle(e.target.value)} className={inputCls} data-testid="profile-handle" autoComplete="off" />
      </Field>
      <Field label="Age group" hint="Adults join adult clubs. Under-19s can join junior clubs only, by invitation, and a coach approves them. Catch can't verify age: please be honest.">
        <select value={band} onChange={(e) => setBand(e.target.value)} className={inputCls} data-testid="profile-band">
          {profile.bands.map((b) => (
            <option key={b} value={b}>{b === "adult" ? "19 or over" : `Under ${b.slice(1)}`}</option>
          ))}
        </select>
      </Field>
      <label className="flex items-start gap-2 text-sm text-text-secondary">
        <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} className="mt-1 h-4 w-4" data-testid="profile-attest" />I am {profile.min_age} or older.
      </label>
      {youth && (
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="checkbox" checked={guardian} onChange={(e) => setGuardian(e.target.checked)} className="mt-1 h-4 w-4" data-testid="profile-guardian" />
          A parent or guardian knows I'm joining clubs and agrees. (Needed if you're under {profile.guardian_below}.)
        </label>
      )}
      <ErrorLine message={s.error} />
      <div className="flex justify-end gap-2">
        <button type="button" className={btn} onClick={() => onOpenChange(false)}>Cancel</button>
        <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending || !handle.trim()} data-testid="profile-save">Save profile</button>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- create a club

export function CreateClubSheet({ open, onOpenChange, onCreated }: Base & { onCreated: (club: Club) => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState<NewClubInput>({ name: "", description: "", location: "", visibility: "private", audience: "adult", join_policy: "request", rules: "" });
  const junior = f.audience === "junior";
  const set = (patch: Partial<NewClubInput>) => setF((cur) => ({ ...cur, ...patch }));
  const s = useSubmit(() => createClub({ ...f, visibility: junior ? "private" : f.visibility, join_policy: junior ? "request" : f.join_policy }), (club) => { refreshClub(qc); onOpenChange(false); onCreated(club); });
  return (
    <Sheet open={open} onOpenChange={onOpenChange} testId="create-club-sheet" title="Start a club" description="Choose who it's for and how people join. You can change most of this later, but not who it is for.">
      <Field label="Club name"><input value={f.name} onChange={(e) => set({ name: e.target.value })} className={inputCls} data-testid="club-name" maxLength={40} /></Field>
      <Field label="Who is it for?">
        <select value={f.audience} onChange={(e) => set({ audience: e.target.value as NewClubInput["audience"] })} className={inputCls} data-testid="club-audience">
          <option value="adult">Adults (19 and over)</option>
          <option value="junior">Juniors (under 19) — private, coach-approved</option>
        </select>
      </Field>
      {junior ? (
        <p data-testid="junior-explainer" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
          A junior club is always private and unlisted. Young members join only by invitation and <strong>a coach approves each one</strong> (as the owner, you count as a coach); staff are adults;
          posts, sessions and challenges not written by a coach or the owner wait for a coach's approval.
        </p>
      ) : (
        <>
          <Field label="Visibility">
            <select value={f.visibility} onChange={(e) => set({ visibility: e.target.value as NewClubInput["visibility"], join_policy: e.target.value === "private" && f.join_policy === "open" ? "request" : f.join_policy })} className={inputCls} data-testid="club-visibility">
              <option value="private">Private — only members see inside; joined by invitation</option>
              <option value="public">Public — listed in Discover (members-only inside)</option>
            </select>
          </Field>
          <Field label="How people join">
            <select value={f.join_policy} onChange={(e) => set({ join_policy: e.target.value as NewClubInput["join_policy"] })} className={inputCls} data-testid="club-join-policy">
              <option value="request">By request — staff approve each person</option>
              <option value="invite">By invite link — a valid link joins directly</option>
              {f.visibility === "public" && <option value="open">Open — anyone signed in can join</option>}
            </select>
          </Field>
          <Field label="Location (optional)"><input value={f.location ?? ""} onChange={(e) => set({ location: e.target.value })} className={inputCls} maxLength={80} /></Field>
        </>
      )}
      <Field label="Description (optional)"><textarea value={f.description ?? ""} onChange={(e) => set({ description: e.target.value })} className={`${inputCls} py-2`} rows={2} maxLength={500} /></Field>
      <Field label="Club rules (members agree to them when they join)"><textarea value={f.rules ?? ""} onChange={(e) => set({ rules: e.target.value })} className={`${inputCls} py-2`} rows={3} maxLength={2000} data-testid="club-rules" /></Field>
      <ErrorLine message={s.error} />
      <div className="flex justify-end gap-2">
        <button type="button" className={btn} onClick={() => onOpenChange(false)}>Cancel</button>
        <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending || f.name.trim().length < 3} data-testid="club-create">Create club</button>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- a decision with a written reason

type ReasonProps = Base & { title: string; description: string; label: string; required?: boolean; submitLabel: string; testId: string; danger?: boolean; onSubmit: (reason: string) => Promise<unknown>; onDone?: () => void };

export function ReasonSheet({ open, onOpenChange, title, description, label, required = true, submitLabel, testId, danger, onSubmit, onDone }: ReasonProps) {
  const [reason, setReason] = useState("");
  const s = useSubmit(() => onSubmit(reason), () => { setReason(""); onOpenChange(false); onDone?.(); });
  return (
    <Sheet open={open} onOpenChange={onOpenChange} testId={testId} title={title} description={description}>
      <Field label={label}><textarea value={reason} onChange={(e) => setReason(e.target.value)} className={`${inputCls} py-2`} rows={3} maxLength={500} data-testid={`${testId}-reason`} /></Field>
      <ErrorLine message={s.error} />
      <div className="flex justify-end gap-2">
        <button type="button" className={btn} onClick={() => onOpenChange(false)}>Cancel</button>
        <button type="button" className={danger ? "min-h-11 rounded-md bg-band-red px-4 text-sm font-semibold text-white disabled:opacity-50" : btnPrimary} onClick={s.run} disabled={s.pending || (required && !reason.trim())} data-testid={`${testId}-submit`}>{submitLabel}</button>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- report

export function ReportSheet({ open, onOpenChange, clubId, targetType, targetId, subject }: Base & { clubId: string; targetType: "club" | "announcement" | "member" | "challenge"; targetId: string; subject: string }) {
  const [reason, setReason] = useState<string>(REPORT_REASONS_CLUB[0].value);
  const [detail, setDetail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const s = useSubmit(() => reportClub(clubId, targetType, targetId, reason, detail), (r) => setDone(r.message));
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setDone(null); onOpenChange(o); }} testId="report-sheet" title={`Report ${subject}`} description="A platform moderator reviews every report. The club's staff are not told who reported. If someone is in danger, contact the emergency services first.">
      {done ? (
        <p role="status" data-testid="report-done" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">{done}</p>
      ) : (
        <>
          <Field label="What's wrong?">
            <select value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls} data-testid="report-reason">
              {REPORT_REASONS_CLUB.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </Field>
          <Field label="Anything a moderator should know? (optional)"><textarea value={detail} onChange={(e) => setDetail(e.target.value)} className={`${inputCls} py-2`} rows={3} maxLength={500} /></Field>
          <ErrorLine message={s.error} />
          <div className="flex justify-end gap-2">
            <button type="button" className={btn} onClick={() => onOpenChange(false)}>Cancel</button>
            <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending} data-testid="report-submit">Send report</button>
          </div>
        </>
      )}
      {done && <div className="flex justify-end"><button type="button" className={btn} onClick={() => { setDone(null); onOpenChange(false); }}>Close</button></div>}
    </Sheet>
  );
}

// ---------------------------------------------------------------- invite

export function InviteSheet({ open, onOpenChange, club }: Base & { club: Club }) {
  const qc = useQueryClient();
  const caps = club.capabilities ?? {};
  const [role, setRole] = useState<"athlete" | "coach">("athlete");
  const [days, setDays] = useState(7);
  const [uses, setUses] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const s = useSubmit(() => createClubInvite(club.club_id, role, days, uses ? Number(uses) : undefined), (inv) => {
    refreshClub(qc, club.club_id);
    setLink(`${publicOrigin()}/clubs/join#${inv.token}`);
  });
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setLink(null); onOpenChange(o); }} testId="invite-sheet" title="Invite someone" description={club.audience === "junior" ? "A link only gets someone to the join form. A coach or the owner still approves every young member." : "Anyone with the link can ask to join (or join, if this club admits by link) until it expires. You can revoke it any time."}>
      {link ? (
        <>
          <p role="status" className="text-sm text-text-secondary">Copy this link now: it's shown once and only a fingerprint of it is stored.</p>
          <input readOnly value={link} className={`${inputCls} font-mono-nums`} data-testid="invite-link" onFocus={(e) => e.currentTarget.select()} />
          <div className="flex justify-end"><button type="button" className={btn} onClick={() => { setLink(null); onOpenChange(false); }}>Done</button></div>
        </>
      ) : (
        <>
          <Field label="Who is it for?">
            <select value={role} onChange={(e) => setRole(e.target.value as "athlete" | "coach")} className={inputCls} data-testid="invite-role">
              <option value="athlete">{club.audience === "junior" ? "A young athlete" : "An athlete"}</option>
              {caps.create_coach_invite && <option value="coach">{club.audience === "junior" ? "An adult coach" : "A coach"}</option>}
            </select>
          </Field>
          <Field label="Expires after (days)"><input type="number" min={1} max={30} value={days} onChange={(e) => setDays(Number(e.target.value))} className={inputCls} data-testid="invite-days" /></Field>
          <Field label="Most people who can use it (optional)"><input type="number" min={1} max={100} value={uses} onChange={(e) => setUses(e.target.value)} className={inputCls} data-testid="invite-uses" /></Field>
          <ErrorLine message={s.error} />
          <div className="flex justify-end gap-2">
            <button type="button" className={btn} onClick={() => onOpenChange(false)}>Cancel</button>
            <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending} data-testid="invite-create">Create link</button>
          </div>
        </>
      )}
    </Sheet>
  );
}

// ---------------------------------------------------------------- posts, sessions, challenges

export function PostSheet({ open, onOpenChange, club }: Base & { club: Club }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const s = useSubmit(() => postClubAnnouncement(club.club_id, title, body), (r) => {
    refreshClub(qc, club.club_id);
    if (r.status === "pending") { setNote(r.message); return; }
    setTitle(""); setBody(""); onOpenChange(false);
  });
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setNote(null); onOpenChange(o); }} testId="post-sheet" title="New announcement" description={club.capabilities?.publish_directly ? "Members see it straight away." : "A coach approves it before members see it."}>
      {note ? (
        <>
          <p role="status" data-testid="post-pending" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">{note}</p>
          <div className="flex justify-end"><button type="button" className={btn} onClick={() => { setNote(null); setTitle(""); setBody(""); onOpenChange(false); }}>Done</button></div>
        </>
      ) : (
        <>
          <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} maxLength={80} data-testid="post-title" /></Field>
          <Field label="Message" hint={club.audience === "junior" ? "No web links in a junior club." : undefined}><textarea value={body} onChange={(e) => setBody(e.target.value)} className={`${inputCls} py-2`} rows={4} maxLength={2000} data-testid="post-body" /></Field>
          <ErrorLine message={s.error} />
          <div className="flex justify-end gap-2">
            <button type="button" className={btn} onClick={() => onOpenChange(false)}>Cancel</button>
            <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending || !title.trim() || !body.trim()} data-testid="post-submit">{club.capabilities?.publish_directly ? "Post" : "Send for approval"}</button>
          </div>
        </>
      )}
    </Sheet>
  );
}

export function SessionSheet({ open, onOpenChange, club }: Base & { club: Club }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ title: "", session_type: "erg", date: todayISO(), start_time: "", duration_min: "", description: "" });
  const [note, setNote] = useState<string | null>(null);
  const s = useSubmit(() => createClubSession(club.club_id, { title: f.title, session_type: f.session_type, date: f.date, start_time: f.start_time || undefined, duration_min: f.duration_min ? Number(f.duration_min) : undefined, description: f.description || undefined }), (r) => {
    refreshClub(qc, club.club_id);
    if (r.status === "pending") { setNote(r.message); return; }
    onOpenChange(false);
  });
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setNote(null); onOpenChange(o); }} testId="session-sheet" title="Plan a team session" description="A plan for the club. It isn't a workout and doesn't add anything to anyone's own plan.">
      {note ? (
        <p role="status" data-testid="session-pending" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">{note}</p>
      ) : (
        <>
          <Field label="Title"><input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputCls} maxLength={80} data-testid="session-title" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type"><select value={f.session_type} onChange={(e) => setF({ ...f, session_type: e.target.value })} className={inputCls}>{SESSION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select></Field>
            <Field label="Date"><input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} className={inputCls} data-testid="session-date" /></Field>
            <Field label="Start (optional)"><input type="time" value={f.start_time} onChange={(e) => setF({ ...f, start_time: e.target.value })} className={inputCls} /></Field>
            <Field label="Minutes (optional)"><input type="number" min={1} max={600} value={f.duration_min} onChange={(e) => setF({ ...f, duration_min: e.target.value })} className={inputCls} /></Field>
          </div>
          <Field label="Notes (optional)"><textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className={`${inputCls} py-2`} rows={2} maxLength={500} /></Field>
          <ErrorLine message={s.error} />
        </>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className={btn} onClick={() => onOpenChange(false)}>{note ? "Done" : "Cancel"}</button>
        {!note && <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending || !f.title.trim()} data-testid="session-submit">{club.capabilities?.publish_directly ? "Add to calendar" : "Send for approval"}</button>}
      </div>
    </Sheet>
  );
}

const METRICS: NewChallengeInput["metric"][] = ["distance", "time", "sessions", "tests", "consistency"];

export function ChallengeSheet({ open, onOpenChange, club }: Base & { club: Club }) {
  const qc = useQueryClient();
  const today = todayISO();
  const [f, setF] = useState({ title: "", metric: "distance" as NewChallengeInput["metric"], goal: "", start: today, end: toISODate(new Date(Date.now() + 27 * 86400000)), target: "3", sport: "rowing" as "rowing" | "any" });
  const [note, setNote] = useState<string | null>(null);
  const unit = f.metric === "distance" ? "km" : f.metric === "time" ? "hours" : f.metric === "sessions" ? "sessions" : f.metric === "tests" ? "tests" : "weeks";
  const s = useSubmit(() => {
    const raw = f.goal ? Number(f.goal) : null;
    const goal = raw === null ? null : f.metric === "distance" ? Math.round(raw * 1000) : f.metric === "time" ? Math.round(raw * 3600) : raw; // unit conversion only: the server validates every limit
    return createClubChallenge(club.club_id, { title: f.title, metric: f.metric, start: f.start, end: f.end, goal, sport: f.sport, target_per_week: f.metric === "consistency" ? Number(f.target) : null });
  }, (r) => {
    refreshClub(qc, club.club_id);
    if (r.status === "pending") { setNote(r.message); return; }
    onOpenChange(false);
  });
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setNote(null); onOpenChange(o); }} testId="challenge-sheet" title="New challenge" description="Challenges are capped on purpose: extra volume never earns more, and nothing about weight, calories, recovery or sleep is ever used.">
      {note ? (
        <p role="status" data-testid="challenge-pending" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">{note}</p>
      ) : (
        <>
          <Field label="Title"><input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputCls} maxLength={80} data-testid="challenge-title" /></Field>
          <Field label="What counts">
            <select value={f.metric} onChange={(e) => setF({ ...f, metric: e.target.value as NewChallengeInput["metric"] })} className={inputCls} data-testid="challenge-metric">
              {METRICS.map((m) => <option key={m} value={m}>{metricLabel(m)}</option>)}
            </select>
          </Field>
          {f.metric === "consistency" ? (
            <Field label="Sessions that make a week count (1–5)" hint="More than this earns nothing. Members can excuse any week."><input type="number" min={1} max={5} value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} className={inputCls} data-testid="challenge-target" /></Field>
          ) : f.metric !== "tests" ? (
            <Field label={`Goal (${unit})`} hint="The score counts up to this and no further."><input type="number" min={1} value={f.goal} onChange={(e) => setF({ ...f, goal: e.target.value })} className={inputCls} data-testid="challenge-goal" /></Field>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Starts"><input type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} className={inputCls} data-testid="challenge-start" /></Field>
            <Field label="Ends"><input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} className={inputCls} data-testid="challenge-end" /></Field>
          </div>
          <Field label="Which sport counts?"><select value={f.sport} onChange={(e) => setF({ ...f, sport: e.target.value as "rowing" | "any" })} className={inputCls}><option value="rowing">Rowing only</option><option value="any">Any recorded sport</option></select></Field>
          <ErrorLine message={s.error} />
        </>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className={btn} onClick={() => onOpenChange(false)}>{note ? "Done" : "Cancel"}</button>
        {!note && <button type="button" className={btnPrimary} onClick={s.run} disabled={s.pending || !f.title.trim()} data-testid="challenge-submit">{club.capabilities?.publish_directly ? "Start challenge" : "Send for approval"}</button>}
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- I took part / share a result

export function LinkWorkoutSheet({ open, onOpenChange, clubId, session, defaultShare }: Base & { clubId: string; session: ClubSessionItem; defaultShare: boolean }) {
  const qc = useQueryClient();
  const [share, setShare] = useState(defaultShare);
  const workouts = useQuery({ queryKey: ["club-workouts", clubId, session.id], queryFn: () => fetchWorkouts({}), enabled: open, retry: false });
  const day = new Date(`${session.date}T12:00:00`).getTime();
  const near = (workouts.data?.items ?? []).filter((w) => w.start && Math.abs(new Date(w.start).getTime() - day) < 36 * 3600000).slice(0, 8);
  const [error, setError] = useState<string | null>(null);
  const link = useMutation({ mutationFn: (id: number) => linkClubWorkout(clubId, session.id, id, share), onSuccess: () => { refreshClub(qc, clubId); onOpenChange(false); }, onError: (e: Error) => setError(e.message) });
  return (
    <Sheet open={open} onOpenChange={onOpenChange} testId="link-sheet" title={`I took part: ${session.title}`} description="Pick the workout you did. The club learns only that you took part — and your distance and time if you tick the box. The workout itself stays yours.">
      <label className="flex items-start gap-2 text-sm text-text-secondary">
        <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} className="mt-1 h-4 w-4" data-testid="link-share" />
        Also share my distance and time with the club (used only in totals when at least three members share).
      </label>
      {workouts.isLoading && <p className="text-sm text-text-tertiary">Looking for your workouts…</p>}
      {workouts.data && near.length === 0 && <p className="text-sm text-text-secondary" data-testid="link-none">No workout of yours is on that day yet. Sync, then try again.</p>}
      <ul className="flex flex-col gap-2">
        {near.map((w) => (
          <li key={w.id}>
            <button type="button" onClick={() => link.mutate(w.id)} className={`${btn} flex w-full items-center justify-between text-left`} data-testid="link-workout">
              <span>{w.title ?? "Workout"}</span>
              <span className="font-mono-nums text-xs text-text-tertiary">{w.start ? new Date(w.start).toLocaleDateString() : ""}</span>
            </button>
          </li>
        ))}
      </ul>
      <ErrorLine message={error} />
    </Sheet>
  );
}

export function ShareResultSheet({ open, onOpenChange, clubId }: Base & { clubId: string }) {
  const qc = useQueryClient();
  const results = useQuery({ queryKey: ["club-my-results"], queryFn: fetchLbResults, enabled: open, retry: false });
  const [error, setError] = useState<string | null>(null);
  const share = useMutation({ mutationFn: (ref: Parameters<typeof shareClubResult>[1]) => shareClubResult(clubId, ref), onSuccess: () => { refreshClub(qc, clubId); onOpenChange(false); }, onError: (e: Error) => setError(e.message) });
  return (
    <Sheet open={open} onOpenChange={onOpenChange} testId="share-result-sheet" title="Share a result with this club" description="Only exact 500 m–6 km and 30/60-minute results can be shared. Club members see your handle and the result; nothing else about you.">
      {results.isLoading && <p className="text-sm text-text-tertiary">Loading your results…</p>}
      {results.data && results.data.results.length === 0 && <p className="text-sm text-text-secondary">You have no eligible results yet.</p>}
      <ul className="flex flex-col gap-2">
        {(results.data?.results ?? []).slice(0, 15).map((r, i) => (
          <li key={`${r.board_key}-${i}`}>
            <button type="button" onClick={() => share.mutate(r.ref)} className={`${btn} flex w-full items-center justify-between text-left`} data-testid="share-result">
              <span>{r.board_label} · <span className="font-mono-nums">{r.result}</span></span>
              <span className="text-xs text-text-tertiary">{r.verification_label}</span>
            </button>
          </li>
        ))}
      </ul>
      <ErrorLine message={error} />
    </Sheet>
  );
}
