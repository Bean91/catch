import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchPushSubscriptions, fetchSettings, fetchVapidPublicKey, saveSettings, sendTestPush } from "../../lib/api";
import { formatRelativeTime } from "../../lib/format";
import { currentSubscriptionEndpoint, disablePush, enablePush, isInstalledPwa, pushSupported, PushPermissionDeniedError } from "../../lib/push";
import type { Settings } from "../../lib/types";
import { Card } from "../ui/Card";

const TYPE_LABELS: Record<keyof Settings["notifications"]["types"], string> = {
  morning_brief: "Morning brief",
  illness: "Illness/overtraining warning",
  garmin_key_expiring: "Garmin key expiring",
  sync_broken: "Sync broken",
  test_reminder: "Test/race reminder (day before)",
};

function guessDeviceLabel(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows PC";
  return "This device";
}

const looksLikeIosSafariNotInstalled = () => /iPhone|iPad/.test(navigator.userAgent) && !isInstalledPwa();

export function NotificationsCard() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const subscriptionsQuery = useQuery({ queryKey: ["push-subscriptions"], queryFn: fetchPushSubscriptions });
  const vapidKeyQuery = useQuery({
    // Fetched on mount, never inside the Enable button's click handler — iOS Safari's "this
    // tap counts as real user activation" window for a permission prompt is lost the moment
    // an await happens first, even a fast one (see lib/push.ts's enablePush docstring).
    queryKey: ["vapid-public-key"],
    queryFn: fetchVapidPublicKey,
    retry: false,
  });

  const [thisDeviceEndpoint, setThisDeviceEndpoint] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<number, "sending" | "ok" | "error">>({});

  useEffect(() => {
    currentSubscriptionEndpoint().then(setThisDeviceEndpoint);
  }, []);

  const save = useMutation({
    mutationFn: (notifications: Settings["notifications"]) => saveSettings({ notifications }),
    onSuccess: (updated) => queryClient.setQueryData(["settings"], updated),
  });

  const enable = useMutation({
    mutationFn: async () => {
      if (!vapidKeyQuery.data) throw new Error("Push isn't configured on the server yet");
      await enablePush(vapidKeyQuery.data, guessDeviceLabel());
    },
    onSuccess: async () => {
      setStatus(null);
      queryClient.invalidateQueries({ queryKey: ["push-subscriptions"] });
      setThisDeviceEndpoint(await currentSubscriptionEndpoint());
    },
    onError: (err) => {
      setStatus(err instanceof PushPermissionDeniedError ? "Notification permission was denied." : "Couldn't enable notifications.");
    },
  });

  const disable = useMutation({
    mutationFn: () => disablePush(),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ["push-subscriptions"] });
      setThisDeviceEndpoint(await currentSubscriptionEndpoint());
    },
  });

  const sendTest = useMutation({
    mutationFn: (id: number) => sendTestPush(id),
    onMutate: (id) => setTestResult((r) => ({ ...r, [id]: "sending" })),
    onSuccess: (_void, id) => setTestResult((r) => ({ ...r, [id]: "ok" })),
    onError: (_err, id) => setTestResult((r) => ({ ...r, [id]: "error" })),
  });

  function toggleType(type: keyof Settings["notifications"]["types"], value: boolean) {
    const current = settingsQuery.data?.notifications;
    if (!current) return;
    const updated = { ...current, types: { ...current.types, [type]: value } };
    queryClient.setQueryData(["settings"], (s: Settings | undefined) => (s ? { ...s, notifications: updated } : s));
    save.mutate(updated);
  }

  function updateQuietHours(field: "quiet_hours_start" | "quiet_hours_end", value: string) {
    const current = settingsQuery.data?.notifications;
    if (!current) return;
    const updated = { ...current, [field]: value };
    queryClient.setQueryData(["settings"], (s: Settings | undefined) => (s ? { ...s, notifications: updated } : s));
    save.mutate(updated);
  }

  if (settingsQuery.isLoading || !settingsQuery.data) return null;
  const notifications = settingsQuery.data.notifications;
  const subscriptions = subscriptionsQuery.data ?? [];
  const subscribedOnThisDevice = thisDeviceEndpoint != null && subscriptions.some((s) => s.endpoint === thisDeviceEndpoint);

  return (
    <Card title="Notifications">
      <p className="mb-3 text-xs text-text-tertiary">
        Morning brief, illness/overtraining warnings, a Garmin-key-expiry countdown, sync-broken alerts, and a day-before
        reminder for a scheduled test or A race. iOS only allows push for the version installed to your home screen (iOS
        16.4+), and only after you tap a button — Settings pages can't ask on page load.
      </p>

      {!pushSupported() ? (
        <p className="text-sm text-text-tertiary">This browser doesn't support push notifications.</p>
      ) : looksLikeIosSafariNotInstalled() ? (
        <p className="text-sm text-text-secondary">
          Add Catch to your Home Screen first (Share → Add to Home Screen), then open it from there to enable notifications.
        </p>
      ) : !vapidKeyQuery.data ? (
        <p className="text-sm text-text-tertiary">{vapidKeyQuery.isError ? "Push isn't configured on the server yet." : "Loading…"}</p>
      ) : subscribedOnThisDevice ? (
        <div className="flex items-center gap-3">
          <span className="text-sm text-band-green">Enabled on this device</span>
          <button
            type="button"
            onClick={() => disable.mutate()}
            disabled={disable.isPending}
            className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50"
          >
            Disable
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => enable.mutate()}
            disabled={enable.isPending}
            className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            Enable notifications on this device
          </button>
          {status && <span className="text-xs text-band-red-text">{status}</span>}
        </div>
      )}

      {subscriptions.length > 0 && (
        <div className="mt-4 flex flex-col gap-2 border-t border-border pt-3">
          <p className="text-xs font-medium text-text-tertiary">Registered devices</p>
          {subscriptions.map((sub) => (
            <div key={sub.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="text-text-primary">
                {sub.label ?? "Unknown device"}
                <span className="ml-2 text-xs text-text-tertiary">last seen {formatRelativeTime(sub.last_seen_at)}</span>
              </span>
              <div className="flex items-center gap-2">
                {testResult[sub.id] === "ok" && <span className="text-xs text-band-green">Sent</span>}
                {testResult[sub.id] === "error" && <span className="text-xs text-band-red-text">Failed</span>}
                <button
                  type="button"
                  onClick={() => sendTest.mutate(sub.id)}
                  disabled={testResult[sub.id] === "sending"}
                  className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50"
                >
                  Send test
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-col gap-2 border-t border-border pt-3">
        <p className="text-xs font-medium text-text-tertiary">Types</p>
        {(Object.keys(TYPE_LABELS) as (keyof Settings["notifications"]["types"])[]).map((type) => (
          <label key={type} className="flex items-center gap-3 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={notifications.types[type]}
              onChange={(e) => toggleType(type, e.target.checked)}
              className="h-5 w-5 accent-accent"
            />
            {TYPE_LABELS[type]}
          </label>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-3 text-sm text-text-secondary">
        Quiet hours
        <input
          type="time"
          value={notifications.quiet_hours_start}
          onChange={(e) => updateQuietHours("quiet_hours_start", e.target.value)}
          className="min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
        />
        to
        <input
          type="time"
          value={notifications.quiet_hours_end}
          onChange={(e) => updateQuietHours("quiet_hours_end", e.target.value)}
          className="min-h-11 rounded-md border border-border bg-surface-2 px-2 text-text-primary"
        />
      </div>
    </Card>
  );
}
