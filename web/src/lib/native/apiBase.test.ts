import { describe, expect, it, vi } from "vitest";

describe("apiUrl", () => {
  it("leaves paths alone on the web", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_CATCH_NATIVE", "");
    vi.stubGlobal("window", { location: { origin: "https://web.example.com" } });
    const { apiUrl, publicOrigin } = await import("./apiBase");
    expect(apiUrl("/api/today")).toBe("/api/today");
    expect(publicOrigin()).toBe("https://web.example.com");
  });

  it("prefixes server paths in a native build and never doubles a slash", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_CATCH_NATIVE", "1");
    vi.stubEnv("VITE_API_BASE_URL", "https://catch.example.com/");
    vi.stubEnv("VITE_WEB_BASE_URL", "https://catch.example.com");
    const { apiUrl, publicOrigin } = await import("./apiBase");
    expect(apiUrl("/api/today")).toBe("https://catch.example.com/api/today");
    expect(apiUrl("https://other.example.com/x")).toBe("https://other.example.com/x");
    expect(apiUrl("blob:abc")).toBe("blob:abc");
    expect(publicOrigin()).toBe("https://catch.example.com");
  });
});
