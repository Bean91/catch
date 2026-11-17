import { describe, expect, it } from "vitest";
import { contextLine, verificationTone, VERIFICATION_GLYPH, VERIFICATION_LABEL } from "./leaderboards";

describe("leaderboards labels", () => {
  it("never relies on colour alone: every state has a glyph and a word", () => {
    for (const v of ["verified", "provider_linked", "unverified"] as const) {
      expect(VERIFICATION_GLYPH[v]).toBeTruthy();
      expect(VERIFICATION_LABEL[v]).toBeTruthy();
    }
    expect(verificationTone("verified")).not.toEqual(verificationTone("unverified"));
  });

  it("spells every ranking-affecting filter out in the context line", () => {
    const base = { board_key: "2000m", label: "2,000 m", ranks_by: "fastest time", age: null, weight: "any", club: null, verification: "verified" as const, ranked_athletes: 1, ties: "" };
    expect(contextLine(base)).toBe("2,000 m · Verified results only · 1 athlete");
    expect(contextLine({ ...base, age: "U16", weight: "lightweight", club: "c1", verification: "include_unverified", ranked_athletes: 12 })).toBe(
      "2,000 m · Verified ranked first, others listed separately · Age U16 · Lightweight · Club · 12 athletes",
    );
  });
});
