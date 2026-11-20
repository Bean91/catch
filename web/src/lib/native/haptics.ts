// Session 30 (DESIGN.md "Native apps"): small, rare confirmations — never decoration. No-ops on the web, when the person has
// asked for reduced motion, or when they've switched haptics off in Settings.
import { isNative } from "./platform";

const KEY = "catch:haptics";

export function hapticsEnabled(): boolean {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function setHapticsEnabled(on: boolean): void {
  try {
    if (on) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, "off");
  } catch {
    /* ignore */
  }
}

export type HapticKind = "light" | "medium" | "success" | "warning" | "selection";

function allowed(): boolean {
  if (!isNative() || !hapticsEnabled()) return false;
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function haptic(kind: HapticKind): void {
  if (!allowed()) return;
  void import("@capacitor/haptics")
    .then(({ Haptics, ImpactStyle, NotificationType }) => {
      switch (kind) {
        case "light":
          return Haptics.impact({ style: ImpactStyle.Light });
        case "medium":
          return Haptics.impact({ style: ImpactStyle.Medium });
        case "success":
          return Haptics.notification({ type: NotificationType.Success });
        case "warning":
          return Haptics.notification({ type: NotificationType.Warning });
        case "selection":
          return Haptics.selectionStart().then(() => Haptics.selectionChanged()).then(() => Haptics.selectionEnd());
      }
    })
    .catch(() => {});
}
