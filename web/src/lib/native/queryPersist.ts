// Session 30 (docs/mobile/offline.md): the PWA's service worker answers a GET from its cache when the network is gone; a store
// app has no service worker, so the read screens (Today, calendar, gym library…) would be empty on a cold start in a basement gym.
// This persists a short allow-list of query results to IndexedDB and restores them at launch. Never holds anything from the
// credential/privacy/AI areas; wiped on sign-out and user switch (lib/session.ts → SESSION_ENDED_EVENT).
import type { Query, QueryClient } from "@tanstack/react-query";
import { isNative } from "./platform";

const DB = "catch-query-cache";
const STORE = "kv";
const KEY = "snapshot";
const MAX_AGE_MS = 7 * 24 * 3600_000;
const SCHEMA = 1;

// Keys are the queryKey[0] strings the read screens use; anything not listed is never written.
const ALLOWED = new Set(["today", "today-checkin", "workouts", "workout", "calendar", "plan-week", "upcoming-events", "gym-exercises", "gym-templates", "gym-gyms", "gym-stations", "gym-body", "exercises", "muscle-readiness", "settings", "series", "sync-status", "pieces", "tests", "pbs"]);

interface Snapshot {
  v: number;
  at: number;
  uid: string;
  queries: { key: unknown[]; data: unknown; at: number }[];
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function read(): Promise<Snapshot | null> {
  const db = await open();
  return new Promise((resolve) => {
    const r = db.transaction(STORE).objectStore(STORE).get(KEY);
    r.onsuccess = () => resolve((r.result as Snapshot | undefined) ?? null);
    r.onerror = () => resolve(null);
  });
}

async function write(snap: Snapshot | null): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve) => {
    const tx = db.transaction(STORE, "readwrite");
    if (snap) tx.objectStore(STORE).put(snap, KEY);
    else tx.objectStore(STORE).delete(KEY);
    tx.oncomplete = tx.onerror = tx.onabort = () => resolve();
  });
}

export function isPersistable(q: Pick<Query, "queryKey" | "state">): boolean {
  return typeof q.queryKey[0] === "string" && ALLOWED.has(q.queryKey[0]) && q.state.status === "success" && q.state.data !== undefined;
}

export async function clearPersistedQueries(): Promise<void> {
  try {
    await write(null);
  } catch {
    /* storage unavailable */
  }
}

/** Restores the snapshot for `uid` into the client, then keeps it current. Returns a disposer. */
export async function persistQueries(client: QueryClient, uid: string): Promise<() => void> {
  if (!isNative()) return () => {};
  try {
    void navigator.storage?.persist?.(); // ask the OS not to evict the webview's storage under pressure
    const snap = await read();
    if (snap && snap.v === SCHEMA && snap.uid === uid && Date.now() - snap.at < MAX_AGE_MS) {
      for (const q of snap.queries) client.setQueryData(q.key, q.data, { updatedAt: q.at });
    } else if (snap) {
      await write(null); // someone else's, stale or an old shape
    }
  } catch {
    /* a cold cache is only slower */
  }
  let timer: ReturnType<typeof setTimeout> | null = null;
  const save = () => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      const queries = client
        .getQueryCache()
        .getAll()
        .filter(isPersistable)
        .map((q) => ({ key: [...q.queryKey], data: q.state.data, at: q.state.dataUpdatedAt }));
      void write({ v: SCHEMA, at: Date.now(), uid, queries }).catch(() => {});
    }, 2_000);
  };
  const unsubscribe = client.getQueryCache().subscribe(save);
  return () => {
    unsubscribe();
    if (timer) clearTimeout(timer);
  };
}
