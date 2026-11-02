import { useCallback, useEffect, useRef, useState } from "react";

// Session 8 shipped sw.js with an unconditional skipWaiting() on install and no update UI at
// all — a new build silently replaced the running one's fetch handler with no way for a user
// to know a reload would get them anything new. This hook drives the "New version available —
// tap to reload" toast (UpdateToast.tsx): it registers the worker, watches for one that's
// installed-but-waiting (the new activate-on-message design above means there's always
// something to find), and reloads once the user asks for it.
export function useServiceWorkerUpdate(): { updateAvailable: boolean; reload: () => void } {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const waitingWorker = useRef<ServiceWorker | null>(null);
  const reloadedOnce = useRef(false);
  // A *first-ever* install (no previous controller) also fires `controllerchange` once
  // `clients.claim()` runs — without this flag, a brand-new visit (or any visit after the user
  // clears site data) would reload itself once, unprompted, possibly mid-password on the login
  // screen. Only a reload *we* asked for (via SKIP_WAITING, below) should actually reload.
  const weRequestedSkipWaiting = useRef(false);

  const reload = useCallback(() => {
    weRequestedSkipWaiting.current = true;
    waitingWorker.current?.postMessage("SKIP_WAITING");
  }, []);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    const onNewWorker = (worker: ServiceWorker) => {
      waitingWorker.current = worker;
      setUpdateAvailable(true);
    };

    let registration: ServiceWorkerRegistration | null = null;

    navigator.serviceWorker
      // updateViaCache: 'none' — the worker script itself must never be served from the
      // browser's HTTP cache when checking for an update, matching the server's own
      // Cache-Control: no-cache on /sw.js (catch/main.py's _no_cache_headers_for).
      .register("/sw.js", { updateViaCache: "none" })
      .then((reg) => {
        registration = reg;
        // A worker can already be sitting in `waiting` from a previous visit to this tab (the
        // user never tapped reload last time) — only prompt if a controller already exists,
        // i.e. this isn't the very first install on a brand-new visit.
        if (reg.waiting && navigator.serviceWorker.controller) onNewWorker(reg.waiting);
        reg.addEventListener("updatefound", () => {
          const installing = reg.installing;
          if (!installing) return;
          installing.addEventListener("statechange", () => {
            if (installing.state === "installed" && navigator.serviceWorker.controller) {
              onNewWorker(installing);
            }
          });
        });
      })
      .catch(() => {
        // Dev server / HTTP-without-TLS / no SW support — offline caching and update prompts
        // just don't apply.
      });

    const onControllerChange = () => {
      if (!weRequestedSkipWaiting.current) return; // e.g. the very first install — not an update
      if (reloadedOnce.current) return; // guards against a reload loop
      reloadedOnce.current = true;
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);

    // An installed iOS PWA resumes from the background without ever navigating, so without
    // this it would never re-check for a new sw.js until the next cold launch from the
    // springboard icon — which could be days.
    const onVisible = () => {
      if (document.visibilityState === "visible") registration?.update().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return { updateAvailable, reload };
}
