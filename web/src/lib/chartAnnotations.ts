import type { MemoryEvent } from "./types";

// Races/tests as vertical markers (A-priority emphasized) and their taper windows, shaded —
// interaction spec #7. Reuses the same 14-day taper window catch/coach/memory.py's
// next_a_race() already defines for the Today screen's recommendation line, rather than
// inventing a second "what counts as taper" definition on the frontend.
const TAPER_DAYS = 14;

export interface EventMarker {
  date: string; // YYYY-MM-DD
  label: string;
  emphasized: boolean; // A-priority race
  taperStart: string | null; // YYYY-MM-DD, only for races
}

export function eventsToMarkers(events: MemoryEvent[]): EventMarker[] {
  return events
    .filter((e) => e.type === "race" || e.type === "2k_test")
    .map((e) => ({
      date: e.date,
      label: e.name,
      emphasized: e.priority === "A",
      taperStart: e.type === "race" ? shiftIsoDate(e.date, -TAPER_DAYS) : null,
    }));
}

function shiftIsoDate(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}
