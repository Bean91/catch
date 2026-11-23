// Session 32 (docs/time.md): which zone dates are shown in.
//
// The server decides the athlete's current zone (home zone, or where their phone/watch says they are) and sends it with /api/me
// and /api/today. Every "today" and every instant shown in the app uses that zone — never the browser's own clock, so a laptop
// left on home time shows the same day as the phone abroad. Bare "YYYY-MM-DD" strings are calendar days already and are never
// converted. A workout shows its time in the zone it happened in, labelled when that differs from the current one.

let activeZone: string | null = null;

/** The browser/phone's own IANA zone — what the app reports to the server on open; never used to decide a day by itself. */
export function deviceZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

export function isValidZone(zone: string | null | undefined): zone is string {
  if (!zone) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone }).format(0);
    return true;
  } catch {
    return false;
  }
}

/** Set by the app when /api/me (or /api/today) arrives. Offsets like "+09:00" are accepted (Intl understands them in modern engines;
 * when one doesn't, it falls back to the device zone). */
export function setActiveZone(zone: string | null | undefined): void {
  const next = isValidZone(zone) ? zone : null;
  if (next === activeZone) return;
  activeZone = next;
  for (const fn of zoneListeners) fn();
}

const zoneListeners = new Set<() => void>();

/** For `useSyncExternalStore`: a component that shows "today" re-renders when the account's zone arrives or changes. */
export function subscribeActiveZone(fn: () => void): () => void {
  zoneListeners.add(fn);
  return () => zoneListeners.delete(fn);
}

export function activeTimeZone(): string | undefined {
  return activeZone ?? undefined;
}

function parts(d: Date, zone: string | undefined): { y: string; m: string; d: string } {
  const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" });
  const p = Object.fromEntries(fmt.formatToParts(d).map((x) => [x.type, x.value]));
  return { y: p.year, m: p.month, d: p.day };
}

/** The calendar day an instant falls on in `zone` (default: the account's current zone), as "YYYY-MM-DD". */
export function dayInZone(instant: Date, zone: string | undefined = activeTimeZone()): string {
  const { y, m, d } = parts(instant, zone);
  return `${y}-${m}-${d}`;
}

/** Today in the account's current zone. Recomputed on every call, so it rolls over at the athlete's own midnight. */
export function zonedTodayISO(now: Date = new Date()): string {
  return dayInZone(now, activeTimeZone());
}

/** A short, readable name: "Asia/Tokyo" -> "Tokyo", "America/New_York" -> "New York", "+09:00" -> "UTC+09:00". */
export function zoneLabel(zone: string | null | undefined): string {
  if (!zone) return "";
  if (/^[+-]\d{2}:\d{2}$/.test(zone)) return `UTC${zone}`;
  if (zone === "UTC" || zone === "Etc/UTC") return "UTC";
  const city = zone.split("/").pop() ?? zone;
  return city.replaceAll("_", " ");
}

/** An instant's wall-clock time. `zone` = where it happened (a workout's local_tz); labelled when that isn't the current zone. */
export function formatInstantTime(iso: string, zone?: string | null): string {
  const tz = isValidZone(zone) ? zone : activeTimeZone();
  const time = new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz });
  const differs = zone && isValidZone(zone) && activeZone && zone !== activeZone && offsetMinutes(zone) !== offsetMinutes(activeZone, new Date(iso));
  return differs ? `${time} · ${zoneLabel(zone)}` : time;
}

/** An instant's calendar date, short ("12 May"), in the account's zone (or the given one). */
export function formatInstantDate(iso: string, zone?: string | null, opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" }): string {
  const tz = isValidZone(zone) ? zone : activeTimeZone();
  return new Date(iso).toLocaleDateString(undefined, { ...opts, timeZone: tz });
}

/** Date and time of an instant in the account's zone (or `zone`): "12 May 2026, 07:10". */
export function formatInstantDateTime(iso: string, zone?: string | null): string {
  const tz = isValidZone(zone) ? zone : activeTimeZone();
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: tz });
}

function offsetMinutes(zone: string, at: Date = new Date()): number | null {
  try {
    const name = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" }).formatToParts(at).find((p) => p.type === "timeZoneName")?.value ?? "";
    const m = /GMT([+-])(\d{2}):?(\d{2})?/.exec(name);
    if (!m) return name === "GMT" ? 0 : null;
    const v = Number(m[2]) * 60 + Number(m[3] ?? 0);
    return m[1] === "-" ? -v : v;
  } catch {
    return null;
  }
}

/** Every IANA zone the browser knows, for the picker (lazy callers only — the list is a few hundred entries). */
export function allZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    const list = intl.supportedValuesOf?.("timeZone") ?? [];
    if (list.length) return list.includes("UTC") ? list : ["UTC", ...list];
  } catch {
    // fall through
  }
  const own = deviceZone();
  return Array.from(new Set(["UTC", ...(own ? [own] : []), "Europe/London", "Europe/Paris", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Asia/Tokyo", "Australia/Sydney"]));
}
