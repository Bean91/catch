import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useAuth } from "../auth";
import { installExternalLinkHandler } from "./externalLinks";
import { isNative } from "./platform";
import { refreshNativePushToken, startNativePushListeners } from "./push";
import { persistQueries } from "./queryPersist";

export const APP_RESUMED_EVENT = "catch:app-resumed";

/** Everything the store apps need from the shell that the web build doesn't: splash, lifecycle, connectivity hints, the Android
 * back button, keyboard-aware scrolling, external links, and push listeners. A no-op in a browser. */
export function useNativeShell(): void {
  const queryClient = useQueryClient();
  const { status } = useAuth();

  // The splash stays up until the first auth decision, so the person never sees the login card flash before their session loads.
  useEffect(() => {
    if (!isNative() || status === "checking") return;
    void import("@capacitor/splash-screen").then(({ SplashScreen }) => SplashScreen.hide({ fadeOutDuration: 150 }));
  }, [status]);

  useEffect(() => {
    if (!isNative()) return;
    const disposers: (() => void)[] = [installExternalLinkHandler()];
    // Listening for a notification tap asks for no permission, and must be in place before sign-in so a tap that launched the
    // app is not lost; the deep-link hook holds the target until the session is ready.
    void startNativePushListeners();
    let cancelled = false;
    const keep = (p: Promise<{ remove: () => Promise<void> }>) =>
      void p.then((h) => {
        if (cancelled) void h.remove();
        else disposers.push(() => void h.remove());
      });

    void (async () => {
      const [{ App }, { Network }, { Keyboard }] = await Promise.all([import("@capacitor/app"), import("@capacitor/network"), import("@capacitor/keyboard")]);

      keep(
        App.addListener("appStateChange", async ({ isActive }) => {
          if (!status || status === "checking") return;
          const { getAuthClient } = await import("../supabase");
          const auth = await getAuthClient();
          if (!isActive) {
            // A backgrounded webview's timers are suspended; auth-js's refresh ticker must not fire half-asleep.
            await auth.stopAutoRefresh();
            return;
          }
          await auth.startAutoRefresh();
          await auth.getSession(); // refreshes an access token that expired while backgrounded
          window.dispatchEvent(new Event(APP_RESUMED_EVENT));
          // Foreground-only health sync: a no-op unless the person turned it on AND confirmed a first import.
          void import("./health").then((h) => h.incrementalSync()).catch(() => {});
          void queryClient.invalidateQueries({ queryKey: ["health-probe"] });
          void queryClient.invalidateQueries({ refetchType: "active" });
        }),
      );

      // A connectivity *hint*: it re-runs the real /api/health probe immediately; it never decides online-ness itself.
      keep(
        Network.addListener("networkStatusChange", (s) => {
          void queryClient.invalidateQueries({ queryKey: ["health-probe"] });
          if (s.connected) window.dispatchEvent(new Event("online"));
        }),
      );

      keep(
        App.addListener("backButton", ({ canGoBack }) => {
          const open = document.querySelector<HTMLElement>('[role="dialog"][data-state="open"], [role="alertdialog"]');
          if (open) {
            open.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            return;
          }
          if (canGoBack) window.history.back();
          else void App.exitApp();
        }),
      );

      // Native keyboard resizing shrinks the webview; keep the field being typed in on screen.
      keep(
        Keyboard.addListener("keyboardDidShow", () => {
          const el = document.activeElement as HTMLElement | null;
          if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) el.scrollIntoView({ block: "center", behavior: "smooth" });
        }),
      );
    })();

    return () => {
      cancelled = true;
      disposers.forEach((d) => d());
    };
    // status is read inside the appStateChange handler only to avoid acting before the first auth decision
  }, [queryClient, status === "checking"]); // eslint-disable-line react-hooks/exhaustive-deps

  // Restore + keep the read-screen cache for the signed-in person (the key is their account id, remembered by lib/session.ts).
  useEffect(() => {
    if (!isNative() || status !== "authed") return;
    let dispose: (() => void) | null = null;
    let live = true;
    const uid = localStorage.getItem("catch:uid") ?? "";
    void persistQueries(queryClient, uid).then((d) => (live ? (dispose = d) : d()));
    return () => {
      live = false;
      dispose?.();
    };
  }, [queryClient, status]);

  useEffect(() => {
    if (!isNative() || status !== "authed") return;
    void refreshNativePushToken("This device").catch(() => {});
    void import("./health").then((h) => h.incrementalSync()).catch(() => {});
  }, [status]);
}
