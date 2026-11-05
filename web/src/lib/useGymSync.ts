import { useEffect, useState } from "react";
import { flushDirty, getSyncStatus, subscribeSyncStatus, type SyncStatus } from "./gymSync";
import { useOnlineStatus } from "./useOnlineStatus";

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
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    };
  }, []);

  return status;
}
