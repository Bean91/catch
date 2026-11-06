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
import { NutritionTargetsCard } from "../components/nutrition/NutritionTargetsCard";
import { IllnessBacktestCard } from "../components/settings/IllnessBacktestCard";

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

      <Card title="Cross-source matching">
        <p className="mb-3 text-xs text-text-tertiary">
          Which source wins for each metric when a watch, Peloton-pushed activity, and/or Concept2 result get merged into one
          workout — comma-separated, first match wins. "manual" always sorts last for body-comp metrics below, regardless of order.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["power", "cadence", "title", "distance_indoor_bike"] as const).map((field) => (
            <label key={field} className="flex flex-col gap-1 text-sm text-text-secondary">
              <span className="capitalize">{field.replace(/_/g, " ")}</span>
              <input
                defaultValue={form.field_priority[field].join(", ")}
                onBlur={(e) =>
                  update("field_priority", { ...form.field_priority, [field]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
                }
                className="min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
              />
            </label>
          ))}
        </div>
        <label className="mt-3 flex flex-col gap-1 text-sm text-text-secondary sm:flex-row sm:items-center sm:gap-3">
          Cycling FTP (watts)
          <input
            type="number"
            value={form.ftp_watts ?? ""}
            onChange={(e) => update("ftp_watts", e.target.value ? Number(e.target.value) : null)}
            placeholder="auto"
            className="font-mono-nums w-24 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
          />
          <span className="text-xs text-text-tertiary">Estimated from the best 20-minute power x 0.95 per ride if left blank.</span>
        </label>
      </Card>

      <Card title="Body composition sources">
        <p className="mb-3 text-xs text-text-tertiary">Default Withings first, Garmin second — never averaged, shown per-day on the Body page.</p>
        <div className="grid gap-3 sm:grid-cols-3">
          {(["weight", "fat_pct", "muscle_kg"] as const).map((field) => (
            <label key={field} className="flex flex-col gap-1 text-sm text-text-secondary">
              <span className="capitalize">{field.replace(/_/g, " ")}</span>
              <input
                defaultValue={form.body_comp_priority[field].join(", ")}
                onBlur={(e) =>
                  update("body_comp_priority", { ...form.body_comp_priority, [field]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
                }
                className="min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
              />
            </label>
          ))}
        </div>
      </Card>

      <Card title="Zones & strain from samples">
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-3 text-sm text-text-secondary">
            Min minutes to lead the label
            <input
              type="number"
              value={form.min_zone_minutes}
              onChange={(e) => update("min_zone_minutes", Number(e.target.value))}
              className="font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
            />
          </label>
          <label className="flex items-center gap-3 text-sm text-text-secondary">
            Min % of moving time
            <input
              type="number"
              step="0.01"
              value={form.min_zone_pct}
              onChange={(e) => update("min_zone_pct", Number(e.target.value))}
              className="font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
            />
          </label>
        </div>
        <label className="mt-3 flex items-center gap-3 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={form.auto_trim_enabled}
            onChange={(e) => update("auto_trim_enabled", e.target.checked)}
            className="h-5 w-5 accent-accent"
          />
          Auto-detect "watch left running" and exclude it from averages
        </label>
        {form.auto_trim_enabled && (
          <label className="mt-2 flex items-center gap-3 text-sm text-text-secondary">
            Min idle seconds to count as left running
            <input
              type="number"
              value={form.auto_trim_min_idle_s}
              onChange={(e) => update("auto_trim_min_idle_s", Number(e.target.value))}
              className="font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
            />
          </label>
        )}
      </Card>

      <Card title="Daily activity in strain">
        <p className="mb-3 text-xs text-text-tertiary">
          Non-exercise steps and active kcal (outside logged workouts) add a small, capped contribution to today's strain —
          workouts stay the dominant driver.
        </p>
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-3 text-sm text-text-secondary">
            Cap (of 0–21)
            <input
              type="number"
              step="0.1"
              min="0"
              value={form.daily_activity_strain_cap}
              onChange={(e) => update("daily_activity_strain_cap", Number(e.target.value))}
              className="font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
            />
          </label>
          <label className="flex items-center gap-3 text-sm text-text-secondary">
            Weight
            <input
              type="number"
              step="0.1"
              min="0"
              value={form.daily_activity_strain_weight}
              onChange={(e) => update("daily_activity_strain_weight", Number(e.target.value))}
              className="font-mono-nums w-20 min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
            />
          </label>
        </div>
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

      <NutritionTargetsCard />

      <IllnessBacktestCard />

      <CoachSettingsCard />

      {/* Plain in-flow button, not floating. Both `fixed` and `sticky` versions of this bar
          ended up visibly overlapping mid-page content (the Zones/AI-coach cards) on this
          page's particular content-to-viewport ratio at 390px — `fixed` because it's glued
          to the viewport for the page's entire height regardless of scroll, and `sticky`
          because it engages far earlier than "near the true end" once this page has more
          than roughly a screen of content left below it, then stays engaged for the rest of
          the scroll. Rendering it as normal content guarantees it can never overlap anything,
          at the cost of needing to scroll to it rather than it always being visible — a
          standard, unsurprising tradeoff for a settings form. Only mounted once there's
          something to save. */}
      {dirty && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => save.mutate(form)}
            disabled={save.isPending}
            className="min-h-11 rounded-md bg-accent px-6 text-sm font-medium text-accent-contrast shadow-lg transition-opacity hover:opacity-90 disabled:opacity-50 disabled:shadow-none"
          >
            {save.isPending ? "Saving…" : "Save settings"}
          </button>
        </div>
      )}

      {/* Lets a real device checklist confirm which build it's actually running (matches
          sw.js's own VERSION and version.json) — the one way to tell "the fix didn't work"
          apart from "this device is still on the old JS" without SSH access to the Pi. The
          commit is almost always "-dirty" on this app's Pi deploys (deploy.sh builds from
          whatever's in the working tree, not a clean checkout), which is the honest label, not
          a bug. */}
      <p className="text-center text-xs text-text-tertiary">
        Build {__BUILD_ID__} · {__COMMIT__}
      </p>
    </div>
  );
}
