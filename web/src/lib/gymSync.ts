// Flushes the IndexedDB offline queue (gymDb.ts) to the Pi — best-effort, triggered by
// useOnlineStatus going true (never navigator.onLine — see that hook's own docstring) and
// right after every local write, but never required for a write to "succeed": every set is
// already durable in IndexedDB the instant it's logged, with or without a network path.
import { authedFetch } from "./authedFetch";
import { computeEffectiveLoad } from "./equipment";
import * as gymDb from "./gymDb";
import { isMock } from "./api";
import type { GymStation, StrengthSetInput, StrengthSetRow } from "./types";

type Listener = (status: SyncStatus) => void;

export interface SyncStatus {
  pendingCount: number;
  syncing: boolean;
  lastError: string | null;
}

let status: SyncStatus = { pendingCount: 0, syncing: false, lastError: null };
const listeners = new Set<Listener>();

function emit() {
  for (const l of listeners) l(status);
}

function setStatus(patch: Partial<SyncStatus>) {
  status = { ...status, ...patch };
  emit();
}

export function subscribeSyncStatus(listener: Listener): () => void {
  listeners.add(listener);
  listener(status);
  return () => listeners.delete(listener);
}

export function getSyncStatus(): SyncStatus {
  return status;
}

async function refreshPendingCount() {
  const dirty = await gymDb.getDirtySets();
  setStatus({ pendingCount: dirty.length });
}

/** Writes a set to IndexedDB immediately, computing a local effective-load preview with the
 * TS equipment-math port so the UI never shows a blank number while offline — then tries a
 * background flush. Never throws on a network failure; the caller doesn't wait for it. */
export async function logSetLocally(
  sessionId: string,
  input: StrengthSetInput,
  context: { exerciseName: string; bodyweightKg: number | null; stationConfig: GymStation["config"] | null },
): Promise<gymDb.LocalSet> {
  const bilateral = !input.side;
  const { effectiveLoadKg, isEstimated, note } = computeEffectiveLoad({
    equipmentType: input.equipment_type,
    loadKg: input.load_kg ?? null,
    barWeightKg: input.bar_weight_kg ?? null,
    pulleyMultiplier: input.pulley_multiplier ?? null,
    addedWeightKg: input.added_weight_kg ?? null,
    assistanceKg: input.assistance_kg ?? null,
    bilateral,
    bandTag: input.band_tag ?? null,
    stationConfig: context.stationConfig ?? null,
    bodyweightKg: context.bodyweightKg,
  });

  const local: gymDb.LocalSet = {
    ...input,
    created_at: input.created_at ?? new Date().toISOString(),
    sessionId,
    dirty: true,
    deleted: false,
    effectiveLoadKg,
    loadIsEstimated: isEstimated,
    loadNote: note ?? null,
    isRepPr: false, // resolved once the server confirms — PR detection needs full history.
    isE1rmPr: false,
    exerciseName: context.exerciseName,
    muscularAu: null,
  };
  await gymDb.putLocalSet(local);
  await refreshPendingCount();
  void flushDirty();
  return local;
}

export async function deleteSetLocally(clientId: string): Promise<void> {
  await gymDb.markSetDeleted(clientId);
  await refreshPendingCount();
  void flushDirty();
}

let flushing = false;

/** Idempotent on the server (upsert by client_id — CLAUDE.md's upsert rule, generalized), so
 * calling this redundantly from several triggers (every local write, the online-status
 * effect, a visibility change) is always safe to overlap or retry. */
export async function flushDirty(): Promise<void> {
  if (isMock || flushing) return;
  const dirty = await gymDb.getDirtySets();
  if (dirty.length === 0) return;

  flushing = true;
  setStatus({ syncing: true, lastError: null });
  try {
    const bySession = new Map<string, gymDb.LocalSet[]>();
    for (const s of dirty) {
      if (!bySession.has(s.sessionId)) bySession.set(s.sessionId, []);
      bySession.get(s.sessionId)!.push(s);
    }
    for (const [sessionId, sets] of bySession) {
      const active = sets.filter((s) => !s.deleted);
      const deletedIds = sets.filter((s) => s.deleted).map((s) => s.client_id);
      const res = await authedFetch("/api/gym/sessions/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_session_id: sessionId,
          sets: active.map(stripLocalFields),
          deleted_client_ids: deletedIds,
        }),
      });
      if (!res.ok) throw new Error(`sync failed: ${res.status}`);
      const body: { sets: StrengthSetRow[] } = await res.json();
      const confirmed = new Map(body.sets.map((s) => [s.client_id, s]));
      for (const s of active) {
        const result = confirmed.get(s.client_id);
        if (result) {
          await gymDb.putLocalSet({
            ...s,
            dirty: false,
            effectiveLoadKg: result.effective_load_kg,
            loadIsEstimated: result.load_is_estimated,
            loadNote: result.load_note ?? null,
            isRepPr: result.is_rep_pr,
            isE1rmPr: result.is_e1rm_pr,
            muscularAu: result.muscular_au,
          });
        }
      }
      await gymDb.markSynced(deletedIds);
    }
    setStatus({ lastError: null });
  } catch (err) {
    setStatus({ lastError: err instanceof Error ? err.message : "Sync failed" });
  } finally {
    flushing = false;
    setStatus({ syncing: false });
    await refreshPendingCount();
  }
}

function stripLocalFields(s: gymDb.LocalSet): StrengthSetInput {
  const { sessionId, dirty, deleted, effectiveLoadKg, loadIsEstimated, loadNote, isRepPr, isE1rmPr, exerciseName, muscularAu, ...rest } = s;
  void sessionId, dirty, deleted, effectiveLoadKg, loadIsEstimated, loadNote, isRepPr, isE1rmPr, exerciseName, muscularAu;
  return rest;
}

// No bespoke IndexedDB mirror for the exercise library/gyms/templates/readiness: every GET
// under /api/* already gets network-first-with-cache-fallback from the service worker itself
// (vite.config.ts's serviceWorkerPlugin) — the same generic mechanism Today/Workouts rely on
// for offline viewing. A cold start that's never been online has nothing to show either way
// (no sets to log against an exercise library it's never seen); opening the Gym page once
// online is what seeds the cache for every offline session after that, same as any other page.
