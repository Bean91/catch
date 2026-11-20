// Session 30 (docs/mobile/health-data.md): reads Apple Health (iOS) / Health Connect (Android) ON THE DEVICE and sends only what the
// person consented to. Order is fixed and enforced here: (1) the in-app notice + the categories they tick are recorded on the server,
// (2) only then does the OS permission sheet appear, (3) a preview of what would be sent is shown, (4) only after they confirm does
// anything leave the phone. Nothing is requested or read at launch.
//
// Honest limits, surfaced in the UI rather than hidden: HealthKit never says whether read access was denied (a denied type just
// returns nothing), so "no data" is reported as "no data returned", never as "denied". Workouts carry type/time/distance/energy only (the
// plugin exposes no per-workout heart-rate summary), and HealthKit's HRV is SDNN, which Catch does not use (Android's RMSSD is).
import { authedFetch } from "../authedFetch";
import { ApiError, isMock } from "../api";
import { nativePlatform } from "./platform";

export type HealthPlatform = "apple_health" | "health_connect";
export type HealthCategory = "workouts" | "sleep" | "resting_hr" | "spo2" | "hrv";

export const CATEGORY_INFO: Record<HealthCategory, { label: string; detail: string }> = {
  workouts: { label: "Workouts", detail: "Type, start and end time, distance and energy of each workout, and which app recorded it." },
  sleep: { label: "Sleep", detail: "Total sleep per night and its stages (deep, light, REM, awake) where your phone has them." },
  resting_hr: { label: "Resting heart rate", detail: "One resting heart rate per day." },
  spo2: { label: "Blood oxygen", detail: "Blood-oxygen readings, averaged per day." },
  hrv: { label: "Heart-rate variability (RMSSD)", detail: "Overnight HRV, averaged per day. Android only — Apple Health measures a different quantity (SDNN) that Catch can't use." },
};

export function healthPlatform(): HealthPlatform | null {
  const p = nativePlatform();
  return p === "ios" ? "apple_health" : p === "android" ? "health_connect" : null;
}

export function categoriesFor(platform: HealthPlatform): HealthCategory[] {
  return platform === "apple_health" ? ["workouts", "sleep", "resting_hr", "spo2"] : ["workouts", "sleep", "resting_hr", "spo2", "hrv"];
}

export interface ConsentRow {
  platform: HealthPlatform;
  categories: HealthCategory[];
  granted_at: string;
  revoked_at: string | null;
  last_import_at: string | null;
  active: boolean;
}
export interface HealthStatus {
  consents: ConsentRow[];
  counts: Record<HealthPlatform, { workouts: number; readings: number }>;
  connected_providers: string[];
  provider_app_markers: Record<string, string[]>;
}
export interface ImportResult {
  workouts: number;
  readings: number;
  skipped_duplicate: number;
  skipped_not_consented: number;
  skipped_invalid: number;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await authedFetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init.headers ?? {}) } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return res.json() as Promise<T>;
}

const MOCK_STATUS: HealthStatus = {
  consents: [],
  counts: { apple_health: { workouts: 0, readings: 0 }, health_connect: { workouts: 0, readings: 0 } },
  connected_providers: ["garmin"],
  provider_app_markers: { garmin: ["garmin"], withings: ["withings", "health mate"], concept2: ["concept2", "logbook"], whoop: ["whoop"] },
};

export const fetchHealthStatus = (): Promise<HealthStatus> => (isMock ? Promise.resolve(MOCK_STATUS) : call("/api/health/status"));
export const saveConsent = (platform: HealthPlatform, categories: HealthCategory[]): Promise<ConsentRow> =>
  isMock ? Promise.resolve({ platform, categories, granted_at: new Date().toISOString(), revoked_at: null, last_import_at: null, active: true }) : call("/api/health/consent" , { method: "PUT", body: JSON.stringify({ platform, categories }) });
export const revokeConsent = (platform: HealthPlatform, deleteData: boolean) =>
  isMock ? Promise.resolve({ revoked: true, workouts: 0, readings: 0 }) : call<{ revoked: true; workouts: number; readings: number }>("/api/health/consent/revoke", { method: "POST", body: JSON.stringify({ platform, delete_data: deleteData }) });
export const deleteImportedHealthData = () => (isMock ? Promise.resolve({ workouts: 0, readings: 0 }) : call<{ workouts: number; readings: number }>("/api/health/data", { method: "DELETE" }));

// ---------------------------------------------------------------- device side

const TYPE_FOR: Record<HealthCategory, string> = { workouts: "workouts", sleep: "sleep", resting_hr: "restingHeartRate", spo2: "oxygenSaturation", hrv: "heartRateVariability" };
const FIRST_IMPORT_DAYS = 30; // also Health Connect's default read window without the history permission
const OVERLAP_DAYS = 2; // re-read the last days each time: a watch syncs late, and imports are idempotent

export interface Availability {
  available: boolean;
  reason?: string;
}

export async function availability(): Promise<Availability> {
  const { Health } = await import("@capgo/capacitor-health");
  const a = await Health.isAvailable();
  return { available: a.available, reason: a.reason };
}

/** Shows the OS permission sheet. Call ONLY after saveConsent() succeeded. Returns the categories the OS says are readable;
 * on iOS that list is advisory (HealthKit doesn't reveal read denial). */
export async function requestOsPermission(categories: HealthCategory[]): Promise<{ readable: HealthCategory[]; unknownOnThisOs: boolean }> {
  const { Health } = await import("@capgo/capacitor-health");
  const read = categories.map((c) => TYPE_FOR[c]) as never[];
  const status = await Health.requestAuthorization({ read, write: [] });
  const ok = new Set<string>(status.readAuthorized as string[]);
  return { readable: categories.filter((c) => ok.has(TYPE_FOR[c])), unknownOnThisOs: healthPlatform() === "apple_health" };
}

/** Categories the OS currently lets us read. Health Connect reports this truthfully; HealthKit never does, so on iOS the consented list
 * is returned unchanged (a type that was denied simply comes back empty). */
export async function readableNow(platform: HealthPlatform, categories: HealthCategory[]): Promise<HealthCategory[]> {
  if (platform === "apple_health") return categories;
  const { Health } = await import("@capgo/capacitor-health");
  const status = await Health.checkAuthorization({ read: categories.map((c) => TYPE_FOR[c]) as never[], write: [] });
  const ok = new Set<string>(status.readAuthorized as string[]);
  return categories.filter((c) => ok.has(TYPE_FOR[c]));
}

export async function openHealthConnectSettings(): Promise<void> {
  const { Health } = await import("@capgo/capacitor-health");
  await Health.openHealthConnectSettings();
}

export interface HealthPayload {
  workouts: Record<string, unknown>[];
  readings: Record<string, unknown>[];
}
export interface HealthPreview {
  payload: HealthPayload;
  counts: { workouts: number; sleep: number; resting_hr: number; spo2: number; hrv: number; skipped_duplicate: number };
  from: string;
  to: string;
}

function localDate(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function isDuplicateOfConnected(app: string | undefined, id: string | undefined, status: HealthStatus): boolean {
  const hay = `${app ?? ""} ${id ?? ""}`.toLowerCase();
  return status.connected_providers.some((p) => (status.provider_app_markers[p] ?? []).some((m) => hay.includes(m)));
}

export async function sinceCursor(platform: HealthPlatform): Promise<Date> {
  const { Preferences } = await import("@capacitor/preferences");
  const { value } = await Preferences.get({ key: `catch.health.cursor.${platform}` });
  const first = new Date(Date.now() - FIRST_IMPORT_DAYS * 86400_000);
  if (!value) return first;
  const since = new Date(new Date(value).getTime() - OVERLAP_DAYS * 86400_000);
  return since > first ? since : first;
}

async function rememberCursor(platform: HealthPlatform, to: Date): Promise<void> {
  const { Preferences } = await import("@capacitor/preferences");
  await Preferences.set({ key: `catch.health.cursor.${platform}`, value: to.toISOString() });
}

export async function clearHealthState(): Promise<void> {
  const { Preferences } = await import("@capacitor/preferences");
  await Promise.all((["apple_health", "health_connect"] as const).map((p) => Preferences.remove({ key: `catch.health.cursor.${p}` })));
}

const asleepStates = new Set(["asleep", "light", "deep", "rem"]);

/** Reads the device's store and builds exactly what WOULD be sent. Nothing is uploaded here. */
export async function buildPreview(platform: HealthPlatform, categories: HealthCategory[], status: HealthStatus, since: Date): Promise<HealthPreview> {
  const { Health } = await import("@capgo/capacitor-health");
  const startDate = since.toISOString();
  const endDate = new Date().toISOString();
  const payload: HealthPayload = { workouts: [], readings: [] };
  const counts = { workouts: 0, sleep: 0, resting_hr: 0, spo2: 0, hrv: 0, skipped_duplicate: 0 };

  if (categories.includes("workouts")) {
    let anchor: string | undefined;
    do {
      const r = await Health.queryWorkouts({ startDate, endDate, limit: 100, anchor });
      for (const w of r.workouts) {
        if (isDuplicateOfConnected(w.sourceName, w.sourceId, status)) {
          counts.skipped_duplicate++;
          continue;
        }
        payload.workouts.push({
          external_id: w.platformId ?? `${w.startDate}|${w.workoutType}`,
          type: w.workoutType,
          start: w.startDate,
          end: w.endDate,
          distance_m: w.totalDistance ?? null,
          energy_kcal: w.totalEnergyBurned ?? null,
          origin_app: w.sourceName ?? null,
          origin_id: w.sourceId ?? null,
        });
        counts.workouts++;
      }
      anchor = r.anchor;
    } while (anchor && payload.workouts.length < 1000);
  }

  const daily = async (type: "restingHeartRate" | "oxygenSaturation" | "heartRateVariability", category: "resting_hr" | "spo2" | "hrv", scale = (v: number) => v) => {
    const { samples } = await Health.readSamples({ dataType: type, startDate, endDate, limit: 2000 });
    const byDay = new Map<string, { sum: number; n: number; app?: string; id?: string }>();
    for (const s of samples) {
      if (isDuplicateOfConnected(s.sourceName, s.sourceId, status)) {
        counts.skipped_duplicate++;
        continue;
      }
      const day = localDate(s.endDate);
      const cur = byDay.get(day) ?? { sum: 0, n: 0, app: s.sourceName, id: s.sourceId };
      cur.sum += scale(s.value);
      cur.n++;
      byDay.set(day, cur);
    }
    for (const [date, v] of byDay) {
      payload.readings.push({ category, date, value: Math.round((v.sum / v.n) * 10) / 10, origin_app: v.app ?? null, origin_id: v.id ?? null });
      counts[category]++;
    }
  };
  if (categories.includes("resting_hr")) await daily("restingHeartRate", "resting_hr");
  // HealthKit may report a fraction (0–1); Health Connect a percent. A value ≤ 1 is a fraction.
  if (categories.includes("spo2")) await daily("oxygenSaturation", "spo2", (v) => (v <= 1 ? v * 100 : v));
  if (categories.includes("hrv") && platform === "health_connect") await daily("heartRateVariability", "hrv");

  if (categories.includes("sleep")) {
    const { samples } = await Health.readSamples({ dataType: "sleep", startDate, endDate, limit: 2000 });
    type Night = { sleep_seconds: number; deep_sleep_seconds: number; light_sleep_seconds: number; rem_sleep_seconds: number; awake_sleep_seconds: number; app?: string; id?: string };
    const nights = new Map<string, Night>();
    for (const s of samples) {
      if (isDuplicateOfConnected(s.sourceName, s.sourceId, status)) {
        counts.skipped_duplicate++;
        continue;
      }
      const segments = s.stages?.length ? s.stages.map((g) => ({ state: g.stage, seconds: g.durationMinutes * 60, end: g.endDate })) : [{ state: s.sleepState ?? "asleep", seconds: s.value * 60, end: s.endDate }];
      for (const g of segments) {
        const day = localDate(g.end); // a night belongs to the day you woke up
        const n = nights.get(day) ?? { sleep_seconds: 0, deep_sleep_seconds: 0, light_sleep_seconds: 0, rem_sleep_seconds: 0, awake_sleep_seconds: 0, app: s.sourceName, id: s.sourceId };
        if (asleepStates.has(g.state)) n.sleep_seconds += g.seconds;
        if (g.state === "deep") n.deep_sleep_seconds += g.seconds;
        else if (g.state === "light") n.light_sleep_seconds += g.seconds;
        else if (g.state === "rem") n.rem_sleep_seconds += g.seconds;
        else if (g.state === "awake") n.awake_sleep_seconds += g.seconds;
        nights.set(day, n);
      }
    }
    for (const [date, n] of nights) {
      if (n.sleep_seconds < 1800) continue;
      payload.readings.push({ category: "sleep", date, sleep_seconds: Math.round(n.sleep_seconds), deep_sleep_seconds: Math.round(n.deep_sleep_seconds), light_sleep_seconds: Math.round(n.light_sleep_seconds), rem_sleep_seconds: Math.round(n.rem_sleep_seconds), awake_sleep_seconds: Math.round(n.awake_sleep_seconds), origin_app: n.app ?? null, origin_id: n.id ?? null });
      counts.sleep++;
    }
  }
  return { payload, counts, from: startDate, to: endDate };
}

/** Sends a previewed payload in server-sized batches. The cursor only moves after every batch was accepted. */
export async function sendPreview(platform: HealthPlatform, preview: HealthPreview): Promise<ImportResult> {
  const total: ImportResult = { workouts: 0, readings: 0, skipped_duplicate: 0, skipped_not_consented: 0, skipped_invalid: 0 };
  const add = (r: ImportResult) => (Object.keys(total) as (keyof ImportResult)[]).forEach((k) => (total[k] += r[k]));
  const W = 200;
  const R = 500;
  const rounds = Math.max(Math.ceil(preview.payload.workouts.length / W), Math.ceil(preview.payload.readings.length / R), 1);
  for (let i = 0; i < rounds; i++) {
    const body = { platform, workouts: preview.payload.workouts.slice(i * W, (i + 1) * W), readings: preview.payload.readings.slice(i * R, (i + 1) * R) };
    if (isMock) continue;
    add(await call<ImportResult>("/api/health/import", { method: "POST", body: JSON.stringify(body) }));
  }
  await rememberCursor(platform, new Date(preview.to));
  return total;
}

/** Foreground sync (app open / resume): only if a consent is active, the OS still allows it, and a first import was confirmed. */
export async function incrementalSync(): Promise<ImportResult | null> {
  const platform = healthPlatform();
  if (!platform) return null;
  const status = await fetchHealthStatus();
  const consent = status.consents.find((c) => c.platform === platform && c.active && c.last_import_at);
  if (!consent) return null;
  if (!(await availability()).available) return null;
  // A permission switched off in system settings since the last sync is respected: read only what is still allowed.
  const readable = await readableNow(platform, consent.categories);
  if (!readable.length) return null;
  const preview = await buildPreview(platform, readable, status, await sinceCursor(platform));
  if (!preview.payload.workouts.length && !preview.payload.readings.length) return null;
  return sendPreview(platform, preview);
}
