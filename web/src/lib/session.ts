import { isPublic } from "./deployment";

export const SESSION_ENDED_EVENT = "catch:session-ended";
const UID_KEY = "catch:uid";

async function deleteApiCaches(): Promise<void> {
  // sw.js keeps every GET /api/* response (network first, cache as the offline fallback) keyed by URL — not by user.
  if (!("caches" in window)) return;
  const keys = await caches.keys();
  await Promise.all(keys.filter((k) => k.startsWith("catch-api-")).map((k) => caches.delete(k)));
}

function deleteGymQueue(): Promise<void> {
  // The offline gym logger's queue of unsynced sets (lib/gymDb.ts) — flushing user A's sets into user B's account
  // after a sign-in on a shared device is exactly what this prevents.
  return new Promise((resolve) => {
    try {
      const req = indexedDB.deleteDatabase("catch-gym");
      req.onsuccess = req.onerror = req.onblocked = () => resolve();
    } catch {
      resolve();
    }
  });
}

/** Everything this browser holds about the signed-in person, except the Supabase session itself (auth-js clears that). */
export async function clearLocalUserState(): Promise<void> {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("catch:") && key !== "catch:theme") localStorage.removeItem(key);
    }
    sessionStorage.clear();
  } catch {
    // blocked storage: nothing to clear
  }
  await Promise.all([deleteApiCaches(), deleteGymQueue()]);
  window.dispatchEvent(new Event(SESSION_ENDED_EVENT)); // main.tsx clears the TanStack Query cache
}

/** Called on every sign-in: if a different person signed in on this browser, the previous person's data goes first. */
export async function rememberUser(userId: string): Promise<void> {
  if (!isPublic) return;
  let previous: string | null = null;
  try {
    previous = localStorage.getItem(UID_KEY);
  } catch {
    /* ignore */
  }
  if (previous && previous !== userId) await clearLocalUserState();
  try {
    localStorage.setItem(UID_KEY, userId);
  } catch {
    /* ignore */
  }
}
