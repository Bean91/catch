/// <reference types="node" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as pieceSplits from "./pieceSplits";
import { aggregateFromSplits, defaultSplits, parseSplitsPaste, validateSplits, type SplitRow } from "./pieceSplits";

// The task's own worked example (session 17 Part B.3's fixture).
const TASK_2K_SPLITS_S = [96.8, 98.9, 99.0, 97.7];
const TASK_2K_TOTAL_S = 392.4;

function rows(splitsS: number[], distances: number[] = [500, 1000, 1500, 2000]): SplitRow[] {
  return splitsS.map((s, i) => ({ split_index: i + 1, distance_m: distances[i], split_s: s, rate: 32, watts: null, hr: null }));
}

describe("defaultSplits", () => {
  it("2000m is four rows of 500", () => {
    const r = defaultSplits("2000m");
    expect(r.map((x) => x.distance_m)).toEqual([500, 1000, 1500, 2000]);
    expect(r.every((x) => x.split_s === null)).toBe(true);
  });

  it("30min_r20 is duration-based", () => {
    const r = defaultSplits("30min_r20");
    expect(r).toHaveLength(6);
    expect(r.every((x) => x.distance_m === null)).toBe(true);
  });

  it("custom uses the supplied distance", () => {
    const r = defaultSplits("custom", 1500);
    expect(r).toHaveLength(3);
  });
});

describe("validateSplits", () => {
  it("accepts the task's own exact example", () => {
    expect(validateSplits(rows(TASK_2K_SPLITS_S), 2000, TASK_2K_TOTAL_S)).toEqual({ ok: true, issues: [] });
  });

  it("flags a total-time mismatch", () => {
    const r = validateSplits(rows([96.8, 98.9, 99.0, 90.0]), 2000, TASK_2K_TOTAL_S);
    expect(r.ok).toBe(false);
    expect(r.issues.some((i) => i.field === "total_time")).toBe(true);
  });

  it("flags a distance mismatch", () => {
    const r = validateSplits(rows(TASK_2K_SPLITS_S, [500, 1000, 1500, 1950]), 2000, TASK_2K_TOTAL_S);
    expect(r.issues.some((i) => i.field === "total_distance")).toBe(true);
  });

  it("flags an implausible rate", () => {
    const data = rows(TASK_2K_SPLITS_S);
    data[0].rate = 95;
    const r = validateSplits(data, 2000, TASK_2K_TOTAL_S);
    expect(r.issues.some((i) => i.split_index === 1 && i.field === "rate")).toBe(true);
  });

  // Session 34: power is the server's alone (catch/analytics/erg_math.py via POST /api/pieces/preview). The browser has no copy of the
  // formula and never judges a watts value — tests/analytics/test_power_and_mass.py covers the check.
  it("holds no power formula and never checks watts", () => {
    expect(Object.keys(pieceSplits).some((name) => /watt/i.test(name))).toBe(false);
    const data = rows(TASK_2K_SPLITS_S);
    data[0].watts = 9999;
    expect(validateSplits(data, 2000, TASK_2K_TOTAL_S).issues.some((i) => i.field === "watts")).toBe(false);
    expect("avg_watts" in aggregateFromSplits(data)).toBe(false);
  });

  it("skips checks with insufficient data", () => {
    expect(validateSplits(defaultSplits("2000m"), 2000, null)).toEqual({ ok: true, issues: [] });
  });
});

describe("aggregateFromSplits", () => {
  it("matches the Python implementation's totals", () => {
    const agg = aggregateFromSplits(rows(TASK_2K_SPLITS_S));
    expect(agg.duration_s).toBeCloseTo(TASK_2K_TOTAL_S, 5);
    expect(agg.distance_m).toBe(2000);
    expect(agg.avg_rate).toBeCloseTo(32, 5);
  });

  it("averages pace over total distance, not the mean of uneven split durations (L-10)", () => {
    const uneven: SplitRow[] = [
      { split_index: 1, distance_m: 500, split_s: 105, rate: null, watts: null, hr: null },
      { split_index: 2, distance_m: 1000, split_s: 105, rate: null, watts: null, hr: null },
      { split_index: 3, distance_m: 1500, split_s: 105, rate: null, watts: null, hr: null },
      { split_index: 4, distance_m: 1750, split_s: 52, rate: null, watts: null, hr: null },
    ];
    // 367 s over 1750 m -> 367 / 1750 * 500 = 104.857 s/500 m (the old mean of durations gave 91.75)
    expect(aggregateFromSplits(uneven).avg_split_s).toBeCloseTo((367 / 1750) * 500, 6);
    const timed: SplitRow[] = [
      { split_index: 1, distance_m: null, split_s: 300, rate: null, watts: null, hr: null },
      { split_index: 2, distance_m: null, split_s: 300, rate: null, watts: null, hr: null },
    ];
    expect(aggregateFromSplits(timed).avg_split_s).toBeNull(); // no distance, no pace
  });
});

describe("parseSplitsPaste", () => {
  it("matches the task's own example", () => {
    const r = parseSplitsPaste("1:36.8 32 / 1:38.9 30 / 1:39.0 31 / 1:37.7 32");
    expect(r.map((x) => x.split_s)).toEqual(TASK_2K_SPLITS_S);
    expect(r.map((x) => x.rate)).toEqual([32, 30, 31, 32]);
  });

  it("raises on an unparseable token, naming its position", () => {
    expect(() => parseSplitsPaste("1:36.8 32 / garbage 30")).toThrow(/split 2/);
  });

  // Shared with tests/analytics/test_piece.py — the exact same input/output pairs, so the
  // Python and TS paste parsers can't silently drift from each other.
  const vectorsPath = fileURLToPath(new URL("../../../tests/fixtures/pieces/paste_vectors.json", import.meta.url));
  const vectors = JSON.parse(readFileSync(vectorsPath, "utf-8")) as { name: string; input: string; splits: number[]; rates: (number | null)[] }[];

  it.each(vectors)("matches shared vector: $name", (vector) => {
    const r = parseSplitsPaste(vector.input);
    expect(r.map((x) => x.split_s)).toEqual(vector.splits);
    expect(r.map((x) => x.rate)).toEqual(vector.rates);
  });
});

// Session 33: rowing erg vs bike — the same vectors tests/analytics/test_piece_modality.py runs, so the two implementations agree
// on the split unit (500 m vs 1000 m), the rate/cadence range and when the pace->watts check applies.
describe("modality (shared vectors)", () => {
  type Modality = "rowing_erg" | "bike";
  const unitPath = fileURLToPath(new URL("../../../tests/fixtures/pieces/split_unit_vectors.json", import.meta.url));
  const unit = JSON.parse(readFileSync(unitPath, "utf-8")) as {
    aggregate: { name: string; modality: Modality; rows: SplitRow[]; avg_split_s: number }[];
    validate: { name: string; modality: Modality; rows: SplitRow[]; fields: string[]; server_only?: boolean }[];
    default_rows: { piece_type: "2000m" | "5000m"; modality: Modality; distances: number[] }[];
  };

  it.each(unit.aggregate)("average split: $name", (c) => {
    expect(aggregateFromSplits(c.rows, c.modality).avg_split_s).toBeCloseTo(c.avg_split_s, 6);
  });

  it.each(unit.validate.filter((c) => !c.server_only))("validation: $name", (c) => {
    expect(validateSplits(c.rows, null, null, c.modality).issues.map((i) => i.field).sort()).toEqual([...c.fields].sort());
  });

  it.each(unit.default_rows)("template rows: $modality $piece_type", (c) => {
    expect(defaultSplits(c.piece_type, null, null, c.modality).map((r) => r.distance_m)).toEqual(c.distances);
  });
});
