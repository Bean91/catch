import { afterEach, describe, expect, it } from "vitest";
import { dayInZone, formatInstantTime, setActiveZone, zoneLabel, zonedTodayISO } from "./localTime";

afterEach(() => setActiveZone(null));

describe("account time zone (session 32)", () => {
  it("reads an instant's day in the account's zone, not the browser's", () => {
    const lateInNewYork = new Date("2026-03-04T04:30:00Z"); // 23:30 on 3 March in New York
    expect(dayInZone(lateInNewYork, "America/New_York")).toBe("2026-03-03");
    expect(dayInZone(lateInNewYork, "Asia/Tokyo")).toBe("2026-03-04");
    setActiveZone("America/New_York");
    expect(zonedTodayISO(lateInNewYork)).toBe("2026-03-03");
    setActiveZone("Asia/Tokyo");
    expect(zonedTodayISO(lateInNewYork)).toBe("2026-03-04");
  });
  it("handles daylight-saving days", () => {
    expect(dayInZone(new Date("2026-03-08T06:59:00Z"), "America/New_York")).toBe("2026-03-08"); // 01:59 EST, just before the jump
    expect(dayInZone(new Date("2026-11-01T05:30:00Z"), "America/New_York")).toBe("2026-11-01"); // 01:30 EDT, the first of two
  });
  it("labels a workout time with its own zone only when that differs from where the athlete is now", () => {
    setActiveZone("Europe/Paris");
    const t = "2026-05-12T10:00:00Z";
    expect(formatInstantTime(t, "Asia/Tokyo")).toContain("· Tokyo");
    expect(formatInstantTime(t, "Europe/Paris")).not.toContain("·");
  });
  it("ignores an unknown zone instead of throwing", () => {
    setActiveZone("Not/AZone");
    expect(zonedTodayISO()).toMatch(/^\d{4}-\d\d-\d\d$/);
  });
  it("gives readable labels", () => {
    expect(zoneLabel("America/New_York")).toBe("New York");
    expect(zoneLabel("+09:00")).toBe("UTC+09:00");
  });
});
