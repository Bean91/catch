import type { ConnectionCard, ConnectionStatus } from "./types";

// Every status is a word AND a glyph, never colour alone (DESIGN.md "Provider connections").
export const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: "Connected",
  needs_reconnect: "Reconnect needed",
  error: "Problem syncing",
  rate_limited: "Waiting — provider is rate limiting",
  disconnected: "Not connected",
};

export const STATUS_GLYPH: Record<ConnectionStatus, string> = {
  connected: "●",
  needs_reconnect: "✕",
  error: "!",
  rate_limited: "!",
  disconnected: "○",
};

export function statusTone(status: ConnectionStatus): "good" | "bad" | "warn" | "quiet" {
  if (status === "connected") return "good";
  if (status === "needs_reconnect") return "bad";
  if (status === "disconnected") return "quiet";
  return "warn";
}

/** The label for the pill: a connected account that is still importing history says so. */
export function statusLabel(card: ConnectionCard): string {
  if (card.connected && card.status === "connected" && card.importing_history_from) return "Connected — importing history";
  return STATUS_LABEL[card.status];
}

/** What to do about a broken connection, in words. Fixed copy: provider text is never shown. */
export function recoveryText(card: ConnectionCard): string | null {
  if (card.status === "needs_reconnect") {
    if (card.provider === "garmin") {
      return "Garmin rejected the key — it has probably expired or was deleted. Create a new Personal API key in Garmin Connect and choose Replace key.";
    }
    if (card.auth_method === "personal_token") {
      return "Concept2 rejected the saved token. Create a new one under Edit Profile → Applications in your Logbook and choose Replace token.";
    }
    return `${card.label} no longer accepts the saved authorization (it expired or was removed). Choose Reconnect and approve access again.`;
  }
  if (card.status === "rate_limited") return `${card.label} is asking Catch to slow down. Catch will retry on its own; nothing needs doing.`;
  if (card.status === "error") return "The last sync failed. Catch retries with increasing pauses; if it keeps failing, use Test connection.";
  return null;
}

/** "Key …abcd" for a long key, "Key saved" when the server (rightly) sent nothing to show. */
export function maskedCredential(card: ConnectionCard): string {
  const noun = card.auth_method === "personal_token" ? "Token" : "Key";
  return card.last4 ? `${noun} …${card.last4}` : `${noun} saved`;
}

export function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  return Math.ceil((new Date(iso + "T00:00:00").getTime() - Date.now()) / 86_400_000);
}

export const GARMIN_KEY_PAGE_URL = "https://connect.garmin.com/app/settings/personalApiToken";
export const CONCEPT2_TOKEN_HELP = "Log in at log.concept2.com, then Edit Profile → Applications → Concept2 Logbook API integration.";

export const CAPABILITY_LABEL: Record<string, string> = {
  activities: "Activities",
  activity_fit_files: "Activity files (heart-rate, GPS)",
  daily_summaries: "Daily summaries",
  sleep: "Sleep",
  heart_rate_variability: "Heart-rate variability",
  respiration: "Respiration",
  spo2: "Blood oxygen",
  weight: "Weight",
  skin_temperature: "Skin temperature",
  body_composition: "Body composition",
  results: "Workout results",
  strokes: "Stroke data",
  recovery: "Recovery",
  workouts: "Workouts",
  push_or_webhooks: "Instant updates (push)",
  documented_rate_limits: "Published rate limits",
  documented_history_depth: "Published history depth",
  token_revocation: "Revocation by Catch",
};
