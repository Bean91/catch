/// <reference types="node" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { aggregateFromSplits, defaultSplits, parseSplitsPaste, validateSplits, wattsForSplit, type SplitRow } from "./pieceSplits";

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

  it("flags watts that disagree with the split", () => {
    const data = rows(TASK_2K_SPLITS_S);
    data[0].watts = wattsForSplit(96.8) + 50;
    const r = validateSplits(data, 2000, TASK_2K_TOTAL_S);
    expect(r.issues.some((i) => i.split_index === 1 && i.field === "watts")).toBe(true);
  });

  it("accepts watts within tolerance of the split", () => {
    const data = rows(TASK_2K_SPLITS_S);
    data[0].watts = Math.round(wattsForSplit(96.8));
    const r = validateSplits(data, 2000, TASK_2K_TOTAL_S);
    expect(r.issues.some((i) => i.field === "watts")).toBe(false);
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
