import type { AiErrorKind, AiProviderCard, AiProviderStatus, CoachProviderName } from "./types";

// Every status is a word AND a glyph, never colour alone (DESIGN.md "AI providers").
export const STATUS_LABEL: Record<AiProviderStatus, string> = {
  valid: "Connected",
  configured: "Saved — not checked yet",
  invalid: "Invalid key",
  unavailable: "Unavailable",
  not_configured: "Not configured",
};

export const STATUS_GLYPH: Record<AiProviderStatus, string> = {
  valid: "●",
  configured: "◐",
  invalid: "✕",
  unavailable: "!",
  not_configured: "○",
};

export function statusTone(status: AiProviderStatus): "good" | "bad" | "warn" | "quiet" {
  if (status === "valid") return "good";
  if (status === "invalid") return "bad";
  if (status === "unavailable") return "warn";
  return "quiet";
}

const DETAIL_TEXT: Record<string, string> = {
  rejected_by_provider: "The provider rejected this key. Replace it, or switch to another provider.",
  rate_limited: "The provider is rate-limiting this key right now.",
  quota_exceeded: "The provider reports this account is out of quota or credit.",
  provider_unreachable: "Catch couldn't reach the provider.",
  timed_out: "The provider took too long to answer.",
};

export function statusDetailText(card: AiProviderCard): string | null {
  return card.status_detail ? (DETAIL_TEXT[card.status_detail] ?? null) : null;
}

/** "…abcd" for a long key, "Key saved" when the server (rightly) sent nothing to show. */
export function maskedKey(last4: string | null): string {
  return last4 ? `…${last4}` : "Key saved";
}

export function errorKindMessage(kind: AiErrorKind | null | undefined): string | null {
  if (kind === "invalid_key") return "This key was rejected. Replace it in Settings → AI Providers.";
  if (kind === "quota") return "This account is out of quota or credit.";
  return null;
}

/** Providers the user could switch to right now (configured, and not the one that just failed). */
export function switchTargets(cards: AiProviderCard[], current: CoachProviderName): AiProviderCard[] {
  return cards.filter((c) => c.configured && c.id !== current);
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
