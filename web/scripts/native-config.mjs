#!/usr/bin/env node
// Session 30 (docs/mobile/README.md). Writes capacitor.config.json for one environment:
//   CATCH_NATIVE_ENV=development|staging|production  (default production)
// The id suffix lets a development or staging build install beside the store build. Only public values go in here —
// nothing in this file or in the web bundle is a credential.
//
// Why a generator instead of capacitor.config.ts/.js: the CLI transpiles a .ts config with the `typescript` package (this
// repo's TypeScript 7 no longer exposes that API) and `require()`s a .js one (this package is "type": "module").
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const ENVS = ["development", "staging", "production"];
export const BASE_ID = "com.openoted.catch";

export function nativeConfig(env = process.env.CATCH_NATIVE_ENV ?? "production") {
  if (!ENVS.includes(env)) throw new Error(`CATCH_NATIVE_ENV must be one of ${ENVS.join(", ")} (got ${env})`);
  const suffix = env === "production" ? "" : env === "development" ? ".dev" : ".staging";
  return {
    appId: `${BASE_ID}${suffix}`,
    appName: env === "production" ? "Catch" : env === "development" ? "Catch Dev" : "Catch Staging",
    webDir: "dist-native",
    server: {
      // https on Android so the webview's origin (https://localhost) is a secure context and matches the CORS allowlist;
      // iOS keeps capacitor://localhost.
      androidScheme: "https",
      // Only a development build may talk to a local http API (localhost through `adb reverse`).
      cleartext: env === "development",
    },
    ios: {
      // The web layer owns the safe-area insets (env(safe-area-inset-*) in AppShell/BottomNav), exactly as in the PWA.
      contentInset: "never",
      scrollEnabled: true,
      backgroundColor: "#0D0F11",
    },
    android: {
      backgroundColor: "#0D0F11",
      allowMixedContent: false,
      webContentsDebuggingEnabled: env !== "production",
    },
    plugins: {
      SplashScreen: { launchAutoHide: false, backgroundColor: "#0D0F11", showSpinner: false },
      Keyboard: { resize: "native", resizeOnFullScreen: true },
      StatusBar: { overlaysWebView: true },
      PushNotifications: { presentationOptions: ["badge", "sound", "alert"] },
    },
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = join(dirname(fileURLToPath(import.meta.url)), "..", "capacitor.config.json");
  const cfg = nativeConfig();
  writeFileSync(out, JSON.stringify(cfg, null, 2) + "\n");
  console.log(`native-config: ${cfg.appId} (${process.env.CATCH_NATIVE_ENV ?? "production"}) -> capacitor.config.json`);
}
