import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { formatRelativeTime } from "../lib/format";
import {
  availability, buildPreview, openHealthConnectSettings, CATEGORY_INFO, categoriesFor, deleteImportedHealthData, fetchHealthStatus, healthPlatform, requestOsPermission, revokeConsent,
  saveConsent, sendPreview, sinceCursor, type HealthCategory, type HealthPreview,
} from "../lib/native/health";
import { isNative } from "../lib/native/platform";

const PLATFORM_NAME = { apple_health: "Apple Health", health_connect: "Health Connect" } as const;

// Settings → Health data. The order of the steps below is the consent flow (docs/mobile/health-data.md): tick what to share →
// we record that → the phone asks its own permission → a preview of exactly what would be sent → send only after confirming.
export function HealthDataPage() {
  const platform = healthPlatform();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["health-status"], queryFn: fetchHealthStatus, enabled: !!platform });
  const [chosen, setChosen] = useState<HealthCategory[] | null>(null);
  const [preview, setPreview] = useState<HealthPreview | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [needsSettings, setNeedsSettings] = useState(false);

  const consent = status.data?.consents.find((c) => c.platform === platform);
  const active = !!consent?.active;
  const categories = chosen ?? consent?.categories ?? [];

  const start = useMutation({
    mutationFn: async () => {
      if (!platform || !status.data) throw new Error("not ready");
      const av = await availability();
      if (!av.available) throw new Error(platform === "health_connect" ? "Health Connect isn't available on this phone. Install or enable it from the Play Store, then try again." : "Apple Health isn't available on this device.");
      await saveConsent(platform, categories); // 1. the consent is recorded BEFORE the phone is asked anything
      const os = await requestOsPermission(categories); // 2. the phone's own permission sheet
      // Health Connect says exactly what was allowed, so only that is read. HealthKit can't say, so its consented list is used and an
      // empty type simply returns nothing.
      const allowed = platform === "apple_health" ? categories : os.readable;
      if (!allowed.length) {
        setNeedsSettings(true);
        throw new Error("Health Connect didn't allow any of those types, so nothing was read. You can change this in Health Connect → App permissions → Catch.");
      }
      setNeedsSettings(false);
      const p = await buildPreview(platform, allowed, status.data, await sinceCursor(platform)); // 3. nothing is sent yet
      setPreview(p);
      qc.invalidateQueries({ queryKey: ["health-status"] });
    },
    onError: (e: Error) => setNotice(e.message),
  });

  const send = useMutation({
    mutationFn: async () => {
      if (!platform || !preview) return;
      const r = await sendPreview(platform, preview); // 4. only now does anything leave the phone
      setNotice(`Imported ${r.workouts} workout${r.workouts === 1 ? "" : "s"} and ${r.readings} daily reading${r.readings === 1 ? "" : "s"}.${r.skipped_duplicate ? ` ${r.skipped_duplicate} already came from a source Catch syncs directly and were left out.` : ""}`);
      setPreview(null);
      qc.invalidateQueries({ queryKey: ["health-status"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["workouts"] });
    },
    onError: (e: Error) => setNotice(e.message),
  });

  const stop = useMutation({
    mutationFn: async (deleteData: boolean) => {
      if (!platform) return;
      await revokeConsent(platform, deleteData);
      setNotice(deleteData ? "Sharing is off and what was imported has been deleted." : "Sharing is off. What was imported stays until you delete it.");
      setConfirmDelete(false);
      setChosen(null);
      qc.invalidateQueries({ queryKey: ["health-status"] });
    },
    onError: (e: Error) => setNotice(e.message),
  });

  const wipe = useMutation({
    mutationFn: deleteImportedHealthData,
    onSuccess: (r) => {
      setNotice(`Deleted ${r.workouts} workout${r.workouts === 1 ? "" : "s"} and ${r.readings} daily reading${r.readings === 1 ? "" : "s"} imported from your phone.`);
      qc.invalidateQueries({ queryKey: ["health-status"] });
    },
  });

  if (!isNative() || !platform) {
    return (
      <div className="flex flex-col gap-4">
        <Link to="/settings" className="text-sm font-medium text-accent hover:underline">← Settings</Link>
        <h1 className="text-lg font-semibold text-text-primary">Health data</h1>
        <Card>
          <p className="text-sm text-text-secondary">Importing from Apple Health or Health Connect is available in the Catch app on your phone. It isn't available in a web browser.</p>
        </Card>
      </div>
    );
  }
  const name = PLATFORM_NAME[platform];
  const counts = status.data?.counts[platform];

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/settings/connections" className="text-sm font-medium text-accent hover:underline">← Connections</Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">{name}</h1>
        <p className="mt-1 text-sm text-text-secondary">Bring workouts, sleep and heart data from your phone into Catch. Off until you turn it on, and you choose each type.</p>
      </div>

      {notice && (
        <div role="status" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
          {notice}
          {needsSettings && platform === "health_connect" && (
            <button type="button" onClick={() => void openHealthConnectSettings()} className="mt-2 block min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-primary">
              Open Health Connect
            </button>
          )}
        </div>
      )}
      {status.isLoading && <CardSkeleton lines={4} />}

      <Card title="What is shared">
        <ul className="flex flex-col gap-3">
          {categoriesFor(platform).map((c) => (
            <li key={c}>
              <label className="flex items-start gap-3 text-sm text-text-primary">
                <input
                  type="checkbox"
                  className="mt-0.5 h-5 w-5 shrink-0 accent-accent"
                  checked={categories.includes(c)}
                  disabled={start.isPending || send.isPending}
                  onChange={(e) => setChosen(e.target.checked ? [...categories, c] : categories.filter((x) => x !== c))}
                />
                <span>
                  {CATEGORY_INFO[c].label}
                  <span className="block text-xs text-text-tertiary">{CATEGORY_INFO[c].detail}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
        <div className="mt-4 rounded-md border border-border bg-surface-2 p-3 text-xs text-text-secondary">
          <p className="font-medium text-text-primary">Where it goes</p>
          <p className="mt-1">
            Only the types you tick are read from {name} and sent over an encrypted connection to your Catch account, where they are stored with your other training data and shown with the app that recorded them. Nothing is sent
            until you confirm a preview. Catch doesn't use it for advertising, and doesn't share it with other people or clubs. The AI coach can see it only if you've allowed that
            category in <Link to="/settings/privacy" className="font-medium text-accent hover:underline">Privacy</Link>.
          </p>
          <p className="mt-2">Workouts that Garmin, Withings, Whoop or Concept2 already give Catch directly are left out, so nothing is counted twice.</p>
          {platform === "apple_health" && <p className="mt-2">Apple doesn't tell apps which types you allowed. If a type returns nothing, check Settings → Health → Data Access &amp; Devices → Catch.</p>}
        </div>
        <button
          type="button"
          disabled={!categories.length || start.isPending || send.isPending}
          onClick={() => { setNotice(null); start.mutate(); }}
          className="mt-4 min-h-11 w-full rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {start.isPending ? "Reading…" : active ? "Review what's new" : `Continue — ${name} will ask for permission`}
        </button>
      </Card>

      {preview && (
        <Card title="Ready to send">
          <p className="text-sm text-text-secondary">Between {new Date(preview.from).toLocaleDateString()} and today, Catch would add:</p>
          <ul className="mt-2 list-inside list-disc text-sm text-text-primary">
            {preview.counts.workouts > 0 && <li>{preview.counts.workouts} workout{preview.counts.workouts === 1 ? "" : "s"}</li>}
            {preview.counts.sleep > 0 && <li>{preview.counts.sleep} night{preview.counts.sleep === 1 ? "" : "s"} of sleep</li>}
            {preview.counts.resting_hr > 0 && <li>{preview.counts.resting_hr} resting heart rate day{preview.counts.resting_hr === 1 ? "" : "s"}</li>}
            {preview.counts.spo2 > 0 && <li>{preview.counts.spo2} blood-oxygen day{preview.counts.spo2 === 1 ? "" : "s"}</li>}
            {preview.counts.hrv > 0 && <li>{preview.counts.hrv} HRV day{preview.counts.hrv === 1 ? "" : "s"}</li>}
            {!preview.payload.workouts.length && !preview.payload.readings.length && <li>Nothing new — no data came back for the types you chose.</li>}
          </ul>
          {preview.counts.skipped_duplicate > 0 && <p className="mt-2 text-xs text-text-tertiary">{preview.counts.skipped_duplicate} record(s) came from apps whose data Catch already syncs, and are left out.</p>}
          <div className="mt-4 flex gap-2">
            <button type="button" disabled={send.isPending || (!preview.payload.workouts.length && !preview.payload.readings.length)} onClick={() => send.mutate()} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-50">
              {send.isPending ? "Sending…" : "Send to Catch"}
            </button>
            <button type="button" disabled={send.isPending} onClick={() => setPreview(null)} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary">Cancel</button>
          </div>
        </Card>
      )}

      {consent && (
        <Card title="Your data">
          <p className="text-sm text-text-secondary">
            {active ? `Sharing is on (${consent.categories.map((c) => CATEGORY_INFO[c].label.toLowerCase()).join(", ")}). Catch checks for new data each time you open the app.` : "Sharing is off."}
            {consent.last_import_at ? ` Last import ${formatRelativeTime(consent.last_import_at)}.` : ""}
          </p>
          {counts && <p className="mt-1 text-xs text-text-tertiary">Held now: {counts.workouts} workouts, {counts.readings} daily readings from {name}.</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {active && <button type="button" disabled={stop.isPending} onClick={() => stop.mutate(false)} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary">Stop sharing</button>}
            {!confirmDelete ? (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-band-red-text">Delete imported data…</button>
            ) : (
              <div role="alertdialog" aria-label="Delete imported health data" className="w-full rounded-md border border-band-red/40 p-3 text-sm text-text-secondary">
                This turns sharing off and permanently deletes the workouts and readings imported from {name}. Data from Garmin, Withings and your other sources stays.
                <div className="mt-3 flex gap-2">
                  <button type="button" disabled={stop.isPending} onClick={() => stop.mutate(true)} className="min-h-11 rounded-md bg-band-red px-4 text-sm font-medium text-white disabled:opacity-50">Delete</button>
                  <button type="button" onClick={() => setConfirmDelete(false)} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary">Keep</button>
                </div>
              </div>
            )}
          </div>
          {wipe.isPending && <p className="mt-2 text-xs text-text-tertiary">Deleting…</p>}
        </Card>
      )}
    </div>
  );
}
