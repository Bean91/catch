import { useCallback, useEffect, useRef, useState } from "react";
import { isNativeBuild } from "./native/platform";

const POLL_INTERVAL_MS = 60_000;
const PRELOAD_RELOAD_KEY = "catch:preload-reload";

interface VersionInfo {
  build: string;
  commit: string;
}

async function fetchVersion(): Promise<VersionInfo | null> {
  try {
    const res = await fetch("/version.json", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as VersionInfo;
  } catch {
    return null;
  }
}

// Update detection is a plain version.json poll, deliberately independent of the service
// worker's own install/waiting/controllerchange lifecycle (registered below purely for its
// caching behavior — see vite.config.ts's NEVER_CACHE comment). A prior design drove the toast
// off `registration.waiting`, which depends on exactly when WebKit decides to notice a changed
// sw.js and run it through install — a real user report ("my iPhone PWA keeps running an old
// build") despite that code looking correct is the reason this doesn't trust that timing as the
// only signal: a version compare on an interval/visibilitychange/online event works the same
// regardless of what the service worker's state machine is doing.
export function useServiceWorkerUpdate(): { updateAvailable: boolean; reload: () => void } {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const reloadedOnce = useRef(false);

  const reload = useCallback(() => {
    if (reloadedOnce.current) return;
    reloadedOnce.current = true;
    window.location.reload();
  }, []);

  useEffect(() => {
    // A store-installed app is replaced by the store, not by a new bundle: no service worker, no version.json poll.
    if (isNativeBuild) return;
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).catch(() => {
        // Dev server / no SW support — offline caching just doesn't apply; update detection
        // below works independently of this.
      });
    }

    // version.json is a plain static file, unrelated to the ?mock= API switch — it exists
    // (and should be polled) under ?mock=1 too; only the dev server (no build, no writeBundle)
    // lacks it, and fetchVersion() already no-ops gracefully on that 404.
    const poll = () => {
      fetchVersion().then((info) => {
        if (info && info.build !== __BUILD_ID__) setUpdateAvailable(true);
      });
    };
    poll();

    const interval = setInterval(poll, POLL_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", poll);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", poll);
    };
  }, []);

  useEffect(() => {
    // Vite's lazily-imported route chunks are content-hashed, and deploy.sh rsyncs with
    // --delete — an old hash a still-open tab references can 404 once a new build has shipped
    // over it. sessionStorage (not the ref above) guards this specific reload: it must survive
    // the reload itself to avoid a loop if the chunk is 404ing for some other reason (e.g.
    // genuinely offline), at the cost of only auto-recovering once per tab session — a second
    // deploy in the same long-lived tab relies on the version.json poll above catching it first.
    const onPreloadError = (e: Event) => {
      // Session 35: only a chunk that genuinely failed to load is a reason to reload. Vite reports any rejection from inside a
      // preload-wrapped import here — on the native app an unreachable API surfaced this way and reloaded the app mid sign-in —
      // and a native build ships every chunk inside the app, so a stale deploy can't happen there at all.
      if (isNativeBuild) return;
      const message = String((e as Event & { payload?: unknown }).payload ?? "");
      if (!/dynamically imported module|Importing a module script failed|Unable to preload CSS|error loading dynamically imported module/i.test(message)) return;
      try {
        if (sessionStorage.getItem(PRELOAD_RELOAD_KEY)) return;
        sessionStorage.setItem(PRELOAD_RELOAD_KEY, "1");
      } catch {
        // Private browsing / blocked storage — fall through and reload anyway, once, per the
        // in-memory guard in reload() above.
      }
      reload();
    };
    window.addEventListener("vite:preloadError", onPreloadError);
    return () => window.removeEventListener("vite:preloadError", onPreloadError);
  }, [reload]);

  return { updateAvailable, reload };
}
