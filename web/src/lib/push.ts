import { subscribePush, unsubscribePush } from "./api";

// iOS only allows push for the PWA installed to the home screen (iOS 16.4+), never a plain
// Safari tab — this is the only reliable way to tell the two apart (no official API for it).
export function isInstalledPwa(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true;
}

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function base64UrlToUint8Array(base64Url: string): Uint8Array<ArrayBuffer> {
  const padded = base64Url + "=".repeat((4 - (base64Url.length % 4)) % 4);
  const base64 = padded.replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i);
  return output;
}

export class PushPermissionDeniedError extends Error {}

/** Must be called synchronously from a user tap (a click handler), with
 * `Notification.requestPermission()` the very first thing it does — iOS Safari's "user
 * activation" window for a permission prompt is lost the moment an `await` happens first
 * (even a fast one, like fetching the VAPID key), so that key is fetched separately, ahead of
 * time, on mount — see components/settings/NotificationsCard.tsx. */
export async function enablePush(vapidPublicKey: string, label: string): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new PushPermissionDeniedError(permission);

  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64UrlToUint8Array(vapidPublicKey),
  });
  const json = subscription.toJSON();
  await subscribePush({
    endpoint: json.endpoint!,
    keys: { p256dh: json.keys!.p256dh, auth: json.keys!.auth },
    label,
    user_agent: navigator.userAgent,
  });
}

export async function disablePush(): Promise<void> {
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (subscription) {
    await unsubscribePush(subscription.endpoint);
    await subscription.unsubscribe();
  }
}

export async function currentSubscriptionEndpoint(): Promise<string | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration) return null;
  const subscription = await registration.pushManager.getSubscription();
  return subscription?.endpoint ?? null;
}
