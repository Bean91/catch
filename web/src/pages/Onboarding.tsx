import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ConnectionCard } from "../components/connections/ConnectionCard";
import { TimeZoneSelect } from "../components/settings/TimeZoneCard";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { fetchConnections, fetchMe, fetchOnboarding, putOnboarding, putTimeZone, saveSettings, startOnboardingSync } from "../lib/api";
import { PROVIDES, statusLabel } from "../lib/connections";
import { deviceZone, setActiveZone, zoneLabel } from "../lib/localTime";
import type { ConnectionCard as Conn, ProviderId } from "../lib/types";

const STEP_TITLES = ["Welcome", "Connect your sources", "Training basics", "Importing", "All set"];
const PRIMARY = "min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50";
const SECONDARY = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent";
const INPUT = "min-h-11 w-full rounded-md border border-border bg-bg px-3 text-sm text-text-primary focus:border-accent focus:outline-none";
const RESULT_TEXT: Record<string, string> = {
  connected: "is connected.",
  denied: "wasn't connected — access wasn't granted. You can try again or skip it.",
  failed: "couldn't be connected. You can try again, skip it, or connect it later in Settings.",
};

/** First-run setup (session 32, docs/onboarding.md). Five short steps, each skippable; progress is saved on the server so it resumes
 * on any device. Nothing here waits for history to import, and no step ever shows a key or token. */
export function OnboardingPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const state = useQuery({ queryKey: ["onboarding"], queryFn: fetchOnboarding });
  const [step, setStep] = useState<number | null>(null);
  const [skipped, setSkipped] = useState<ProviderId[]>([]);
  const restarted = useRef(false);

  // "Run setup again" from Settings, or the return from a provider's sign-in page (which lands on the connections step).
  useEffect(() => {
    if (!state.data || step !== null) return;
    if (params.get("restart") === "1" && !restarted.current) {
      restarted.current = true;
      void putOnboarding({ restart: true }).then((s) => qc.setQueryData(["onboarding"], s));
      setStep(0);
      return;
    }
    setSkipped(state.data.skipped);
    setStep(params.get("provider") ? 1 : Math.min(state.data.step, 4));
  }, [state.data, step, params, qc]);

  const go = (next: number) => {
    setStep(next);
    if (params.get("restart")) setParams({}, { replace: true });
    void putOnboarding({ step: next, skipped }).then((s) => qc.setQueryData(["onboarding"], s));
    window.scrollTo?.({ top: 0 });
  };

  const finish = useMutation({
    mutationFn: () => putOnboarding({ complete: true, skipped }),
    onSuccess: (s) => {
      qc.setQueryData(["onboarding"], s);
      void qc.invalidateQueries({ queryKey: ["me"] });
      navigate("/", { replace: true });
    },
  });

  if (state.isLoading || step === null) return <CardSkeleton lines={4} />;

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4" data-testid="onboarding">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-text-tertiary" aria-live="polite">
          Step {step + 1} of {STEP_TITLES.length}
        </p>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">{STEP_TITLES[step]}</h1>
        <div className="mt-2 flex gap-1" aria-hidden>
          {STEP_TITLES.map((_, i) => (
            <span key={i} className={`h-1 flex-1 rounded-full ${i <= step ? "bg-accent" : "bg-surface-2"}`} />
          ))}
        </div>
      </div>

      {step === 0 && <WelcomeStep onNext={() => go(1)} />}
      {step === 1 && (
        <ConnectionsStep
          skipped={skipped}
          setSkipped={setSkipped}
          result={params.get("provider") ? { provider: params.get("provider")!, result: params.get("result") ?? "" } : null}
          onNext={() => go(2)}
          onBack={() => go(0)}
        />
      )}
      {step === 2 && <PreferencesStep onNext={() => go(3)} onBack={() => go(1)} />}
      {step === 3 && <SyncStep onNext={() => go(4)} onLeave={() => finish.mutate()} />}
      {step === 4 && <DoneStep skipped={skipped} onFinish={() => finish.mutate()} busy={finish.isPending} onBack={() => go(3)} />}

      {step < 4 && (
        <button type="button" onClick={() => finish.mutate()} className="self-center min-h-11 px-3 text-sm text-text-tertiary hover:text-text-secondary">
          Skip setup — I'll do this later in Settings
        </button>
      )}
    </div>
  );
}

function WelcomeStep({ onNext }: { onNext: () => void }) {
  const [zone, setZone] = useState(deviceZone() ?? "UTC");
  const save = useMutation({
    mutationFn: () => putTimeZone({ timezone: zone }),
    onSuccess: (out) => {
      setActiveZone(out.current_zone);
      onNext();
    },
  });
  return (
    <Card>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-text-secondary">
          Catch brings your erg results, workouts, sleep and recovery into one place, and turns them into a daily strain, a recovery score and an
          estimated 2k. Setup takes a couple of minutes; every step can be skipped.
        </p>
        <label className="flex flex-col gap-1.5" htmlFor="onb-tz">
          <span className="font-medium text-text-primary">Your time zone</span>
          <span className="text-xs text-text-tertiary">
            Suggested from this device. Days, "today" and reminders use it; when you travel, Catch follows your phone or watch on its own.
          </span>
          <TimeZoneSelect id="onb-tz" value={zone} onChange={setZone} />
        </label>
        {save.isError && <p role="alert" className="text-band-red-text">{(save.error as Error).message}</p>}
        <div className="flex justify-end">
          <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className={PRIMARY}>
            Continue
          </button>
        </div>
      </div>
    </Card>
  );
}

function ConnectionsStep({ skipped, setSkipped, result, onNext, onBack }: {
  skipped: ProviderId[];
  setSkipped: (s: ProviderId[]) => void;
  result: { provider: string; result: string } | null;
  onNext: () => void;
  onBack: () => void;
}) {
  const query = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  const offered = (query.data?.connections ?? []).filter((c) => c.available);
  const label = offered.find((c) => c.provider === result?.provider)?.label ?? result?.provider;
  const toggleSkip = (p: ProviderId) => setSkipped(skipped.includes(p) ? skipped.filter((x) => x !== p) : [...skipped, p]);
  return (
    <>
      <p className="text-sm text-text-secondary">
        Connect the ones you use — none is required, and anything you skip can be connected later in Settings → Connections. Catch never asks for a
        password.
      </p>
      {result && RESULT_TEXT[result.result] && (
        <p role="status" data-testid="onboarding-result" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
          {label} {RESULT_TEXT[result.result]}
        </p>
      )}
      {query.isLoading && <CardSkeleton lines={3} />}
      {query.isError && <p className="text-sm text-band-red-text">Couldn't load the sources. You can carry on and connect them later.</p>}
      {offered.map((c) => (
        <div key={c.provider} className="flex flex-col gap-2">
          <p className="text-sm text-text-secondary">
            <span className="font-medium text-text-primary">{c.label}:</span> {PROVIDES[c.provider]}
          </p>
          {skipped.includes(c.provider) && !c.connected ? (
            <Card>
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="text-text-tertiary">Skipped for now</span>
                <button type="button" className={SECONDARY} onClick={() => toggleSkip(c.provider)}>
                  Connect instead
                </button>
              </div>
            </Card>
          ) : (
            <>
              <ConnectionCard card={c} returnTo="onboarding" />
              {!c.connected && (
                <button type="button" className="self-end min-h-11 px-3 text-sm text-text-tertiary hover:text-text-secondary" onClick={() => toggleSkip(c.provider)}>
                  Skip {c.label}
                </button>
              )}
            </>
          )}
        </div>
      ))}
      <div className="flex justify-between">
        <button type="button" onClick={onBack} className={SECONDARY}>
          Back
        </button>
        <button type="button" onClick={onNext} className={PRIMARY}>
          Next
        </button>
      </div>
    </>
  );
}

function PreferencesStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const [maxHr, setMaxHr] = useState("");
  const [sleepH, setSleepH] = useState("");
  const [ftp, setFtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => {
      const patch: Record<string, number> = {};
      if (maxHr) patch.max_hr = Number(maxHr);
      if (sleepH) patch.sleep_need_seconds = Math.round(Number(sleepH) * 3600);
      if (ftp) patch.ftp_watts = Number(ftp);
      return Object.keys(patch).length ? saveSettings(patch) : Promise.resolve(null);
    },
    onSuccess: onNext,
    onError: (e: Error) => setError(e.message),
  });
  const invalid = (maxHr !== "" && !(Number(maxHr) >= 120 && Number(maxHr) <= 230)) || (sleepH !== "" && !(Number(sleepH) >= 4 && Number(sleepH) <= 12)) || (ftp !== "" && !(Number(ftp) >= 50 && Number(ftp) <= 600));
  return (
    <Card>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-text-secondary">All optional. Leave anything blank and Catch works it out from your data (a Concept2 profile sets max heart rate, for example).</p>
        <label className="flex flex-col gap-1.5">
          <span className="font-medium text-text-primary">Max heart rate (bpm)</span>
          <span className="text-xs text-text-tertiary">Sets your heart-rate zones and strain.</span>
          <input inputMode="numeric" value={maxHr} onChange={(e) => setMaxHr(e.target.value.replace(/\D/g, ""))} className={INPUT} placeholder="e.g. 192" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="font-medium text-text-primary">Sleep you need (hours)</span>
          <span className="text-xs text-text-tertiary">Used by the recovery score. Default 8.</span>
          <input inputMode="decimal" value={sleepH} onChange={(e) => setSleepH(e.target.value.replace(/[^\d.]/g, ""))} className={INPUT} placeholder="8" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="font-medium text-text-primary">Cycling FTP (watts)</span>
          <span className="text-xs text-text-tertiary">Only if you ride with power; otherwise leave it blank.</span>
          <input inputMode="numeric" value={ftp} onChange={(e) => setFtp(e.target.value.replace(/\D/g, ""))} className={INPUT} placeholder="—" />
        </label>
        {invalid && <p role="alert" className="text-band-red-text">Check the numbers: max HR 120–230, sleep 4–12 hours, FTP 50–600 W.</p>}
        {error && <p role="alert" className="text-band-red-text">{error}</p>}
        <div className="flex justify-between">
          <button type="button" onClick={onBack} className={SECONDARY}>
            Back
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onNext} className={SECONDARY}>
              Skip
            </button>
            <button type="button" disabled={invalid || save.isPending} onClick={() => save.mutate()} className={PRIMARY}>
              Save and continue
            </button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function SyncStep({ onNext, onLeave }: { onNext: () => void; onLeave: () => void }) {
  const started = useQuery({ queryKey: ["onboarding-sync"], queryFn: startOnboardingSync, staleTime: Infinity, retry: false });
  const connections = useQuery({ queryKey: ["connections"], queryFn: fetchConnections, refetchInterval: 5000 });
  const connected = (connections.data?.connections ?? []).filter((c) => c.connected);
  return (
    <>
      <Card>
        <div className="flex flex-col gap-3 text-sm" aria-live="polite">
          {connected.length === 0 ? (
            <p className="text-text-secondary">Nothing is connected yet, so there's nothing to import. You can connect sources any time in Settings.</p>
          ) : (
            <>
              <p className="text-text-secondary">
                The last 30 days come first; older history keeps importing in the background, a month at a time. You don't need to wait here.
              </p>
              {connected.map((c) => (
                <SyncRow key={c.provider} card={c} started={started.data?.started.includes(c.provider) ?? false} />
              ))}
            </>
          )}
          {started.isError && <p role="alert" className="text-band-red-text">Couldn't start the import now — Catch will try again on its own.</p>}
        </div>
      </Card>
      <div className="flex justify-between">
        <button type="button" onClick={onLeave} className={SECONDARY}>
          Go to dashboard
        </button>
        <button type="button" onClick={onNext} className={PRIMARY}>
          Continue
        </button>
      </div>
    </>
  );
}

function SyncRow({ card, started }: { card: Conn; started: boolean }) {
  const done = card.last_success_at != null && !card.importing_history_from;
  const text = card.status !== "connected" ? statusLabel(card) : done ? "Up to date" : card.last_success_at ? "Importing history in the background" : started ? "Importing your last 30 days…" : "Waiting";
  return (
    <div className="flex items-center justify-between gap-2 rounded-md bg-surface-2 px-3 py-2" data-testid={`sync-${card.provider}`}>
      <span className="font-medium text-text-primary">{card.label}</span>
      <span className="text-text-secondary">{text}</span>
    </div>
  );
}

function DoneStep({ skipped, onFinish, busy, onBack }: { skipped: ProviderId[]; onFinish: () => void; busy: boolean; onBack: () => void }) {
  const connections = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  const offered = (connections.data?.connections ?? []).filter((c) => c.available);
  const connected = offered.filter((c) => c.connected).map((c) => c.label);
  const notNow = offered.filter((c) => !c.connected).map((c) => c.label);
  const zone = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  return (
    <Card>
      <dl className="flex flex-col gap-2 text-sm" data-testid="onboarding-summary">
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">Connected</dt>
          <dd className="text-right text-text-primary">{connected.length ? connected.join(", ") : "Nothing yet"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{skipped.length ? "Skipped" : "Not connected"}</dt>
          <dd className="text-right text-text-primary">{notNow.length ? notNow.join(", ") : "—"}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">Time zone</dt>
          <dd className="text-right text-text-primary">{zoneLabel(zone.data?.timezone ?? zone.data?.current_zone)}</dd>
        </div>
      </dl>
      <p className="mt-3 text-sm text-text-tertiary">You can change any of this in Settings, and run setup again from there.</p>
      <div className="mt-4 flex justify-between">
        <button type="button" onClick={onBack} className={SECONDARY}>
          Back
        </button>
        <button type="button" onClick={onFinish} disabled={busy} className={PRIMARY}>
          Go to my dashboard
        </button>
      </div>
    </Card>
  );
}
