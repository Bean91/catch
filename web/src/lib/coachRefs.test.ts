import { describe, expect, it } from "vitest";
import { isCoachRef, splitRefs } from "./coachRefs";

describe("coach refs", () => {
  it("links only the allowed in-app paths and keeps every character", () => {
    const text = "Your fastest 2k (/tests/12) beat /workouts/345, see /lab.";
    const parts = splitRefs(text);
    expect(parts.map((p) => p.text).join("")).toBe(text);
    expect(parts.filter((p) => p.to).map((p) => p.to)).toEqual(["/tests/12", "/workouts/345", "/lab"]);
  });

  it("never links a host, a query, a script-ish path or an unknown route", () => {
    for (const t of ["https://evil.example/workouts/1", "/settings/privacy", "/workouts/abc", "//evil/workouts/1", "/tests/piece/../../x"]) {
      expect(splitRefs(t).some((p) => p.to)).toBe(false);
    }
    // A query or hash never travels: at most the bare allowed path becomes the link.
    const q = splitRefs("/workouts/1?x=javascript:alert(1)");
    expect(q.filter((p) => p.to).map((p) => p.to)).toEqual(["/workouts/1"]);
    expect(isCoachRef("/tests/piece/4")).toBe(true);
    expect(isCoachRef("/calendar/events/9")).toBe(true);
    expect(isCoachRef("/workouts/1/edit")).toBe(false);
  });
});
