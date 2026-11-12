import { describe, expect, it } from "vitest";
import { formatClock, formatMetres, formatMinutesOrHours, parseClock } from "./duration";

describe("parseClock", () => {
  it("reads plain seconds, m:ss, m:ss.t and h:mm:ss", () => {
    expect(parseClock("90")).toBe(90);
    expect(parseClock("4:00")).toBe(240);
    expect(parseClock("1:50.5")).toBe(110.5);
    expect(parseClock("1:02:03")).toBe(3723);
    expect(parseClock(" 2:05 ")).toBe(125);
  });
  it("rejects anything else rather than guessing", () => {
    for (const bad of ["", "abc", "1:75", "1:2:3:4", "-5", "1,5"]) expect(parseClock(bad)).toBeNull();
  });
});

describe("formatClock", () => {
  it("formats minutes and seconds, hours when needed, and tenths on request", () => {
    expect(formatClock(240)).toBe("4:00");
    expect(formatClock(60)).toBe("1:00");
    expect(formatClock(3723)).toBe("1:02:03");
    expect(formatClock(110.5, true)).toBe("1:50.5");
    expect(formatClock(110, true)).toBe("1:50");
    expect(formatClock(null)).toBe("—");
  });
  it("round-trips with parseClock", () => {
    for (const s of [45, 240, 3600, 125.5]) expect(parseClock(formatClock(s, true))).toBe(s);
  });
});

describe("display helpers", () => {
  it("minutes/hours and metres", () => {
    expect(formatMinutesOrHours(1680)).toBe("28 min");
    expect(formatMinutesOrHours(3600)).toBe("1 h");
    expect(formatMinutesOrHours(5400)).toBe("1 h 30 min");
    expect(formatMinutesOrHours(null)).toBe("—");
    expect(formatMetres(500)).toBe("500 m");
    expect(formatMetres(5000)).toBe("5 km");
    expect(formatMetres(2250)).toBe("2250 m");
  });
});
