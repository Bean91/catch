// Parsing and display of the m:ss strings a template editor types. This is text <-> seconds only:
// every total (work, rest, session length) is computed by the server, never here.

export function parseClock(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  if (/^\d+(\.\d+)?$/.test(t)) return Number(t);
  const m = /^(\d+):([0-5]?\d(?:\.\d+)?)$/.exec(t);
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  const h = /^(\d+):(\d{1,2}):([0-5]?\d(?:\.\d+)?)$/.exec(t);
  if (h) return Number(h[1]) * 3600 + Number(h[2]) * 60 + Number(h[3]);
  return null;
}

export function formatClock(seconds: number | null | undefined, tenths = false): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const total = Math.round(seconds * 10) / 10;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total - h * 3600) / 60);
  const s = total - h * 3600 - m * 60;
  const sec = tenths && !Number.isInteger(s) ? s.toFixed(1).padStart(4, "0") : String(Math.round(s)).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function formatMinutesOrHours(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const r = mins - h * 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function formatMetres(m: number | null | undefined): string {
  if (m == null) return "—";
  return m >= 1000 && m % 100 === 0 ? `${m / 1000} km` : `${Math.round(m)} m`;
}
