import { describe, expect, it } from "vitest";
import {
  clampSpanDays,
  domainToDateStrings,
  parseChartUrlState,
  presetSpanDays,
  presetToDomain,
  writeChartUrlState,
} from "./chartRange";

describe("presetSpanDays", () => {
  it("maps fixed presets to day counts", () => {
    expect(presetSpanDays("7d")).toBe(7);
    expect(presetSpanDays("4w")).toBe(28);
    expect(presetSpanDays("12w")).toBe(84);
    expect(presetSpanDays("6m")).toBe(182);
    expect(presetSpanDays("1y")).toBe(365);
  });

  it("'all' has no fixed span", () => {
    expect(presetSpanDays("all")).toBeNull();
  });

  it("'season' counts back to the most recent September 1st", () => {
    const afterSeasonStart = new Date(2026, 9, 15); // Oct 15, 2026 -> season started Sep 1 2026
    expect(presetSpanDays("season", afterSeasonStart)).toBe(44);

    const beforeSeasonStart = new Date(2026, 2, 1); // Mar 1, 2026 -> season started Sep 1 2025
    const days = presetSpanDays("season", beforeSeasonStart);
    expect(days).toBeGreaterThan(150);
  });
});

describe("presetToDomain", () => {
  const now = new Date(2026, 10, 1); // Nov 1 2026

  it("resolves a fixed preset relative to `now`", () => {
    const domain = presetToDomain("7d", now, null);
    expect(domain.max).toBe(now.getTime());
    expect(domain.max - domain.min).toBe(7 * 86_400_000);
  });

  it("'all' spans from the earliest known date to now", () => {
    const earliest = new Date(2024, 0, 1);
    const domain = presetToDomain("all", now, earliest);
    expect(domain.min).toBe(earliest.getTime());
    expect(domain.max).toBe(now.getTime());
  });

  it("'all' with no known history still returns a sane, non-empty domain", () => {
    const domain = presetToDomain("all", now, null);
    expect(domain.max).toBeGreaterThan(domain.min);
  });

  it("a fixed-span preset wider than the real history starts at the first data point, not before it", () => {
    // Data only since ~18 days ago ("mid-October" relative to the Nov 1 `now` above) — "6m"
    // would otherwise start 182 days back, showing ~5 months of empty chart.
    const earliest = new Date(2026, 9, 14); // Oct 14 2026
    const domain = presetToDomain("6m", now, earliest);
    expect(domain.min).toBe(earliest.getTime());
    expect(domain.max).toBe(now.getTime());
  });

  it("a fixed-span preset narrower than the real history is unaffected", () => {
    const earliest = new Date(2024, 0, 1); // years of history
    const domain = presetToDomain("4w", now, earliest);
    expect(domain.max - domain.min).toBe(28 * 86_400_000);
  });

  it("never clamps a fixed-span preset to less than the 7-day minimum zoom", () => {
    const earliest = new Date(now.getTime() - 2 * 86_400_000); // only 2 days of real history
    const domain = presetToDomain("12w", now, earliest);
    expect(domain.max - domain.min).toBe(7 * 86_400_000);
  });
});

describe("clampSpanDays", () => {
  it("never goes below the 7-day minimum zoom", () => {
    expect(clampSpanDays(1, 1000)).toBe(7);
  });

  it("never exceeds the all-time span", () => {
    expect(clampSpanDays(10_000, 400)).toBe(400);
  });

  it("passes through an in-range value unchanged", () => {
    expect(clampSpanDays(30, 400)).toBe(30);
  });
});

describe("chart URL state round-trip", () => {
  it("parses a preset from the URL", () => {
    const params = new URLSearchParams("range=12w");
    expect(parseChartUrlState(params)).toEqual({ preset: "12w", from: null, to: null });
  });

  it("ignores an unrecognized preset value", () => {
    const params = new URLSearchParams("range=bogus");
    expect(parseChartUrlState(params).preset).toBeNull();
  });

  it("parses a custom from/to pair", () => {
    const params = new URLSearchParams("from=2026-01-01&to=2026-02-01");
    expect(parseChartUrlState(params)).toEqual({ preset: null, from: "2026-01-01", to: "2026-02-01" });
  });

  it("writing a preset clears any existing from/to", () => {
    const params = new URLSearchParams("from=2026-01-01&to=2026-02-01");
    const next = writeChartUrlState(params, { preset: "4w", from: null, to: null });
    expect(next.get("range")).toBe("4w");
    expect(next.get("from")).toBeNull();
    expect(next.get("to")).toBeNull();
  });

  it("writing a custom range clears any existing preset", () => {
    const params = new URLSearchParams("range=12w");
    const next = writeChartUrlState(params, { preset: null, from: "2026-01-01", to: "2026-02-01" });
    expect(next.get("range")).toBeNull();
    expect(next.get("from")).toBe("2026-01-01");
    expect(next.get("to")).toBe("2026-02-01");
  });

  it("round-trips through parse -> write -> parse", () => {
    const original = { preset: null, from: "2026-03-01", to: "2026-04-01" };
    const written = writeChartUrlState(new URLSearchParams(), original);
    expect(parseChartUrlState(written)).toEqual(original);
  });

  it("preserves unrelated query params", () => {
    const params = new URLSearchParams("metric=recovery");
    const next = writeChartUrlState(params, { preset: "7d", from: null, to: null });
    expect(next.get("metric")).toBe("recovery");
    expect(next.get("range")).toBe("7d");
  });
});

describe("domainToDateStrings", () => {
  it("formats epoch-ms bounds as YYYY-MM-DD", () => {
    const domain = { min: Date.UTC(2026, 0, 1), max: Date.UTC(2026, 0, 31) };
    expect(domainToDateStrings(domain)).toEqual({ from: "2026-01-01", to: "2026-01-31" });
  });
});
