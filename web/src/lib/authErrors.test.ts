import { describe, expect, it } from "vitest";
import { describeAuthError, passwordProblem } from "./authErrors";

describe("describeAuthError", () => {
  it("does not reveal whether an address is registered", () => {
    const wrong = describeAuthError({ code: "invalid_credentials", status: 400 }, "signin");
    const unknown = describeAuthError({ code: "user_not_found", status: 400 }, "signin");
    expect(wrong).toBe(unknown);
    const dupe = describeAuthError({ code: "user_already_exists" }, "signup");
    expect(dupe).toMatch(/If you already have one/);
  });
  it("is specific only where it helps", () => {
    expect(describeAuthError({ code: "email_not_confirmed" }, "signin")).toMatch(/Confirm your email/);
    expect(describeAuthError({ status: 429 }, "reset")).toMatch(/Too many/);
    expect(describeAuthError({ code: "weak_password" }, "signup")).toMatch(/too weak/);
    expect(describeAuthError(null, "update")).toMatch(/expired/);
  });
});

describe("passwordProblem", () => {
  it("requires 8 characters", () => {
    expect(passwordProblem("short")).not.toBeNull();
    expect(passwordProblem("long-enough")).toBeNull();
  });
});
