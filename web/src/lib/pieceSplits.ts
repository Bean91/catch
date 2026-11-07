// Small TS port of catch/analytics/piece.py (session 17 — see PLAN.md, the task called
// itself "session 13") — duplicated intentionally, same precedent as equipment.ts: the add-
// piece form needs live validation and paste-parsing feedback with zero network round trips
// (task Part C.1's "fast form"). The server re-validates from scratch on save and is always
// the value of record; this is a live preview only. Keep in sync by hand — the shared
// pytest/Vitest paste-vector fixture (tests/fixtures/pieces/paste_vectors.json) at least
// catches a parser drift, even if it can't catch every other function drifting.
import type { ErgTestType } from "./types";

export const PIECE_TYPES: ErgTestType[] = ["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"];
const DISTANCE_BY_TYPE: Partial<Record<ErgTestType, number>> = { "500m": 500, "1000m": 1000, "2000m": 2000, "5000m": 5000, "6000m": 6000 };
const DURATION_BY_TYPE: Partial<Record<ErgTestType, number>> = { "30min_r20": 1800, "60min": 3600 };

const MIN_PLAUSIBLE_RATE = 14;
const MAX_PLAUSIBLE_RATE = 50;
const WATTS_TOLERANCE_FLOOR = 2.0;
const WATTS_TOLERANCE_PCT = 0.01;
const DEFAULT_SPLIT_DISTANCE_M = 500.0;
const DEFAULT_TIME_SPLIT_S = 300.0;

const WATTS_CONSTANT = 2.8;

export interface SplitRow {
  split_index: number;
  distance_m: number | null;
  split_s: number | null;
  rate: number | null;
  watts: number | null;
  hr: number | null;
  hr_source?: "typed" | "derived" | "concept2" | null;
}

export interface ValidationIssue {
  split_index: number | null;
  field: string;
  message: string;
}

export interface Validation {
  ok: boolean;
  issues: ValidationIssue[];
}

export function wattsForSplit(splitS: number, distanceDeltaM = DEFAULT_SPLIT_DISTANCE_M): number {
  const pacePer500 = (splitS / distanceDeltaM) * DEFAULT_SPLIT_DISTANCE_M;
  const secondsPerMeter = pacePer500 / DEFAULT_SPLIT_DISTANCE_M;
  return WATTS_CONSTANT / secondsPerMeter ** 3;
}

export function defaultSplits(pieceType: ErgTestType, distanceM?: number | null, durationS?: number | null): SplitRow[] {
  const distance = DISTANCE_BY_TYPE[pieceType] ?? distanceM ?? null;
  const duration = DURATION_BY_TYPE[pieceType] ?? durationS ?? null;

  if (distance) {
    const n = Math.max(1, Math.round(distance / DEFAULT_SPLIT_DISTANCE_M));
    const perSplit = distance / n;
    return Array.from({ length: n }, (_, i) => ({
      split_index: i + 1,
      distance_m: Math.round(perSplit * (i + 1) * 10) / 10,
      split_s: null,
      rate: null,
      watts: null,
      hr: null,
    }));
  }
  if (duration) {
    const n = Math.max(1, Math.round(duration / DEFAULT_TIME_SPLIT_S));
    return Array.from({ length: n }, (_, i) => ({ split_index: i + 1, distance_m: null, split_s: null, rate: null, watts: null, hr: null }));
  }
  return [{ split_index: 1, distance_m: null, split_s: null, rate: null, watts: null, hr: null }];
}

function rowDistanceDelta(rows: SplitRow[], i: number): number | null {
  const d = rows[i].distance_m;
  if (d == null) return null;
  const prev = i > 0 ? rows[i - 1].distance_m : 0;
  if (prev == null) return null;
  return d - prev;
}

export function validateSplits(rows: SplitRow[], totalDistanceM: number | null, totalDurationS: number | null): Validation {
  const issues: ValidationIssue[] = [];
  const n = rows.length;
  const definedSplits = rows.map((r) => r.split_s).filter((s): s is number => s != null);

  if (totalDurationS != null && definedSplits.length === n && n > 0) {
    const totalOfSplits = definedSplits.reduce((a, b) => a + b, 0);
    const tolerance = 0.5 * n;
    if (Math.abs(totalOfSplits - totalDurationS) > tolerance) {
      issues.push({
        split_index: null,
        field: "total_time",
        message: `Splits sum to ${totalOfSplits.toFixed(1)}s but the total is ${totalDurationS.toFixed(1)}s (off by ${Math.abs(totalOfSplits - totalDurationS).toFixed(1)}s, tolerance is ${tolerance.toFixed(1)}s).`,
      });
    }
  }

  if (totalDistanceM != null && rows.length > 0 && rows[rows.length - 1].distance_m != null) {
    const last = rows[rows.length - 1].distance_m as number;
    const toleranceD = Math.max(1.0 * n, totalDistanceM * 0.005);
    if (Math.abs(last - totalDistanceM) > toleranceD) {
      issues.push({ split_index: null, field: "total_distance", message: `Splits add up to ${last.toFixed(0)}m but the total is ${totalDistanceM.toFixed(0)}m.` });
    }
  }

  rows.forEach((row, i) => {
    const { split_s: splitS, rate, watts } = row;
    if (rate != null && (rate < MIN_PLAUSIBLE_RATE || rate > MAX_PLAUSIBLE_RATE)) {
      issues.push({ split_index: row.split_index, field: "rate", message: `${rate}spm is outside the plausible ${MIN_PLAUSIBLE_RATE}-${MAX_PLAUSIBLE_RATE} range.` });
    }
    if (splitS != null && watts != null && splitS > 0) {
      const distanceDelta = rowDistanceDelta(rows, i) ?? DEFAULT_SPLIT_DISTANCE_M;
      const expected = wattsForSplit(splitS, distanceDelta);
      const toleranceW = Math.max(WATTS_TOLERANCE_FLOOR, expected * WATTS_TOLERANCE_PCT);
      if (Math.abs(expected - watts) > toleranceW) {
        issues.push({
          split_index: row.split_index,
          field: "watts",
          message: `${watts}W doesn't match the split (${expected.toFixed(0)}W implied by ${splitS.toFixed(1)}s/${distanceDelta.toFixed(0)}m).`,
        });
      }
    }
  });

  return { ok: issues.length === 0, issues };
}

export interface Aggregate {
  duration_s: number | null;
  distance_m: number | null;
  avg_split_s: number | null;
  avg_rate: number | null;
  avg_watts: number | null;
}

export function aggregateFromSplits(rows: SplitRow[]): Aggregate {
  const definedSplits = rows.map((r) => r.split_s).filter((s): s is number => s != null);
  const rates = rows.map((r) => r.rate).filter((v): v is number => v != null);
  const watts = rows.map((r) => r.watts).filter((v): v is number => v != null);
  const durationS = definedSplits.length === rows.length && rows.length > 0 ? definedSplits.reduce((a, b) => a + b, 0) : null;
  const distanceM = rows.length > 0 && rows[rows.length - 1].distance_m != null ? rows[rows.length - 1].distance_m : null;
  return {
    duration_s: durationS,
    distance_m: distanceM,
    avg_split_s: definedSplits.length ? definedSplits.reduce((a, b) => a + b, 0) / definedSplits.length : null,
    avg_rate: rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : null,
    avg_watts: watts.length ? watts.reduce((a, b) => a + b, 0) / watts.length : null,
  };
}

export function parseTimeToken(timeStr: string, label = "time"): number {
  if (!timeStr.includes(":")) throw new Error(`Can't parse ${label} '${timeStr}' — expected m:ss or m:ss.t.`);
  const [minutesStr, secondsStr] = timeStr.split(":", 2);
  const minutes = Number.parseInt(minutesStr, 10);
  const seconds = Number.parseFloat(secondsStr);
  if (Number.isNaN(minutes) || Number.isNaN(seconds)) throw new Error(`Can't parse ${label} '${timeStr}' — expected m:ss or m:ss.t.`);
  return minutes * 60 + seconds;
}

export function parseSplitsPaste(text: string): SplitRow[] {
  const raw = text.replace(/\n/g, "/");
  const tokens = raw
    .split("/")
    .map((t) => t.trim())
    .filter(Boolean);
  return tokens.map((token, i) => {
    const parts = token.split(/\s+/).filter(Boolean);
    const timeStr = parts[0];
    const rate = parts.length > 1 ? Number.parseFloat(parts[1]) : null;
    const splitS = parseTimeToken(timeStr, `split ${i + 1}`);
    return { split_index: i + 1, distance_m: null, split_s: splitS, rate, watts: null, hr: null };
  });
}
