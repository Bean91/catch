import type { AiModelsResponse, AiProviderCard, AiProvidersResponse, AiTestResult, AiUsage, CoachProviderName } from "./types";

// Mock state for Settings → AI Providers (?mock=1). All four card states appear at once:
// Anthropic connected + active, OpenAI invalid, Gemini not configured, Ollama unavailable.
const CAPS = { streaming: true, tools: true, vision: true, list_models: true, validate_key: true, reports_balance: false };

function base(id: CoachProviderName, label: string, hint: string, docs: string, needsKey = true): AiProviderCard {
  return {
    id,
    label,
    needs_key: needsKey,
    key_hint: hint,
    docs_url: docs,
    capabilities: CAPS,
    configured: false,
    last4: null,
    status: "not_configured",
    status_detail: null,
    status_checked_at: null,
    model: null,
    base_url: null,
    active: false,
  };
}

let cards: AiProviderCard[] = [
  { ...base("anthropic", "Anthropic", "sk-ant-…", "https://console.anthropic.com/settings/keys"), configured: true, last4: "wxyz", status: "valid", model: "claude-sonnet-5", active: true },
  { ...base("openai", "OpenAI", "sk-…", "https://platform.openai.com/api-keys"), configured: true, last4: "4f2a", status: "invalid", status_detail: "rejected_by_provider", model: "gpt-5-mini" },
  base("gemini", "Google Gemini", "AIza…", "https://aistudio.google.com/app/apikey"),
  { ...base("ollama", "Ollama (local)", "", "https://ollama.com", false), configured: true, status: "unavailable", status_detail: "provider_unreachable", base_url: "http://laptop.tailnet:11434", model: "llama3.1:70b" },
];

const MODELS: Record<CoachProviderName, { id: string; display_name: string; vision: boolean | null }[]> = {
  anthropic: [
    { id: "claude-opus-5", display_name: "Claude Opus 5", vision: true },
    { id: "claude-sonnet-5", display_name: "Claude Sonnet 5", vision: true },
    { id: "claude-haiku-4-5", display_name: "Claude Haiku 4.5", vision: true },
  ],
  openai: [
    { id: "gpt-5", display_name: "gpt-5", vision: true },
    { id: "gpt-5-mini", display_name: "gpt-5-mini", vision: true },
  ],
  gemini: [
    { id: "gemini-2.5-pro", display_name: "Gemini 2.5 Pro", vision: true },
    { id: "gemini-2.5-flash", display_name: "Gemini 2.5 Flash", vision: true },
  ],
  ollama: [
    { id: "llama3.1:70b", display_name: "llama3.1:70b", vision: false },
    { id: "qwen2.5vl:7b", display_name: "qwen2.5vl:7b", vision: true },
  ],
};

export class MockAiError extends Error {}

function snapshot(): AiProvidersResponse {
  const active = cards.find((c) => c.active && c.configured)?.id ?? null;
  const activeCard = cards.find((c) => c.id === active);
  return {
    active,
    providers: cards.map((c) => ({ ...c })),
    vision: {
      available: !!activeCard && !!activeCard.model,
      provider: active ?? "anthropic",
      reason: !activeCard ? "not_configured" : !activeCard.model ? "no_model" : null,
    },
  };
}

export function mockAiProviders(): AiProvidersResponse {
  return snapshot();
}

export function mockPutAiKey(provider: CoachProviderName, key: string): AiProviderCard {
  if (key.trim().toLowerCase().startsWith("bad")) throw new MockAiError("The provider rejected this API key. It may be wrong, expired or revoked.");
  cards = cards.map((c) =>
    c.id === provider ? { ...c, configured: true, last4: key.length >= 12 ? key.slice(-4) : null, status: "valid", status_detail: null, status_checked_at: new Date().toISOString() } : c,
  );
  return cards.find((c) => c.id === provider)!;
}

export function mockDeleteAiKey(provider: CoachProviderName): AiProvidersResponse {
  cards = cards.map((c) => (c.id === provider ? { ...c, configured: false, last4: null, status: "not_configured", status_detail: null, active: false } : c));
  return snapshot();
}

export function mockTestAiProvider(provider: CoachProviderName): AiTestResult {
  const card = cards.find((c) => c.id === provider)!;
  if (!card.configured) return { ok: false, kind: "invalid_key", message: "AI features need a configured provider. Add a key in Settings → AI Providers.", model_count: null };
  if (card.status === "invalid") return { ok: false, kind: "invalid_key", message: "The provider rejected this API key. It may be wrong, expired or revoked — replace it in Settings → AI Providers.", model_count: null };
  if (card.id === "ollama") return { ok: false, kind: "unavailable", message: "Could not reach Ollama at the configured URL", model_count: null };
  cards = cards.map((c) => (c.id === provider ? { ...c, status: "valid", status_detail: null, status_checked_at: new Date().toISOString() } : c));
  return { ok: true, kind: null, message: "Connected", model_count: MODELS[provider].length };
}

export function mockAiModels(provider: CoachProviderName): AiModelsResponse {
  const card = cards.find((c) => c.id === provider)!;
  if (!card.configured) return { models: [], error: "AI features need a configured provider.", kind: "invalid_key" };
  if (card.status === "unavailable" || card.status === "invalid") return { models: [], error: "Couldn't load models from this provider right now.", kind: "unavailable" };
  return { models: MODELS[provider], error: null, kind: null };
}

export function mockSetActive(provider: CoachProviderName, model?: string): AiProvidersResponse {
  const target = cards.find((c) => c.id === provider);
  if (!target?.configured) throw new MockAiError(`${target?.label ?? "That provider"} isn't set up yet.`);
  cards = cards.map((c) => ({ ...c, active: c.id === provider, model: c.id === provider && model ? model : c.model }));
  return snapshot();
}

export function mockAiUsage(): AiUsage {
  return {
    days: 30,
    by_provider: {
      anthropic: { tokens: 184_300, cost_usd: 0.42, turns: 31, unpriced_turns: 0 },
      openai: { tokens: 22_000, cost_usd: 0, turns: 4, unpriced_turns: 4 },
    },
    today: { spend_usd: 0.42, tokens: 21_400, cap_usd: 2, token_cap: null },
    provider_balance: null,
    source: "recorded_by_catch",
  };
}
