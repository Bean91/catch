import { describe, expect, it } from "vitest";
import { snapshotUsable } from "./queryPersist";

const now = Date.parse("2026-11-22T12:00:00Z");
const fresh = { v: 2, build: "build-b", uid: "user-a", at: now - 60_000 };

describe("snapshotUsable", () => {
  it("restores the same build's snapshot for the same person", () => {
    expect(snapshotUsable(fresh, "user-a", "build-b", now)).toBe(true);
  });

  it("drops a snapshot written by another build (an app update), even a minute old", () => {
    expect(snapshotUsable({ ...fresh, build: "build-a" }, "user-a", "build-b", now)).toBe(false);
  });

  it("drops a snapshot from before builds were recorded", () => {
    expect(snapshotUsable({ v: 1, uid: "user-a", at: now - 60_000 }, "user-a", "build-b", now)).toBe(false);
  });

  it("drops someone else's or a week-old snapshot, and handles none", () => {
    expect(snapshotUsable(fresh, "user-b", "build-b", now)).toBe(false);
    expect(snapshotUsable({ ...fresh, at: now - 8 * 24 * 3600_000 }, "user-a", "build-b", now)).toBe(false);
    expect(snapshotUsable(null, "user-a", "build-b", now)).toBe(false);
  });
});
