import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./deployment", () => ({ isPublic: true }));
vi.mock("./supabase", () => ({ accessToken: async () => "tok", refreshedAccessToken: async () => null }));

import { authedFetch } from "./authedFetch";

afterEach(() => vi.restoreAllMocks());

describe("authedFetch on the public build", () => {
  it("omits cookies by default", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    await authedFetch("/api/today");
    expect(spy.mock.calls[0][1]?.credentials).toBe("omit");
  });

  it("lets a call keep the cookie the server sets (the OAuth state cookie)", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    await authedFetch("/api/connections/withings/oauth/start", { method: "POST", credentials: "same-origin" });
    expect(spy.mock.calls[0][1]?.credentials).toBe("same-origin");
    expect(new Headers(spy.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer tok");
  });
});
