// Session 30 (docs/mobile/push.md): APNs (iOS) / FCM (Android) registration through @capacitor/push-notifications. The web
// path (lib/push.ts, Web Push + VAPID) is untouched; NotificationsCard picks one by isNative().
//
// Rules this file keeps: the OS permission prompt is requested ONLY from `enableNativePush` (a button tap), never at launch;
// the token is sent to the server only after the permission is granted; the device's own token is never shown in full.
import { subscribeNativePush, unsubscribeNativePush } from "../api";
import { PushPermissionDeniedError } from "../push";
import { emitDeepLink } from "./deepLinkBus";
import { resolveNotificationPath } from "./deepLinkTargets";
import { nativePlatform } from "./platform";

const ENABLED_KEY = "catch.push.enabled";
const TOKEN_KEY = "catch.push.token";
export const PUSH_RECEIVED_EVENT = "catch:push-received";

export interface ForegroundPush {
  title: string;
  body: string;
  url: string;
}

function platform(): "apns" | "fcm" {
  return nativePlatform() === "ios" ? "apns" : "fcm";
}

// APNs distinguishes a development-signed build (sandbox) from a TestFlight/App Store one (production). JS cannot read the
// provisioning profile, so this is a hint from the build mode; the server retries the other host on BadDeviceToken.
function environment(): "sandbox" | "production" {
  return import.meta.env.MODE === "native-development" ? "sandbox" : "production";
}

async function plugins() {
  const [{ PushNotifications }, { Preferences }, { App }] = await Promise.all([
    import("@capacitor/push-notifications"),
    import("@capacitor/preferences"),
    import("@capacitor/app"),
  ]);
  return { PushNotifications, Preferences, App };
}

let listening = false;

/** Notification taps and foreground deliveries. Registering listeners does not ask for any permission. */
export async function startNativePushListeners(): Promise<void> {
  if (listening) return;
  listening = true;
  const { PushNotifications } = await plugins();
  await PushNotifications.addListener("pushNotificationActionPerformed", (action) => {
    emitDeepLink(resolveNotificationPath((action.notification.data as { url?: unknown } | undefined)?.url));
  });
  await PushNotifications.addListener("pushNotificationReceived", (n) => {
    const data = (n.data ?? {}) as { url?: unknown };
    const detail: ForegroundPush = { title: n.title ?? "Catch", body: n.body ?? "", url: typeof data.url === "string" ? data.url : "/" };
    window.dispatchEvent(new CustomEvent(PUSH_RECEIVED_EVENT, { detail }));
  });
}

async function registerAndGetToken(): Promise<string> {
  const { PushNotifications } = await plugins();
  return new Promise<string>((resolve, reject) => {
    const cleanup: Promise<{ remove: () => Promise<void> }>[] = [];
    const done = () => void Promise.all(cleanup).then((hs) => hs.forEach((h) => void h.remove()));
    const timer = setTimeout(() => {
      done();
      reject(new Error("Push registration timed out"));
    }, 15_000);
    cleanup.push(
      PushNotifications.addListener("registration", (t) => {
        clearTimeout(timer);
        done();
        resolve(t.value);
      }),
      PushNotifications.addListener("registrationError", (e) => {
        clearTimeout(timer);
        done();
        reject(new Error(e.error));
      }),
    );
    void PushNotifications.register();
  });
}

async function sendToServer(token: string, label: string): Promise<void> {
  const { App, Preferences } = await plugins();
  const info = await App.getInfo();
  await subscribeNativePush({ platform: platform(), token, environment: environment(), app_id: info.id, label });
  await Preferences.set({ key: TOKEN_KEY, value: token });
}

export async function nativePushPermission(): Promise<"granted" | "denied" | "prompt"> {
  const { PushNotifications } = await plugins();
  const p = await PushNotifications.checkPermissions();
  return p.receive === "granted" ? "granted" : p.receive === "denied" ? "denied" : "prompt";
}

/** Called from the Enable button's tap handler. */
export async function enableNativePush(label: string): Promise<void> {
  const { PushNotifications, Preferences } = await plugins();
  let state = (await PushNotifications.checkPermissions()).receive;
  if (state !== "granted") state = (await PushNotifications.requestPermissions()).receive;
  if (state !== "granted") throw new PushPermissionDeniedError(state);
  await startNativePushListeners();
  await sendToServer(await registerAndGetToken(), label);
  await Preferences.set({ key: ENABLED_KEY, value: "1" });
}

export async function disableNativePush(): Promise<void> {
  const { PushNotifications, Preferences } = await plugins();
  const { value: token } = await Preferences.get({ key: TOKEN_KEY });
  if (token) await unsubscribeNativePush(platform(), token);
  await PushNotifications.unregister().catch(() => {});
  await Preferences.remove({ key: ENABLED_KEY });
  await Preferences.remove({ key: TOKEN_KEY });
}

/** This device's token hint (last characters), to find its own row in the registered-devices list. */
export async function nativePushTokenHint(): Promise<string | null> {
  const { Preferences } = await plugins();
  const { value } = await Preferences.get({ key: TOKEN_KEY });
  return value ? value.slice(-8) : null;
}

/** On launch/resume: if the person enabled notifications earlier and the OS still allows them, re-register so a rotated token
 * reaches the server. Never prompts. */
export async function refreshNativePushToken(label: string): Promise<void> {
  const { Preferences } = await plugins();
  const { value } = await Preferences.get({ key: ENABLED_KEY });
  if (!value) return;
  if ((await nativePushPermission()) !== "granted") return;
  const token = await registerAndGetToken();
  const { value: known } = await Preferences.get({ key: TOKEN_KEY });
  if (token !== known) await sendToServer(token, label);
}

/** Sign-out: stop this device receiving the account's notifications before the session goes away. Best effort — the server also
 * moves a token to whichever account registers it next. */
export async function releaseNativePush(): Promise<void> {
  try {
    await disableNativePush();
  } catch {
    /* offline or already signed out */
  }
}
