import { describe, expect, it } from "vitest";
import { mockQueryAllowed } from "./mock";

describe("mockQueryAllowed (launch audit L-03)", () => {
  it("ignores ?mock in a public production bundle", () => {
    expect(mockQueryAllowed("public", false, undefined)).toBe(false);
    expect(mockQueryAllowed("public", false, "0")).toBe(false);
  });
  it("allows it in the public dev server or an explicitly allowed test bundle", () => {
    expect(mockQueryAllowed("public", true, undefined)).toBe(true);
    expect(mockQueryAllowed("public", false, "1")).toBe(true);
  });
  it("leaves the personal build's fixture mode alone", () => {
    expect(mockQueryAllowed(undefined, false, undefined)).toBe(true);
    expect(mockQueryAllowed("personal", false, undefined)).toBe(true);
  });
});
