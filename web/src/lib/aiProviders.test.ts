import { describe, expect, it } from "vitest";
import { formatTokens, maskedKey, statusDetailText, STATUS_GLYPH, STATUS_LABEL, switchTargets } from "./aiProviders";
import type { AiProviderCard } from "./types";

const card = (over: Partial<AiProviderCard>): AiProviderCard => ({
  id: "openai",
  label: "OpenAI",
  needs_key: true,
  key_hint: "sk-…",
  docs_url: "",
  capabilities: { streaming: true, tools: true, vision: true, list_models: true, validate_key: true, reports_balance: false },
  configured: true,
  last4: "abcd",
  status: "valid",
  status_detail: null,
  status_checked_at: null,
  model: null,
  base_url: null,
  active: false,
  ...over,
});

describe("aiProviders helpers", () => {
  it("masks a key to its last four characters, or says only that one is saved", () => {
    expect(maskedKey("abcd")).toBe("…abcd");
    expect(maskedKey(null)).toBe("Key saved");
  });

  it("gives every status a word and a glyph", () => {
    for (const status of Object.keys(STATUS_LABEL) as (keyof typeof STATUS_LABEL)[]) {
      expect(STATUS_LABEL[status].length).toBeGreaterThan(2);
      expect(STATUS_GLYPH[status].length).toBeGreaterThan(0);
    }
  });

  it("explains an invalid key without echoing provider text", () => {
    expect(statusDetailText(card({ status: "invalid", status_detail: "rejected_by_provider" }))).toMatch(/Replace it/);
    expect(statusDetailText(card({ status_detail: "something_else" }))).toBeNull();
  });

  it("offers only other configured providers as switch targets", () => {
    const cards = [card({ id: "openai" }), card({ id: "gemini" }), card({ id: "anthropic", configured: false })];
    expect(switchTargets(cards, "openai").map((c) => c.id)).toEqual(["gemini"]);
  });

  it("formats token counts", () => {
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(12_500)).toBe("12.5k");
    expect(formatTokens(2_000_000)).toBe("2.0M");
  });
});
