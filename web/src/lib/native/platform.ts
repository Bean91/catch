// Session 30 (docs/mobile/README.md): which shell this bundle runs in. `isNativeBuild` is a build-time literal (a
// `--mode native-<env>` build), so the web bundle drops every native-only branch; `isNative()` also asks Capacitor, so a
// native bundle opened in a plain browser (a dev server, a Playwright page) behaves as the web app and no plugin is called.
import { Capacitor } from "@capacitor/core";

export const isNativeBuild = import.meta.env.VITE_CATCH_NATIVE === "1";

export function isNative(): boolean {
  return isNativeBuild && Capacitor.isNativePlatform();
}

export type NativePlatform = "ios" | "android" | "web";

export function nativePlatform(): NativePlatform {
  if (!isNative()) return "web";
  return Capacitor.getPlatform() === "ios" ? "ios" : "android";
}
