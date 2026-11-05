// IndexedDB-backed offline queue for the gym logger (PLAN.md's session 14 Part A.1: "the
// active workout lives in IndexedDB and syncs to the Pi when online; never lose a set if the
// connection drops or the app is closed"). Hand-rolled against the raw `indexedDB` API rather
// than a wrapper library — this app already avoids adding small dependencies a short module
// can replace (see DESIGN.md/CLAUDE.md's precedent for sw.js and the hand-rolled charts), and
// the actual API surface needed here is narrow (put/get/getAll by index).
//
// Every write (a new set, an edit, a delete) lands here *before* any network call is even
// attempted — gymSync.ts's flush is a separate, best-effort step that can fail and retry
// freely without ever risking the set itself.
import type { StrengthSetInput } from "./types";

const DB_NAME = "catch-gym";
const DB_VERSION = 1;
const SETS_STORE = "sets";

export interface LocalSet extends StrengthSetInput {
  sessionId: string;
  dirty: boolean;
  deleted: boolean;
  effectiveLoadKg: number | null;
  loadIsEstimated: boolean;
  loadNote?: string | null;
  isRepPr: boolean;
  isE1rmPr: boolean;
  exerciseName: string;
  muscularAu: number | null;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(SETS_STORE)) {
        const store = db.createObjectStore(SETS_STORE, { keyPath: "client_id" });
        store.createIndex("sessionId", "sessionId");
        store.createIndex("dirty", "dirty");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function tx<T>(storeName: string, mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(storeName, mode);
        const store = t.objectStore(storeName);
        const req = fn(store);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      }),
  );
}

function getAllByIndex<T>(storeName: string, indexName: string, value: unknown): Promise<T[]> {
  return openDb().then(
    (db) =>
      new Promise<T[]>((resolve, reject) => {
        const t = db.transaction(storeName, "readonly");
        const req = t.objectStore(storeName).index(indexName).getAll(value as IDBValidKey);
        req.onsuccess = () => resolve(req.result as T[]);
        req.onerror = () => reject(req.error);
      }),
  );
}

export async function putLocalSet(set: LocalSet): Promise<void> {
  await tx(SETS_STORE, "readwrite", (store) => store.put(set));
}

export async function getLocalSet(clientId: string): Promise<LocalSet | undefined> {
  return tx(SETS_STORE, "readonly", (store) => store.get(clientId));
}

export async function getSetsForSession(sessionId: string): Promise<LocalSet[]> {
  const rows = await getAllByIndex<LocalSet>(SETS_STORE, "sessionId", sessionId);
  return rows.filter((r) => !r.deleted).sort((a, b) => a.seq - b.seq);
}

export async function getAllLocalSets(): Promise<LocalSet[]> {
  return tx<LocalSet[]>(SETS_STORE, "readonly", (store) => store.getAll());
}

export async function markSetDeleted(clientId: string): Promise<void> {
  const existing = await getLocalSet(clientId);
  if (!existing) return;
  await putLocalSet({ ...existing, deleted: true, dirty: true });
}

export async function getDirtySets(): Promise<LocalSet[]> {
  const all = await getAllLocalSets();
  return all.filter((s) => s.dirty);
}

export async function markSynced(clientIds: string[]): Promise<void> {
  for (const id of clientIds) {
    const existing = await getLocalSet(id);
    if (existing) await putLocalSet({ ...existing, dirty: false });
  }
}

/** Today's existing session id (the local calendar day a set was created on), if one has
 * already been started — appending to it, rather than starting a new one, is what keeps
 * "resume today's workout" and the coach's log_strength tool consistent with each other. */
export async function getTodaysSessionId(): Promise<string | null> {
  const all = await getAllLocalSets();
  const today = new Date().toDateString();
  const todays = all.filter((s) => !s.deleted && new Date(s.created_at ?? Date.now()).toDateString() === today);
  if (todays.length === 0) return null;
  todays.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  return todays[0].sessionId;
}
