import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchConnections, fetchSettings, isMock, saveSettings } from "../lib/api";
import { STATUS_GLYPH, STATUS_LABEL } from "../lib/connections";
import { formatRelativeTime } from "../lib/format";
import { useTheme } from "../lib/theme";
import type { Settings } from "../lib/types";
import { Card } from "../components/ui/Card";
import { buttonClass } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { controlBase, controlClass } from "../components/ui/Field";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { MoonIcon, SunIcon } from "../components/shell/icons";
import { CoachSettingsCard } from "../components/coach/CoachSettingsCard";
import { NutritionTargetsCard } from "../components/nutrition/NutritionTargetsCard";
import { IllnessBacktestCard } from "../components/settings/IllnessBacktestCard";
import { NotificationsCard } from "../components/settings/NotificationsCard";
import { RecoveryInputsCard } from "../components/settings/RecoveryInputsCard";
import { AccountCard } from "../components/settings/AccountCard";
import { isPublic } from "../lib/deployment";
import { TimeZoneCard } from "../components/settings/TimeZoneCard";
import { HrZonesCard } from "../components/settings/HrZonesCard";

const ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"] as const;
const SOURCES = ["garmin", "withings", "concept2", "whoop"] as const;
const SECTIONS: [string, string][] = [
  ["sources", "Sources and data"],
  ["privacy", "Sharing and visibility"],
  ["training", "Training and zones"],
  ["health", "Health and notifications"],
  ["coach", "Coach and AI"],
  ["general", "General"],
];

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { theme, toggle } = useTheme();
  // Session 33: every card loads on its own — no card waits for another's request, and a failed one shows its own Retry. Stable
  // settings are kept for 5 minutes so moving between Settings pages doesn't refetch them.
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings, staleTime: 5 * 60_000 });
  // Launch audit L-32: list only the sources this deployment offers (Garmin BYOK can be switched off), never one Connections says
  // "isn't available" for. Session 33: the status line comes from this same response (it carries last sync and status), so the
  // page no longer also calls /api/sync/status, which rebuilt the same cards on the server.
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: fetchConnections, staleTime: 60_000 });
  const offered = SOURCES.filter((s) => connectionsQuery.data?.connections.find((c) => c.provider === s)?.available ?? true);

  const [form, setForm] = useState<Settings | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settingsQuery.data && !dirty) setForm(settingsQuery.data);
  }, [settingsQuery.data, dirty]);

  const { toast } = useToast();
  const save = useMutation({
    mutationFn: (patch: Partial<Settings>) => saveSettings(patch),
    onSuccess: (updated) => {
      setDirty(false);
      toast("Settings saved");
      queryClient.setQueryData(["settings"], updated);
      // Zone boundaries and every workout's cached zones follow the saved values (recalculated server-side).
      queryClient.invalidateQueries({ queryKey: ["zones"] });
      queryClient.invalidateQueries({ queryKey: ["workout"] });
    },
  });

  const formPending = settingsQuery.isError ? (
    <ErrorState message="Couldn't load your settings." onRetry={() => settingsQuery.refetch()} />
  ) : (
    <CardSkeleton lines={3} />
  );

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
    setDirty(true);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow="Account" title="Settings" />
      <div className="lg:grid lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-8">
        <nav aria-label="Settings sections" className="hidden lg:block">
          <ul className="sticky top-8 flex flex-col gap-0.5 text-sm">
            {SECTIONS.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className="flex min-h-9 items-center rounded-md px-2.5 text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary">
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex min-w-0 flex-col gap-8">
      <section id="sources" aria-labelledby="sources-h" className="flex scroll-mt-24 flex-col gap-4 lg:gap-5">
        <SectionHeader id="sources-h" title="Sources and data" description="Where your data comes from and how it syncs." />
      <Card
        title="Connected sources"
        action={
          <Link to="/settings/connections" className="text-sm font-medium text-accent hover:underline">
            Manage
          </Link>
        }
      >
        <div className="flex flex-col gap-3" data-testid="connected-sources">
          {connectionsQuery.isError && <ErrorState message="Couldn't load your connected sources." onRetry={() => connectionsQuery.refetch()} />}
          {connectionsQuery.isLoading && <CardSkeleton lines={2} />}
          {connectionsQuery.data && offered.map((source) => {
            const status = connectionsQuery.data.connections.find((c) => c.provider === source);
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

      </section>
      <section id="privacy" aria-labelledby="privacy-h" className="flex scroll-mt-24 flex-col gap-4 lg:gap-5">
        <SectionHeader id="privacy-h" title="Sharing and visibility" description="Who and what can see your data." />
<div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
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
</div>
      </section>
      <section id="training" aria-labelledby="training-h" className="flex scroll-mt-24 flex-col gap-4 lg:gap-5">
        <SectionHeader id="training-h" title="Training and zones" description="How recovery, zones and strain are calculated." />
      {!form ? formPending : (
        <>
      <RecoveryInputsCard settings={form} />

      <HrZonesCard form={form} update={update} />

      <Card title="Power zones">
        <div className="mb-3 flex gap-2" role="radiogroup" aria-label="Workout screens open on">
          {(["hr", "power"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={form.zone_mode === mode}
              onClick={() => update("zone_mode", mode)}
              className={`min-h-11 rounded-md border px-4 text-sm font-medium transition-colors ${
                form.zone_mode === mode ? "border-accent bg-accent-soft text-text-primary" : "border-border text-text-tertiary hover:text-text-primary"
              }`}
            >
              {form.zone_mode === mode ? "● " : "○ "}
              {mode === "hr" ? "Heart rate" : "Power"}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full max-w-md text-sm">
            <thead>
              <tr className="text-left text-xs text-text-tertiary">
                <th className="py-1 font-normal">Zone</th>
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
                      value={form.zones.power_pct[zone]}
                      onChange={(e) =>
                        update("zones", { ...form.zones, power_pct: { ...form.zones.power_pct, [zone]: Number(e.target.value) } })
                      }
                      className={`${controlBase} min-h-10 w-24 font-mono-nums`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-text-tertiary">{"Which table workout screens open on. Defaults — confirm with your coach before training off them."}</p>
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
                className={controlClass}
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
            className={`${controlBase} w-24 font-mono-nums`}
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
                className={controlClass}
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
              className={`${controlBase} w-24 font-mono-nums`}
            />
          </label>
          <label className="flex items-center gap-3 text-sm text-text-secondary">
            Min % of moving time
            <input
              type="number"
              step="0.01"
              value={form.min_zone_pct}
              onChange={(e) => update("min_zone_pct", Number(e.target.value))}
              className={`${controlBase} w-24 font-mono-nums`}
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
              className={`${controlBase} w-24 font-mono-nums`}
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
              className={`${controlBase} w-24 font-mono-nums`}
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
              className={`${controlBase} w-24 font-mono-nums`}
            />
          </label>
        </div>
      </Card>
        </>
      )}
      {dirty && form && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => save.mutate(form)}
            disabled={save.isPending}
            className={buttonClass("primary", "md", "px-6")}
          >
            {save.isPending ? "Saving…" : "Save settings"}
          </button>
        </div>
      )}

      </section>
      <section id="health" aria-labelledby="health-h" className="flex scroll-mt-24 flex-col gap-4 lg:gap-5">
        <SectionHeader id="health-h" title="Health and notifications" description="Fuelling targets, reminders and the illness flag." />
      <NotificationsCard />
      <NutritionTargetsCard />
      <IllnessBacktestCard />

      </section>
      <section id="coach" aria-labelledby="coach-h" className="flex scroll-mt-24 flex-col gap-4 lg:gap-5">
        <SectionHeader id="coach-h" title="Coach and AI" description="The AI coach's settings and spending." />
      <CoachSettingsCard />

      </section>
      <section id="general" aria-labelledby="general-h" className="flex scroll-mt-24 flex-col gap-4 lg:gap-5">
        <SectionHeader id="general-h" title="General" description="Time, appearance and setup." />
      <TimeZoneCard />
      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
      <Card title="Appearance">
        <button
          type="button"
          onClick={toggle}
          className={buttonClass("secondary")}
        >
          {theme === "dark" ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
          Switch to {theme === "dark" ? "light" : "dark"} theme
        </button>
      </Card>
      <Card title="First-run setup">
        <p className="text-sm text-text-secondary">Walk through connecting sources, your time zone and training basics again. Nothing you already set is lost.</p>
        <Link to="/welcome?restart=1" className={buttonClass("secondary", "md", "mt-3")}>
          Run setup again
        </Link>
      </Card>
      </div>

      </section>
        </div>
      </div>

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
