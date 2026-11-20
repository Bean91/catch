import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchConnections, fetchSettings, fetchSyncStatus, isMock, saveSettings } from "../lib/api";
import { STATUS_GLYPH, STATUS_LABEL } from "../lib/connections";
import { formatRelativeTime } from "../lib/format";
import { useTheme } from "../lib/theme";
import type { Settings } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { MoonIcon, SunIcon } from "../components/shell/icons";
import { CoachSettingsCard } from "../components/coach/CoachSettingsCard";
import { NutritionTargetsCard } from "../components/nutrition/NutritionTargetsCard";
import { IllnessBacktestCard } from "../components/settings/IllnessBacktestCard";
import { NotificationsCard } from "../components/settings/NotificationsCard";
import { RecoveryInputsCard } from "../components/settings/RecoveryInputsCard";
import { AccountCard } from "../components/settings/AccountCard";
import { isPublic } from "../lib/deployment";

const ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"] as const;
const SOURCES = ["garmin", "withings", "concept2", "whoop"] as const;

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { theme, toggle } = useTheme();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const statusQuery = useQuery({ queryKey: ["sync-status"], queryFn: fetchSyncStatus });
  // Launch audit L-32: list only the sources this deployment offers (Garmin BYOK can be switched off), never one Connections says
  // "isn't available" for. Until the list loads, every source shows, as before.
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  const offered = SOURCES.filter((s) => connectionsQuery.data?.connections.find((c) => c.provider === s)?.available ?? true);

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

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Settings</h1>

      <Card
        title="Connected sources"
        action={
          <Link to="/settings/connections" className="text-sm font-medium text-accent hover:underline">
            Manage
          </Link>
        }
      >
        <div className="flex flex-col gap-3" data-testid="connected-sources">
          {offered.map((source) => {
            const status = statusQuery.data?.find((s) => s.source === source);
            const connected = status?.connected ?? false;
            const state = status?.status ?? "disconnected";
            return (
              <div key={source} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3 last:border-0 last:pb-0">
                <div>
                  <div className="text-sm font-medium capitalize text-text-primary">{source}</div>
                  <div className="text-xs text-text-tertiary">
                    {connected ? <>last sync {formatRelativeTime(status?.last_success_at)}</> : "connect it under Connections"}
                  </div>
                </div>
                <span className="text-xs text-text-secondary">
                  <span aria-hidden="true">{STATUS_GLYPH[connected ? state : "disconnected"]}</span> {connected ? STATUS_LABEL[state] : "Not connected"}
                </span>
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-3 border-t border-border pt-3 text-sm">
          <Link to="/settings/connections" className="font-medium text-accent hover:underline">
            Connect, replace a key or disconnect
          </Link>
          <Link to="/settings/status" className="font-medium text-accent hover:underline">
            Status
          </Link>
        </div>
      </Card>

      {(isPublic || isMock) && (
        <Card
          title="Clubs"
          action={
            <Link to="/clubs" data-testid="settings-clubs" className="text-sm font-medium text-accent hover:underline">
              Open
            </Link>
          }
        >
          <p className="text-sm text-text-secondary">
            Join or start a rowing club: roles, invitations, a team calendar, challenges and announcements. Junior clubs are private, coach-approved and never list their members.
          </p>
        </Card>
      )}

      <Card
        title="Privacy"
        action={
          <Link to="/settings/privacy" data-testid="settings-privacy" className="text-sm font-medium text-accent hover:underline">
            Open
          </Link>
        }
      >
        <p className="text-sm text-text-secondary">
          What the AI may see, what's public, apps connected to your data, download everything, delete selected data or your account.
        </p>
      </Card>

      {(isPublic || isMock) && (
        <Card
          title="Leaderboards"
          action={
            <Link to="/settings/leaderboards" data-testid="settings-leaderboards" className="text-sm font-medium text-accent hover:underline">
              Manage
            </Link>
          }
        >
          <p className="text-sm text-text-secondary">
            Publish verified erg results to the public leaderboards — only what you choose, with a preview first. Opt in or out and take results down any time.
          </p>
        </Card>
      )}

      <RecoveryInputsCard settings={form} />

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

      {/* Session 31 (launch audit L-22): a metric/imperial toggle sat here, but nothing read it — every figure stays metric — so it
          is gone until units are actually implemented. The stored `units` setting is untouched. */}
      <Card title="Profile">
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

      <NotificationsCard />

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
      {isPublic && <AccountCard />}

      <p className="text-center text-xs text-text-tertiary">
        Build {__BUILD_ID__} · {__COMMIT__}
      </p>
    </div>
  );
}
