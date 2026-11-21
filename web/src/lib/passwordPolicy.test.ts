import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MIN_PASSWORD_LENGTH, PASSWORD_RULES, PASSWORD_SYMBOLS, unmetRules } from "./passwordPolicy";

// The one policy file the backend docs test also reads (tests/test_password_policy.py): the browser's checklist must agree with what
// Supabase Auth enforces, or people see a ticked list and then a "weak password" error.
const fixture = JSON.parse(readFileSync(fileURLToPath(new URL("../../../tests/fixtures/auth/password_policy.json", import.meta.url)), "utf8"));

describe("password policy", () => {
  it("matches the shared fixture", () => {
    expect(MIN_PASSWORD_LENGTH).toBe(fixture.min_length);
    expect(PASSWORD_RULES.map((r) => r.id)).toEqual(fixture.rules);
    expect(PASSWORD_SYMBOLS).toBe(fixture.symbols);
  });
  it("accepts the valid vectors and names exactly the missed rule for the invalid ones", () => {
    for (const p of fixture.vectors.valid as string[]) expect(unmetRules(p)).toEqual([]);
    for (const [p, rule] of Object.entries(fixture.vectors.invalid as Record<string, string>)) expect(unmetRules(p)).toEqual([rule]);
  });
  it("does not count a space or an accented letter as a symbol", () => {
    expect(unmetRules("Abcdefg 1")).toContain("symbol");
    expect(unmetRules("Abcdéfg1")).toContain("symbol");
  });
});
