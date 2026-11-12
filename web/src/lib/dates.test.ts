import { describe, expect, it } from "vitest";
import { addDays, addMonths, daysBetween, monthGrid, parseISODate, toISODate, todayISO, weekDays, weekStart } from "./dates";

describe("calendar date math", () => {
  it("starts weeks on Monday", () => {
    expect(weekStart("2026-11-11")).toBe("2026-11-09"); // Wednesday
    expect(weekStart("2026-11-15")).toBe("2026-11-09"); // Sunday belongs to the week that began Monday
    expect(weekStart("2026-11-09")).toBe("2026-11-09");
    expect(weekDays("2026-11-09")).toHaveLength(7);
    expect(weekDays("2026-11-09")[6]).toBe("2026-11-15");
  });

  it("adds days across month and year ends", () => {
    expect(addDays("2026-12-30", 3)).toBe("2027-01-02");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
  });

  it("is DST-safe: a day is a calendar day, not 24 hours", () => {
    // US clocks change on 2026-03-08 (spring forward) and 2026-11-01 (fall back); a naive
    // +24h on local midnight would land on the wrong calendar date around these.
    expect(addDays("2026-03-07", 1)).toBe("2026-03-08");
    expect(addDays("2026-03-08", 1)).toBe("2026-03-09");
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-11-01", 1)).toBe("2026-11-02");
    expect(daysBetween("2026-03-01", "2026-03-15")).toBe(14);
    expect(daysBetween("2026-10-25", "2026-11-08")).toBe(14);
  });

  it("round-trips a date through local fields rather than UTC", () => {
    // Local midnight: toISOString() would shift this to the previous day for anyone east of UTC.
    const d = new Date(2026, 5, 1, 0, 30);
    expect(toISODate(d)).toBe("2026-06-01");
    expect(todayISO(new Date(2026, 5, 1, 23, 59))).toBe("2026-06-01");
    expect(toISODate(parseISODate("2026-06-01"))).toBe("2026-06-01");
  });

  it("counts calendar days between dates", () => {
    expect(daysBetween("2026-11-09", "2026-11-09")).toBe(0);
    expect(daysBetween("2026-11-09", "2026-11-19")).toBe(10);
    expect(daysBetween("2026-11-19", "2026-11-09")).toBe(-10);
  });

  it("builds Monday-first month grids padded with neighbouring days", () => {
    const grid = monthGrid(2026, 10); // November 2026 starts on a Sunday
    expect(grid[0][0]).toBe("2026-10-26");
    expect(grid[0][6]).toBe("2026-11-01");
    expect(grid.every((w) => w.length === 7)).toBe(true);
    expect(grid[grid.length - 1]).toContain("2026-11-30");
    expect(monthGrid(2027, 1)).toHaveLength(4); // Feb 2027 starts on a Monday and has 28 days
  });

  it("clamps month arithmetic to the last day of the shorter month", () => {
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2026-03-31", -1)).toBe("2026-02-28");
    expect(addMonths("2026-12-15", 1)).toBe("2027-01-15");
  });
});
