import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchPushSubscriptions, fetchSettings, fetchVapidPublicKey, saveSettings, sendTestPush } from "../../lib/api";
import { formatRelativeTime } from "../../lib/format";
import { currentSubscriptionEndpoint, disablePush, enablePush, isInstalledPwa, pushSupported, PushPermissionDeniedError } from "../../lib/push";
import { disableNativePush, enableNativePush, nativePushPermission, nativePushTokenHint } from "../../lib/native/push";
import { isNative } from "../../lib/native/platform";
import type { Settings } from "../../lib/types";
import { Card } from "../ui/Card";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

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
  // The store app registers with APNs/FCM instead of Web Push (session 30); everything below the device list is shared.
  const native = isNative();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const subscriptionsQuery = useQuery({ queryKey: ["push-subscriptions"], queryFn: fetchPushSubscriptions });
  const vapidKeyQuery = useQuery({
    // Fetched on mount, never inside the Enable button's click handler — iOS Safari's "this
    // tap counts as real user activation" window for a permission prompt is lost the moment
    // an await happens first, even a fast one (see lib/push.ts's enablePush docstring).
    queryKey: ["vapid-public-key"],
    queryFn: fetchVapidPublicKey,
    retry: false,
    enabled: !native,
  });

  const [thisDeviceEndpoint, setThisDeviceEndpoint] = useState<string | null>(null);
  const [nativeHint, setNativeHint] = useState<string | null>(null);
  const [nativePermission, setNativePermission] = useState<"granted" | "denied" | "prompt" | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<number, "sending" | "ok" | "error">>({});

  useEffect(() => {
    if (native) {
      void nativePushTokenHint().then(setNativeHint);
      void nativePushPermission().then(setNativePermission);
      return;
    }
    currentSubscriptionEndpoint().then(setThisDeviceEndpoint);
  }, [native]);

  const save = useMutation({
    mutationFn: (notifications: Settings["notifications"]) => saveSettings({ notifications }),
    onSuccess: (updated) => queryClient.setQueryData(["settings"], updated),
  });

  const enable = useMutation({
    mutationFn: async () => {
      if (native) return enableNativePush(guessDeviceLabel());
      if (!vapidKeyQuery.data) throw new Error("Push isn't configured on the server yet");
      await enablePush(vapidKeyQuery.data, guessDeviceLabel());
    },
    onSuccess: async () => {
      setStatus(null);
      queryClient.invalidateQueries({ queryKey: ["push-subscriptions"] });
      if (native) {
        setNativeHint(await nativePushTokenHint());
        setNativePermission(await nativePushPermission());
        return;
      }
      setThisDeviceEndpoint(await currentSubscriptionEndpoint());
    },
    onError: (err) => {
      if (native) void nativePushPermission().then(setNativePermission);
      setStatus(err instanceof PushPermissionDeniedError ? "Notification permission was denied." : "Couldn't enable notifications.");
    },
  });

  const disable = useMutation({
    mutationFn: () => (native ? disableNativePush() : disablePush()),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ["push-subscriptions"] });
      if (native) {
        setNativeHint(await nativePushTokenHint());
        return;
      }
      setThisDeviceEndpoint(await currentSubscriptionEndpoint());
    },
  });

  const sendTest = useMutation({
    mutationFn: (id: number) => sendTestPush(id, subscriptions.find((x) => x.id === id && x.kind === "native") ? "native" : "web"),
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
  const subscribedOnThisDevice = native
    ? nativeHint != null && subscriptions.some((s) => s.kind === "native" && s.token_hint === nativeHint)
    : thisDeviceEndpoint != null && subscriptions.some((s) => s.endpoint === thisDeviceEndpoint);

  return (
    <Card title="Notifications">
      <p className="mb-3 text-xs text-text-tertiary">
        Morning brief, illness/overtraining warnings, a Garmin-key-expiry countdown, sync-broken alerts, and a day-before
        reminder for a scheduled test or A race. {native
          ? "Your phone asks for permission only when you tap the button below."
          : "iOS only allows push for the version installed to your home screen (iOS 16.4+), and only after you tap a button — Settings pages can't ask on page load."}
      </p>

      {native ? (
        nativePermission === "denied" && !subscribedOnThisDevice ? (
          <p className="text-sm text-text-secondary">
            Notifications are turned off for Catch on this phone. Turn them on in your phone's Settings → Catch → Notifications, then come back here.
          </p>
        ) : subscribedOnThisDevice ? (
          <div className="flex items-center gap-3">
            <span className="text-sm text-band-green">Enabled on this device</span>
            <button type="button" onClick={() => disable.mutate()} disabled={disable.isPending} className={buttonClass("secondary", "md")}>
              Disable
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => enable.mutate()} disabled={enable.isPending} className={buttonClass("primary", "md")}>
              Enable notifications on this device
            </button>
            {status && <span className="text-xs text-band-red-text">{status}</span>}
          </div>
        )
      ) : !pushSupported() ? (
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
            className={buttonClass("secondary", "md")}
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
            className={buttonClass("primary", "md")}
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
                  className={buttonClass("secondary", "sm")}
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
          className={controlSkin + " w-auto min-h-11"}
        />
        to
        <input
          type="time"
          value={notifications.quiet_hours_end}
          onChange={(e) => updateQuietHours("quiet_hours_end", e.target.value)}
          className={controlSkin + " w-auto min-h-11"}
        />
      </div>
    </Card>
  );
}
