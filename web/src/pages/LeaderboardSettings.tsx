import { formatInstantDateTime } from "../lib/localTime";
import { PageHeader } from "../components/ui/PageHeader";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchLbMe, fetchLbProfilePreview, fetchLbResults, lbOptOut, saveLbSettings, withdrawLbPublication,
} from "../lib/api";
import { EntryRow } from "../components/leaderboards/EntryRow";
import { JoinLeaderboardsForm } from "../components/leaderboards/JoinLeaderboardsForm";
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
      <PageHeader
        back={{ to: "/settings", label: "Settings" }}
        eyebrow="Community"
        title="Leaderboards and verified results"
        subtitle="Nothing is public unless you publish it. You preview exactly what will be shown, you can take a result down at any time, and recovery, sleep, HRV, weight, body composition, nutrition and your training history are never part of it."
      />
      <Card tone="inset" title="What “verified” means">
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
      {me.data?.available && (me.data.settings.opted_in ? <OptedIn state={me.data} /> : <JoinLeaderboardsForm state={me.data} />)}
    </div>
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
              <p className="text-xs text-text-tertiary">{formatInstantDateTime(ev.created_at)}</p>
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

      <Card
        title="Clubs"
        action={
          <Link to="/clubs" data-testid="lb-clubs-link" className="text-sm font-medium text-accent hover:underline">
            Open clubs
          </Link>
        }
      >
        <p className="text-sm text-text-secondary">
          Clubs have their own page now: roles, invitations, a team calendar, challenges and a club results board. A public club's board can include your public results only if you tick
          “show my public results” in that club.
        </p>
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
