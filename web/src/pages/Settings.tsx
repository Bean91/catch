import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchSettings, fetchSyncStatus, saveSettings, triggerSync } from "../lib/api";
import { formatRelativeTime } from "../lib/format";
import { daysUntilGarminKeyExpires, GARMIN_KEY_PAGE_URL } from "../lib/garminKey";
import { useTheme } from "../lib/theme";
import type { Settings } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { MoonIcon, SunIcon } from "../components/shell/icons";
import { CoachSettingsCard } from "../components/coach/CoachSettingsCard";

const ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"] as const;
const SOURCES = ["garmin", "withings", "concept2"] as const;

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { theme, toggle } = useTheme();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const statusQuery = useQuery({ queryKey: ["sync-status"], queryFn: fetchSyncStatus });

  const [form, setForm] = useState<Settings | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settingsQuery.data && !dirty) setForm(settingsQuery.data);
  }, [settingsQuery.data, dirty]);

  const save = useMutation({
    mutationFn: (patch: Partial<Settings>) => saveSettings(patch),
    onSuccess: (updated) => {
      setDirty(false);
      queryClient.setQueryData(["settings"], updated);
    },
  });

  const sync = useMutation({
    mutationFn: (source: string) => triggerSync(source),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["sync-status"] }),
  });

  if (settingsQuery.isLoading || !form) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={2} />
        <CardSkeleton lines={2} />
      </div>
    );
  }

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
    setDirty(true);
  }

  const warnDays = daysUntilGarminKeyExpires(form.garmin_key_expires_on);

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Settings</h1>

      <Card title="Connected sources">
        <div className="flex flex-col gap-3">
          {SOURCES.map((source) => {
            const status = statusQuery.data?.find((s) => s.source === source);
            return (
              <div key={source} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3 last:border-0 last:pb-0">
                <div>
                  <div className="text-sm font-medium capitalize text-text-primary">{source}</div>
                  <div className="text-xs text-text-tertiary">
                    {status?.last_error ? (
                      <span className="text-band-red-text">failed — {status.last_error}</span>
                    ) : (
                      <>last sync {formatRelativeTime(status?.last_success_at)}</>
                    )}
                    {status?.token_expires_at && <> · token valid until {new Date(status.token_expires_at).toLocaleString()}</>}
                  </div>
                </div>
                {source === "withings" ? (
                  <a
                    href="/auth/withings/start"
                    className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent"
                  >
                    Reconnect
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={() => sync.mutate(source)}
                    disabled={sync.isPending}
                    className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50"
                  >
                    {sync.isPending ? "Syncing…" : "Sync now"}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-4 border-t border-border pt-3">
          <label className="flex flex-col gap-1.5 text-sm text-text-secondary sm:flex-row sm:items-center sm:gap-3">
            Garmin personal API key expires on
            <input
              type="date"
              value={form.garmin_key_expires_on ?? ""}
              onChange={(e) => update("garmin_key_expires_on", e.target.value || null)}
              className="min-h-11 rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary"
            />
          </label>
          <p className="mt-1 text-xs text-text-tertiary">
            Garmin's API exposes no key-expiry field — this is a reminder only you can set, separate from the token-refresh
            date above.
          </p>
          {warnDays != null && warnDays <= 14 && (
            <p className="mt-2 rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-xs text-band-red-text">
              {warnDays <= 0 ? "Garmin key has expired" : `Garmin key expires in ${warnDays} day(s)`} —{" "}
              <a href={GARMIN_KEY_PAGE_URL} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2">
                create a new one
              </a>
              .
            </p>
          )}
        </div>
      </Card>

      <Card title="Zones">
        <div className="mb-3 flex gap-2">
          {(["hr", "power"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => update("zone_mode", mode)}
              className={`min-h-11 rounded-md border px-4 text-sm font-medium transition-colors ${
                form.zone_mode === mode ? "border-accent text-accent" : "border-border text-text-tertiary"
              }`}
            >
              {mode === "hr" ? "Heart rate" : "Power"}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full max-w-md min-w-[360px] text-sm">
            <thead>
              <tr className="text-left text-xs text-text-tertiary">
                <th className="py-1 font-normal">Zone</th>
                <th className="py-1 font-normal">% max HR</th>
                <th className="py-1 font-normal">% 2k watts</th>
              </tr>
            </thead>
            <tbody>
              {ZONE_ORDER.map((zone) => (
                <tr key={zone}>
                  <td className="py-1.5 text-text-primary">{zone}</td>
                  <td className="py-1.5">
                    <input
                      type="number"
                      value={form.zones.hr_pct[zone]}
                      onChange={(e) =>
                        update("zones", { ...form.zones, hr_pct: { ...form.zones.hr_pct, [zone]: Number(e.target.value) } })
                      }
                      className="font-mono-nums w-20 rounded-md border border-border bg-surface-2 px-2 py-1.5 text-text-primary"
                    />
                  </td>
                  <td className="py-1.5">
                    <input
                      type="number"
                      value={form.zones.power_pct[zone]}
                      onChange={(e) =>
                        update("zones", { ...form.zones, power_pct: { ...form.zones.power_pct, [zone]: Number(e.target.value) } })
                      }
                      className="font-mono-nums w-20 rounded-md border border-border bg-surface-2 px-2 py-1.5 text-text-primary"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-text-tertiary">{"Defaults — confirm with your coach before training off them."}</p>
      </Card>

      <Card title="Profile & units">
        <div className="flex flex-col gap-3 sm:flex-row sm:gap-6">
          <label className="flex items-center gap-3 text-sm text-text-secondary">
            Max HR
            <input
              type="number"
              value={form.max_hr ?? ""}
              onChange={(e) => update("max_hr", e.target.value ? Number(e.target.value) : null)}
              className="font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
            />
          </label>
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-secondary">Units</span>
            {(["metric", "imperial"] as const).map((u) => (
              <button
                key={u}
                type="button"
                onClick={() => update("units", u)}
                className={`min-h-11 rounded-md border px-3.5 text-sm font-medium capitalize transition-colors ${
                  form.units === u ? "border-accent text-accent" : "border-border text-text-tertiary"
                }`}
              >
                {u}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Appearance">
        <button
          type="button"
          onClick={toggle}
          className="flex min-h-11 items-center gap-3 rounded-md border border-border px-4 text-sm text-text-primary transition-colors hover:border-accent"
        >
          {theme === "dark" ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
          Switch to {theme === "dark" ? "light" : "dark"} theme
        </button>
      </Card>

      <CoachSettingsCard />

      {/* pointer-events-none on the row, -auto on the button: the AI coach card below grew
          long enough that this floating bar's empty space (full-width, invisible) now
          scrolls over other buttons like Test connection — without this, the empty area
          would still intercept their clicks even though nothing is painted there. */}
      <div className="sticky bottom-[calc(5rem+env(safe-area-inset-bottom))] flex justify-end pointer-events-none sm:static sm:bottom-auto">
        <button
          type="button"
          onClick={() => save.mutate(form)}
          disabled={!dirty || save.isPending}
          className="pointer-events-auto min-h-11 rounded-md bg-accent px-6 text-sm font-medium text-accent-contrast shadow-lg transition-opacity hover:opacity-90 disabled:opacity-50 disabled:shadow-none"
        >
          {save.isPending ? "Saving…" : "Save settings"}
        </button>
      </div>
    </div>
  );
}
