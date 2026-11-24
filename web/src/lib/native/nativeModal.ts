// Session 38: which dialogs are open, for the iOS app's native tab bar (lib/native/tabBar.ts). Its own small module so the dialog
// primitives (components/ui/Sheet.tsx) can mount the marker without importing the router, the theme or the native shell.
import { Capacitor } from "@capacitor/core";
import { useEffect, useSyncExternalStore } from "react";
import { nativePlatform } from "./platform";

/** True only in the iOS app, and only if its native shell has the plugin (an older shell falls back to the web tab bar). */
export function nativeTabBarAvailable(): boolean {
  return nativePlatform() === "ios" && Capacitor.isPluginAvailable("NativeTabBar");
}

// ---- Open dialogs hide the bar ---------------------------------------------------------------------------------------------
// A native view always sits above the web view, so a bottom sheet would slide up underneath the bar. iOS presents sheets over
// the tab bar; here the bar steps aside while any dialog is open (and the safe area it adds goes with it).

let openModals = 0;
const modalListeners = new Set<() => void>();
const emitModals = () => modalListeners.forEach((l) => l());

function subscribeModals(listener: () => void): () => void {
  modalListeners.add(listener);
  return () => modalListeners.delete(listener);
}

/** Mounted inside every dialog's content (Radix mounts the content only while open). A no-op outside the iOS app. */
export function NativeModalMarker(): null {
  useEffect(() => {
    if (!nativeTabBarAvailable()) return;
    openModals += 1;
    emitModals();
    return () => {
      openModals -= 1;
      emitModals();
    };
  }, []);
  return null;
}

export function useAnyModalOpen(): boolean {
  return useSyncExternalStore(subscribeModals, () => openModals > 0);
}
