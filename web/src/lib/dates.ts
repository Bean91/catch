// Calendar date math on plain "YYYY-MM-DD" strings. Everything is done with local calendar
// fields (new Date(y, m, d + n)), never `toISOString().slice(0, 10)` — that gives the UTC
// date, which is the wrong day for anyone east of UTC just after midnight and anyone west of
// it in the evening — and never "+ 24 h" arithmetic, which a DST change turns into the wrong day.

export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function todayISO(now: Date = new Date()): string {
  return toISODate(now);
}

export function addDays(iso: string, n: number): string {
  const d = parseISODate(iso);
  return toISODate(new Date(d.getFullYear(), d.getMonth(), d.getDate() + n));
}

/** Whole calendar days from a to b (b - a), DST-safe because it counts UTC midnights. */
export function daysBetween(a: string, b: string): number {
  const [ay, am, ad] = a.split("-").map(Number);
  const [by, bm, bd] = b.split("-").map(Number);
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000);
}

/** The Monday on or before `iso` — weeks start on Monday, matching the backend. */
export function weekStart(iso: string): string {
  const d = parseISODate(iso);
  return addDays(iso, -((d.getDay() + 6) % 7));
}

export function weekDays(startIso: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(startIso, i));
}

/** Weeks (Monday-first) covering a month, padded with the neighbouring months' days. */
export function monthGrid(year: number, monthIndex: number): string[][] {
  const first = toISODate(new Date(year, monthIndex, 1));
  const last = toISODate(new Date(year, monthIndex + 1, 0));
  const weeks: string[][] = [];
  let cursor = weekStart(first);
  while (cursor <= last) {
    weeks.push(weekDays(cursor));
    cursor = addDays(cursor, 7);
  }
  return weeks;
}

export function addMonths(iso: string, n: number): string {
  const d = parseISODate(iso);
  const target = new Date(d.getFullYear(), d.getMonth() + n, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  return toISODate(new Date(target.getFullYear(), target.getMonth(), Math.min(d.getDate(), lastDay)));
}

export function isSameMonth(a: string, b: string): boolean {
  return a.slice(0, 7) === b.slice(0, 7);
}

export function weekdayShort(iso: string): string {
  return parseISODate(iso).toLocaleDateString(undefined, { weekday: "short" });
}

export function dayLabel(iso: string): string {
  return parseISODate(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export function monthLabel(iso: string): string {
  return parseISODate(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

export function weekRangeLabel(startIso: string): string {
  const end = addDays(startIso, 6);
  const a = parseISODate(startIso);
  const b = parseISODate(end);
  const sameMonth = a.getMonth() === b.getMonth();
  const left = a.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const right = b.toLocaleDateString(undefined, sameMonth ? { day: "numeric" } : { month: "short", day: "numeric" });
  return `${left} – ${right}`;
}
