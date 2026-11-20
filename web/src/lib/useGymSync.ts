import { useEffect, useState } from "react";
import { flushDirty, getSyncStatus, subscribeSyncStatus, type SyncStatus } from "./gymSync";
import { useOnlineStatus } from "./useOnlineStatus";

const PENDING_RETRY_MS = 20_000;

/** Flushes the offline queue whenever the real online probe (never navigator.onLine) flips
 * to true, and exposes the current pending/syncing state for a subtle status indicator
 * (task Part A.1: "show sync state subtly"). */
export function useGymSync(): SyncStatus {
  const online = useOnlineStatus();
  const [status, setStatus] = useState<SyncStatus>(getSyncStatus());

  useEffect(() => subscribeSyncStatus(setStatus), []);

  useEffect(() => {
    if (online) void flushDirty();
  }, [online]);

  // Session 30: a set that couldn't be sent is retried on a timer too, not only on connectivity events. The phone can be online while
  // Catch's server is briefly unreachable (a deploy, a scale-to-zero cold start): no online/offline transition ever fires then, and the
  // queue would otherwise wait for the next app resume. The flush is idempotent, so a retry is always safe.
  const pending = status.pendingCount;
  useEffect(() => {
    if (pending <= 0) return;
    const id = setInterval(() => void flushDirty(), PENDING_RETRY_MS);
    return () => clearInterval(id);
  }, [pending]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void flushDirty();
    };
    document.addEventListener("visibilitychange", onVisible);
    // The browser's own "online" event — a real signal (unlike navigator.onLine's static
    // value) that connectivity just came back, fired independently of useOnlineStatus's own
    // debounced 15s-interval probe. Without this, a reconnect that happens to fall inside one
    // probe interval (the probe never having ticked while genuinely offline, so `online`
    // above never flips false->true to re-run the effect) would leave the queue stuck until
    // the next scheduled probe tick — a real gap for "never lose a set," not just a test-timing
    // quirk, so this isn't belt-and-suspenders, it's load-bearing.
    const onOnline = () => void flushDirty();
    window.addEventListener("online", onOnline);
    // The native shell's resume event (lib/native/useNativeShell.ts): a backgrounded webview may not fire visibilitychange reliably.
    window.addEventListener("catch:app-resumed", onOnline);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("catch:app-resumed", onOnline);
    };
  }, []);

  return status;
}
