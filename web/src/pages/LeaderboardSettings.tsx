import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  createLbClub, fetchLbMe, fetchLbProfilePreview, fetchLbResults, joinLbClub, lbOptIn, lbOptOut, leaveLbClub, saveLbSettings, withdrawLbPublication,
} from "../lib/api";
import { EntryRow } from "../components/leaderboards/EntryRow";
import { PublishSheet } from "../components/leaderboards/PublishSheet";
import { ReasonSheet } from "../components/leaderboards/ReasonSheet";
import { VerificationBadge } from "../components/leaderboards/VerificationBadge";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ACTOR_LABEL, PRECISION_LABEL, STATUS_LABEL, VERIFICATION_MEANING } from "../lib/leaderboards";
import type { LbDatePrecision, LbResult, LbState, Verification } from "../lib/types";

const inputCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary placeholder:text-text-tertiary";
const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-secondary";
const primary = "min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50";

function Err({ text }: { text: string | null }) {
  return text ? (
    <p role="alert" data-testid="lb-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
      {text}
    </p>
  ) : null;
}

export function LeaderboardSettingsPage() {
  const me = useQuery({ queryKey: ["lb-me"], queryFn: fetchLbMe, retry: false });
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/settings" className="text-sm font-medium text-accent hover:underline">
          ← Settings
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">Leaderboards and verified results</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Nothing is public unless you publish it. You preview exactly what will be shown, you can take a result down at any time, and recovery, sleep, HRV, weight,
          body composition, nutrition and your training history are never part of it.
        </p>
      </div>
      <Card title="What “verified” means">
        <div className="flex flex-col gap-3" data-testid="verification-explainer">
          {(["verified", "provider_linked", "unverified"] as Verification[]).map((v) => (
            <div key={v} className="flex flex-col gap-1">
              <VerificationBadge state={v} />
              <p className="text-sm text-text-secondary">{VERIFICATION_MEANING[v]}</p>
            </div>
          ))}
          <p className="text-xs text-text-tertiary">“Verified” means the source can be authenticated — not that Catch guarantees who rowed it or their physical condition.</p>
        </div>
      </Card>
      {me.isLoading && <CardSkeleton lines={4} />}
      {(me.isError || (me.data && !me.data.available)) && (
        <Card>
          <p data-testid="lb-unavailable" className="text-sm text-text-secondary">Leaderboards are only available on the public Catch deployment.</p>
        </Card>
      )}
      {me.data?.available && (me.data.settings.opted_in ? <OptedIn state={me.data} /> : <Join state={me.data} />)}
    </div>
  );
}

function Join({ state }: { state: LbState }) {
  const queryClient = useQueryClient();
  const [handle, setHandle] = useState("");
  const [mode, setMode] = useState<"handle" | "anonymous">("handle");
  const [band, setBand] = useState("");
  const [age13, setAge13] = useState(false);
  const [guardian, setGuardian] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const youth = band.startsWith("U");
  const join = useMutation({
    mutationFn: () =>
      lbOptIn({ confirm, handle: mode === "handle" ? handle : undefined, display_mode: mode, self_declared_band: band || undefined, attest_min_age: !band && age13 ? true : band ? true : undefined, attest_guardian: youth && guardian ? true : undefined }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["lb-me"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  return (
    <Card title="Join the leaderboards">
      <form
        className="flex flex-col gap-3"
        data-testid="lb-join-form"
        onSubmit={(e) => {
          e.preventDefault();
          join.mutate();
        }}
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm text-text-secondary">How you appear</legend>
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="radio" name="mode" checked={mode === "handle"} onChange={() => setMode("handle")} className="h-5 w-5" data-testid="lb-mode-handle" /> A public handle I choose
          </label>
          {mode === "handle" && <input value={handle} onChange={(e) => setHandle(e.target.value)} maxLength={24} placeholder="Handle (3–24 characters)" className={inputCls} data-testid="lb-handle" aria-label="Public handle" />}
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="radio" name="mode" checked={mode === "anonymous"} onChange={() => setMode("anonymous")} className="h-5 w-5" data-testid="lb-mode-anonymous" /> Anonymous rower (no name)
          </label>
          <p className="text-xs text-text-tertiary">Catch never publishes your account name or email. Only the handle you type here, or “Anonymous rower”.</p>
        </fieldset>
        <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
          Age category (optional)
          <select value={band} onChange={(e) => setBand(e.target.value)} className={inputCls} data-testid="lb-band">
            <option value="">I'll skip this — Overall boards only</option>
            {state.age_bands.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
          <span className="text-xs text-text-tertiary">
            If your Concept2 profile has a date of birth, Catch uses it instead (and keeps only the category, never the date). Otherwise this is self-declared and labelled that
            way. “U16” means under 16.
          </span>
        </label>
        {!band && (
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={age13} onChange={(e) => setAge13(e.target.checked)} className="h-5 w-5" data-testid="lb-age13" /> I am {state.min_age} or older
          </label>
        )}
        {youth && (
          <label className="flex min-h-11 items-start gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={guardian} onChange={(e) => setGuardian(e.target.checked)} className="mt-2 h-5 w-5" data-testid="lb-guardian" />
            <span>
              A parent or guardian agrees to this. (Required under {state.guardian_below}. Athletes under 18 appear only under a handle or as anonymous, and only the year of a
              result is ever shown.)
            </span>
          </label>
        )}
        <label className="flex min-h-11 items-start gap-2 text-sm text-text-primary">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-2 h-5 w-5" data-testid="lb-confirm" />
          <span>I want to be able to publish results to the public leaderboards. I can leave and take everything down at any time.</span>
        </label>
        <Err text={error} />
        <div className="flex justify-end">
          <button type="submit" disabled={!confirm || join.isPending} data-testid="lb-optin" className={primary}>
            {join.isPending ? "Saving…" : "Opt in"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function OptedIn({ state }: { state: LbState }) {
  const queryClient = useQueryClient();
  const results = useQuery({ queryKey: ["lb-results"], queryFn: fetchLbResults });
  const [publishing, setPublishing] = useState<LbResult | null>(null);
  const [appealing, setAppealing] = useState<string | null>(null);
  const [takeDown, setTakeDown] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [handle, setHandle] = useState(state.athlete?.handle ?? "");
  const [mode, setMode] = useState(state.athlete?.display_mode ?? "handle");
  const [precision, setPrecision] = useState<LbDatePrecision>(state.settings.date_precision);
  const [showAge, setShowAge] = useState(state.settings.show_age_band);
  const [showWeight, setShowWeight] = useState(state.settings.show_weight_class);
  const [band, setBand] = useState(state.settings.self_declared_band ?? "");
  const [clubName, setClubName] = useState("");
  const [clubCode, setClubCode] = useState("");
  const [newCode, setNewCode] = useState<string | null>(null);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["lb-me"] });
    queryClient.invalidateQueries({ queryKey: ["lb-results"] });
    queryClient.invalidateQueries({ queryKey: ["lb-board"] });
    queryClient.invalidateQueries({ queryKey: ["lb-profile-preview"] });
  };
  const onError = (e: Error) => setError(e.message);
  const save = useMutation({
    mutationFn: () => saveLbSettings({ handle: mode === "handle" ? handle : null, display_mode: mode, date_precision: precision, show_age_band: showAge, show_weight_class: showWeight, ...(band !== (state.settings.self_declared_band ?? "") ? { self_declared_band: band || null } : {}) }),
    onSuccess: () => { setError(null); refresh(); },
    onError,
  });
  const withdraw = useMutation({ mutationFn: (id: string) => withdrawLbPublication(id), onSuccess: () => { setTakeDown(null); setError(null); refresh(); }, onError });
  const leave = useMutation({ mutationFn: () => lbOptOut(true), onSuccess: () => { setLeaving(false); refresh(); }, onError });
  const create = useMutation({ mutationFn: () => createLbClub(clubName), onSuccess: (c) => { setNewCode(c.join_code); setClubName(""); setError(null); refresh(); }, onError });
  const join = useMutation({ mutationFn: () => joinLbClub(clubCode), onSuccess: () => { setClubCode(""); setError(null); refresh(); }, onError });
  const leaveClub = useMutation({ mutationFn: (id: string) => leaveLbClub(id), onSuccess: refresh, onError });
  const profile = useQuery({ queryKey: ["lb-profile-preview"], queryFn: fetchLbProfilePreview, enabled: showProfile, retry: false });
  const fromConcept2 = state.settings.age_source === "concept2_profile";
  const bandById = (id: string) => state.publications.find((p) => p.entry_id === id);

  return (
    <>
      <Err text={error} />
      <Card title="Your results">
        <p className="mb-2 text-sm text-text-secondary">Exact 500 m to 6,000 m pieces and 30 or 60 minute pieces from the test center qualify. Publishing always shows a preview first.</p>
        {results.isLoading && <CardSkeleton lines={3} />}
        {results.data?.results.length === 0 && <p className="text-sm text-text-secondary">No results qualify yet.</p>}
        <ul className="flex flex-col gap-2" data-testid="lb-results">
          {results.data?.results.map((r) => {
            const key = `${r.ref.kind}-${r.ref.id}`;
            return (
              <li key={key} data-testid={`lb-result-${key}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-surface px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-text-primary">
                    {r.board_label} · <span className="font-mono-nums">{r.result}</span>
                  </p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2">
                    <VerificationBadge state={r.verification} />
                    {r.published && <span className="text-xs text-text-secondary" data-testid={`lb-status-${key}`}>{STATUS_LABEL[r.published]}</span>}
                  </div>
                </div>
                {!r.published || r.published === "withdrawn" ? (
                  <button type="button" onClick={() => setPublishing(r)} data-testid={`lb-publish-${key}`} className={btn}>
                    Publish…
                  </button>
                ) : takeDown === r.entry_id ? (
                  <div role="group" aria-label="Confirm take down" className="flex gap-2 rounded-md border border-border p-1">
                    <button type="button" onClick={() => withdraw.mutate(r.entry_id!)} data-testid={`lb-takedown-confirm-${key}`} className={primary}>
                      Take down
                    </button>
                    <button type="button" onClick={() => setTakeDown(null)} className={btn}>
                      Keep
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    {r.can_republish ? (
                      <button type="button" onClick={() => setPublishing(r)} data-testid={`lb-republish-${key}`} className={btn}>
                        Review and publish again…
                      </button>
                    ) : (
                      (r.published === "hidden" || r.published === "removed") && (
                        <button type="button" onClick={() => setAppealing(r.entry_id)} data-testid={`lb-appeal-${key}`} className={btn}>
                          Appeal
                        </button>
                      )
                    )}
                    {(r.published === "active" || r.can_republish) && (
                      <button type="button" onClick={() => setTakeDown(r.entry_id)} data-testid={`lb-takedown-${key}`} className={btn}>
                        Take down…
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>

      <Card title="Privacy settings">
        <form className="flex flex-col gap-3" data-testid="lb-privacy-form" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm text-text-secondary">How you appear</legend>
            <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
              <input type="radio" name="pmode" checked={mode === "handle"} onChange={() => setMode("handle")} className="h-5 w-5" /> My handle
            </label>
            {mode === "handle" && <input value={handle} onChange={(e) => setHandle(e.target.value)} maxLength={24} className={inputCls} aria-label="Public handle" data-testid="lb-privacy-handle" />}
            <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
              <input type="radio" name="pmode" checked={mode === "anonymous"} onChange={() => setMode("anonymous")} className="h-5 w-5" data-testid="lb-privacy-anonymous" /> Anonymous rower
            </label>
          </fieldset>
          <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
            Default date detail
            <select value={precision} onChange={(e) => setPrecision(e.target.value as LbDatePrecision)} className={inputCls} data-testid="lb-privacy-precision">
              {state.date_precisions.map((p) => (
                <option key={p} value={p}>
                  {PRECISION_LABEL[p]}
                </option>
              ))}
            </select>
            <span className="text-xs text-text-tertiary">Applies to results you publish from now on. Existing ones keep what you saw in their preview.</span>
          </label>
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={showAge} onChange={(e) => setShowAge(e.target.checked)} className="h-5 w-5" /> Show my age category by default
          </label>
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={showWeight} onChange={(e) => setShowWeight(e.target.checked)} className="h-5 w-5" /> Show the weight class Concept2 recorded by default
          </label>
          <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
            Age category
            <select value={band} onChange={(e) => setBand(e.target.value)} disabled={fromConcept2} className={`${inputCls} disabled:opacity-60`}>
              <option value="">Not set</option>
              {state.age_bands.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <span className="text-xs text-text-tertiary" data-testid="lb-age-source">
              {fromConcept2 ? "Taken from your Concept2 profile (as reported to Concept2). It can't be changed here." : state.settings.self_declared_band ? "Self-declared. Shown as such." : "Not set — you appear on Overall boards only."}
            </span>
          </label>
          <div className="flex justify-end">
            <button type="submit" disabled={save.isPending} data-testid="lb-privacy-save" className={primary}>
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </Card>

      <Card
        title="Your public profile"
        action={
          <button type="button" onClick={() => setShowProfile((s) => !s)} data-testid="lb-profile-toggle" className="min-h-11 text-sm font-medium text-accent hover:underline">
            {showProfile ? "Hide preview" : "Preview as others see it"}
          </button>
        }
      >
        {!showProfile && <p className="text-sm text-text-secondary">See exactly what another signed-in user sees when they open your profile.</p>}
        {showProfile && profile.isLoading && <CardSkeleton lines={2} />}
        {showProfile && profile.data && (
          <div data-testid="lb-profile-preview">
            <p className="mb-2 text-sm font-medium text-text-primary">{profile.data.name}</p>
            {profile.data.results.length === 0 ? (
              <p className="text-sm text-text-secondary">No public results yet.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {profile.data.results.map((e) => (
                  <EntryRow key={e.entry_id} entry={e} />
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card title="Decisions and appeals">
        {state.moderation.events.length === 0 && <p className="text-sm text-text-secondary" data-testid="lb-no-events">Nothing has ever been hidden or removed. Every change to a published result is recorded here, with its reason.</p>}
        <ul className="flex flex-col gap-2" data-testid="lb-events">
          {state.moderation.events.map((ev) => (
            <li key={ev.id} className="rounded-md border border-border px-3 py-2 text-sm">
              <p className="text-text-primary">
                {ACTOR_LABEL[ev.actor_kind]}: {STATUS_LABEL[ev.to_status] ?? ev.to_status}
              </p>
              <p className="text-text-secondary">{ev.reason_text}</p>
              <p className="text-xs text-text-tertiary">{new Date(ev.created_at).toLocaleString()}</p>
            </li>
          ))}
        </ul>
        {state.moderation.appeals.map((a) => (
          <p key={a.id} className="mt-2 text-sm text-text-secondary" data-testid={`lb-appeal-row-${a.id}`}>
            Appeal {a.status === "open" ? "waiting for a moderator" : a.status}
            {a.resolution_text ? `: ${a.resolution_text}` : ""}
          </p>
        ))}
        {state.is_moderator && (
          <Link to="/settings/moderation" className="mt-3 inline-block text-sm font-medium text-accent hover:underline" data-testid="lb-mod-link">
            Open the moderation queue
          </Link>
        )}
      </Card>

      <Card title="Clubs">
        <ul className="flex flex-col gap-2">
          {state.clubs.map((c) => (
            <li key={c.club_id} className="flex items-center justify-between text-sm text-text-primary">
              {c.name}
              <button type="button" onClick={() => leaveClub.mutate(c.club_id)} className={btn}>
                Leave
              </button>
            </li>
          ))}
        </ul>
        {state.clubs.length === 0 && <p className="text-sm text-text-secondary">You're not in a club. A club is just a join code; being in one lets club boards include you.</p>}
        {newCode && (
          <p role="status" data-testid="lb-club-code" className="mt-2 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
            Share this code with your club: <span className="font-mono-nums font-semibold text-text-primary">{newCode}</span>. It's shown once.
          </p>
        )}
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input value={clubName} onChange={(e) => setClubName(e.target.value)} placeholder="New club name" className={inputCls} aria-label="New club name" data-testid="lb-club-name" />
          <button type="button" onClick={() => create.mutate()} disabled={!clubName.trim()} className={btn} data-testid="lb-club-create">
            Create
          </button>
        </div>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input value={clubCode} onChange={(e) => setClubCode(e.target.value)} placeholder="Join code" className={inputCls} aria-label="Club join code" data-testid="lb-club-code-input" />
          <button type="button" onClick={() => join.mutate()} disabled={!clubCode.trim()} className={btn} data-testid="lb-club-join">
            Join
          </button>
        </div>
      </Card>

      <Card title="Leave the leaderboards">
        {leaving ? (
          <div role="group" aria-label="Confirm leaving" className="flex flex-col gap-2">
            <p className="text-sm text-text-secondary">This takes every published result down now. It's recorded in your history with the reason “you opted out”. Your own results stay in Catch.</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => leave.mutate()} data-testid="lb-optout-confirm" className={primary}>
                Opt out and take everything down
              </button>
              <button type="button" onClick={() => setLeaving(false)} className={btn}>
                Stay
              </button>
            </div>
          </div>
        ) : (
          <button type="button" onClick={() => setLeaving(true)} data-testid="lb-optout" className={btn}>
            Opt out…
          </button>
        )}
      </Card>

      {publishing && <PublishSheet result={publishing} state={state} open onOpenChange={(o) => !o && setPublishing(null)} />}
      {appealing && <ReasonSheet mode="appeal" entryId={appealing} subject={`Your ${bandById(appealing)?.board_key ?? ""} result was ${STATUS_LABEL[bandById(appealing)?.status ?? "hidden"]?.toLowerCase()}`} open onOpenChange={(o) => !o && setAppealing(null)} />}
    </>
  );
}
