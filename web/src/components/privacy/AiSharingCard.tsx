import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";
import { useState } from "react";
import { fetchSharing, updateSharing, withdrawSharing, YOUTH_BANDS } from "../../lib/privacy";
import { Card } from "../ui/Card";
import { controlSkin } from "../ui/Field";
import { buttonClass } from "../ui/Button";

const btn = buttonClass("secondary", "md");
const BANDS = [["", "I'd rather not say"], ["adult", "19 or over"], ["u19", "Under 19"], ["u18", "Under 18"], ["u17", "Under 17"], ["u16", "Under 16"], ["u15", "Under 15"], ["u14", "Under 14"]];

/** What the AI coach and your AI provider may see. Nothing is sent until you have read this and agreed, and every category starts off. */
export function AiSharingCard() {
  const qc = useQueryClient();
  const state = useQuery({ queryKey: ["ai-sharing"], queryFn: fetchSharing });
  const [agree, setAgree] = useState(false);
  // The band the person picked, kept even if the server refused it (health data already on) so the guardian box can appear.
  const [pickedBand, setPickedBand] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const done = (data: unknown) => {
    setError(null);
    qc.setQueryData(["ai-sharing"], data);
    qc.invalidateQueries({ queryKey: ["ai-providers"] });
  };
  const save = useMutation({ mutationFn: updateSharing, onSuccess: done, onError: (e: Error) => setError(e.message) });
  const withdraw = useMutation({ mutationFn: withdrawSharing, onSuccess: (d) => { done(d); setAgree(false); } });

  // An error used to leave "Loading…" up for good (`!state.data` stays true); it now says so and offers Retry.
  if (state.isError)
    return (
      <Card title="AI sharing">
        <ErrorState message="Couldn't load your sharing choices." onRetry={() => state.refetch()} />
      </Card>
    );
  if (state.isLoading || !state.data)
    return (
      <Card title="AI sharing">
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-10 w-full" />
        </div>
      </Card>
    );
  const s = state.data;
  const band = pickedBand === undefined ? s.age_band : pickedBand;
  const young = band !== null && YOUTH_BANDS.includes(band);

  return (
    <Card title="AI sharing">
      <div className="flex flex-col gap-4" data-testid="ai-sharing">
        <p className="text-sm text-text-secondary">
          Catch only talks to an AI provider when you chat with the coach, ask it to read a photo, or connect an app like Claude Desktop — always with your
          own key. Choose exactly what it may see. A category that is off is never sent: the coach is told it is switched off instead of being given the data.
          Whatever you do allow is sent to the provider you chose, under their own terms.
        </p>

        {!s.consented && (
          <label className="flex min-h-11 items-start gap-3 rounded-md border border-border p-3 text-sm text-text-primary">
            <input type="checkbox" className="mt-1 size-4" checked={agree} onChange={(e) => setAgree(e.target.checked)} data-testid="ai-sharing-agree" />
            <span>I've read what is sent, and I understand it goes to my AI provider and is not under Catch's control once it does.</span>
          </label>
        )}

        <div className="flex flex-col gap-1">
          <label htmlFor="age-band" className="text-sm font-medium text-text-primary">Age (optional)</label>
          <select
            id="age-band"
            className={controlSkin + " w-auto min-h-11"}
            value={band ?? ""}
            onChange={(e) => {
              setPickedBand(e.target.value || null);
              save.mutate({ age_band: e.target.value || null, acknowledge: s.consented ? undefined : agree });
            }}
            disabled={!s.consented && !agree}
          >
            {BANDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {young && (
            <label className="mt-1 flex min-h-11 items-start gap-3 text-sm text-text-primary">
              <input type="checkbox" className="mt-1 size-4" checked={s.guardian_ack} onChange={(e) => save.mutate({ guardian_ack: e.target.checked, age_band: band })} data-testid="guardian-ack" />
              <span>A parent or guardian knows I'm using an AI with my training data.</span>
            </label>
          )}
        </div>

        <ul className="flex flex-col gap-2">
          {s.categories.map((c) => (
            <li key={c.key} className="flex items-start justify-between gap-3 rounded-md border border-border p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-text-primary">{c.label}</p>
                <p className="mt-0.5 text-xs text-text-secondary">{c.description}</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={c.enabled}
                aria-label={`Share ${c.label}`}
                data-testid={`share-${c.key}`}
                disabled={save.isPending || (!s.consented && !agree)}
                onClick={() => save.mutate({ acknowledge: s.consented ? undefined : agree, categories: { [c.key]: !c.enabled } })}
                className={`min-h-11 min-w-16 shrink-0 rounded-full border px-3 text-xs font-medium disabled:opacity-40 ${c.enabled ? "border-accent bg-accent/15 text-text-primary" : "border-border text-text-secondary"}`}
              >
                {c.enabled ? "On" : "Off"}
              </button>
            </li>
          ))}
        </ul>

        {error && <p role="alert" className="text-sm text-band-red-text" data-testid="ai-sharing-error">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          {!s.consented && (
            <button type="button" className={btn} disabled={!agree || save.isPending} onClick={() => save.mutate({ acknowledge: true, categories: {} })} data-testid="ai-sharing-confirm">
              Save my choice (everything stays off)
            </button>
          )}
          {s.consented && (
            <button type="button" className={btn} onClick={() => withdraw.mutate()} disabled={withdraw.isPending} data-testid="ai-sharing-withdraw">
              Withdraw — stop sharing everything
            </button>
          )}
          <a href="/legal/ai-data-sharing" className="text-sm font-medium text-accent hover:underline">Exactly what is sent</a>
        </div>
      </div>
    </Card>
  );
}
