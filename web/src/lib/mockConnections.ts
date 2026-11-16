import type { ConnectionCard, ConnectionsResponse, ConnectionTestResult, ProviderId, SyncResult } from "./types";

// Mock state for Settings → Connections (?mock=1). One of each state at once: Garmin connected with a key that is about to
// expire, Withings needing a reconnect, Concept2 not connected, Whoop connected and importing history. In-memory per page load.

const GARMIN_LIMITS = [
  "You create the key yourself in Garmin Connect (Settings → Personal API Key). Garmin shows it once; keys last 30, 90, 180 or 365 days, then you create a new one.",
  "Catch asks only for that key — never your Garmin password. Garmin's Personal API has no OAuth sign-in, so there is no 'Sign in with Garmin' button.",
  "Pull only: Garmin offers no push or webhooks on this API, so Catch checks periodically.",
  "Garmin publishes no rate limits or history depth for this API. Catch imports history in small windows and backs off when Garmin says to slow down.",
  "Skin temperature isn't in Garmin's Personal API.",
  "Catch can't revoke a key at Garmin: delete the key in Garmin Connect to end access. Disconnecting here removes Catch's copy.",
];
const GARMIN_NOTE =
  "Catch uses Garmin's Personal API with a key you create yourself. Garmin says that API is for an individual's own data and \"is not intended for commercial applications serving multiple end users\". You are connecting your own key to your own account; check Garmin's terms before relying on it.";

function empty(provider: ProviderId, label: string, methods: ConnectionCard["auth_methods"], limits: string[], caps: ConnectionCard["capabilities"], notes = ""): ConnectionCard {
  return {
    provider,
    label,
    auth_methods: methods,
    available: true,
    oauth_available: methods.includes("oauth"),
    connected: false,
    status: "disconnected",
    status_detail: null,
    status_text: null,
    auth_method: null,
    last4: "",
    scopes: [],
    account_connected_at: null,
    credential_expires_on: null,
    token_expires_at: null,
    last_attempt_at: null,
    last_success_at: null,
    last_error: null,
    consecutive_failures: 0,
    next_attempt_at: null,
    importing_history_from: null,
    capabilities: caps,
    limitations: limits,
    notes,
  };
}

const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
const day = (offsetDays: number) => new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);

let cards: ConnectionCard[] = [
  {
    ...empty(
      "garmin",
      "Garmin",
      ["api_key"],
      GARMIN_LIMITS,
      { activities: "yes", activity_fit_files: "yes", daily_summaries: "yes", sleep: "yes", heart_rate_variability: "yes", respiration: "yes", spo2: "yes", weight: "yes", skin_temperature: "no", push_or_webhooks: "no", documented_rate_limits: "unknown", documented_history_depth: "unknown" },
      GARMIN_NOTE,
    ),
    connected: true,
    status: "connected",
    auth_method: "api_key",
    last4: "9f3a",
    scopes: ["PERSONAL_API_WELLNESS_READ"],
    credential_expires_on: day(120),
    last_success_at: iso(-35 * 60_000),
    last_attempt_at: iso(-35 * 60_000),
  },
  {
    ...empty(
      "withings",
      "Withings",
      ["oauth"],
      [
        "You authorize on Withings' own page; Catch never sees your Withings password.",
        "Withings' API allows about 120 requests a minute across the whole Catch deployment (not per user).",
        "Withings documents no way for an app to revoke a grant. Disconnecting removes Catch's copy; remove the app in your Withings account to end access there.",
      ],
      { body_composition: "yes", weight: "yes", push_or_webhooks: "no", token_revocation: "no" },
      "Catch reads body measurements (weight and composition) only.",
    ),
    connected: true,
    status: "needs_reconnect",
    status_detail: "authorization_revoked",
    status_text: "The provider no longer accepts this authorization.",
    auth_method: "oauth",
    scopes: ["user.metrics"],
    last_success_at: iso(-3 * 86_400_000),
    last_attempt_at: iso(-3_600_000),
    last_error: "Withings refused the saved authorization. Reconnect Withings.",
  },
  empty(
    "concept2",
    "Concept2",
    ["oauth", "personal_token"],
    [
      "Connect with Concept2 (you authorize on log.concept2.com) or paste a personal token from Edit Profile → Applications. Catch asks for nothing else.",
      "Catch only reads your results; it never writes to your Logbook.",
      "Concept2 documents no way for an app to revoke access. Disconnecting removes Catch's copy; remove the application in your Logbook profile to end access there.",
      "A personal token has no documented lifetime. If Concept2 rejects it, Catch will say so and ask for a new one.",
    ],
    { results: "yes", strokes: "yes", push_or_webhooks: "no", documented_rate_limits: "no", token_revocation: "no" },
    "Concept2 says its API is not rate limited today but reserves the right to limit or remove abusive access.",
  ),
  {
    ...empty(
      "whoop",
      "Whoop",
      ["oauth"],
      [
        "You authorize on Whoop's own page; Catch never sees your Whoop password.",
        "Catch's Whoop app is limited to a small number of members until Whoop approves a higher tier, so connecting can be unavailable when that limit is reached.",
        "Whoop allows 100 requests a minute and 10,000 a day for the whole app; Catch waits and retries.",
        "Only scored records are imported. Whoop's own recovery and strain scores are reference only, never inputs.",
      ],
      { sleep: "yes", recovery: "yes", workouts: "yes", push_or_webhooks: "no", token_revocation: "yes" },
      "Whoop's refresh tokens rotate; if one is ever refused, Catch asks you to reconnect.",
    ),
    connected: true,
    status: "connected",
    status_detail: "backfilling",
    status_text: "Importing your history in small steps.",
    auth_method: "oauth",
    scopes: ["offline", "read:recovery", "read:sleep", "read:workout", "read:cycles", "read:profile", "read:body_measurement"],
    token_expires_at: iso(50 * 60_000),
    importing_history_from: day(-12),
    last_success_at: iso(-12 * 60_000),
    last_attempt_at: iso(-12 * 60_000),
  },
];

export class MockConnectionError extends Error {}

function find(provider: ProviderId): ConnectionCard {
  return cards.find((c) => c.provider === provider)!;
}

function update(provider: ProviderId, patch: Partial<ConnectionCard>): ConnectionCard {
  cards = cards.map((c) => (c.provider === provider ? { ...c, ...patch } : c));
  return find(provider);
}

export function mockProviderConnections(): ConnectionsResponse {
  return { deployment: "personal", connections: cards };
}

export function mockPutProviderCredential(provider: ProviderId, secret: string, expiresOn: string | null): ConnectionCard {
  if (secret.startsWith("bad")) {
    throw new MockConnectionError(
      provider === "garmin"
        ? "Garmin rejected the key. Create a new Personal API key at Garmin Connect and paste it in Catch."
        : "Concept2 rejected that token. Create a new one under Edit Profile → Applications.",
    );
  }
  return update(provider, {
    connected: true,
    status: "connected",
    status_detail: "backfilling",
    status_text: "Importing your history in small steps.",
    auth_method: provider === "garmin" ? "api_key" : "personal_token",
    last4: secret.length >= 12 ? secret.slice(-4) : "",
    credential_expires_on: expiresOn,
    importing_history_from: day(-30),
    last_error: null,
    consecutive_failures: 0,
  });
}

export function mockPutProviderExpiry(provider: ProviderId, expiresOn: string | null): ConnectionCard {
  return update(provider, { credential_expires_on: expiresOn });
}

export function mockStartProviderOAuth(provider: ProviderId): { authorize_url: string | null } {
  update(provider, {
    connected: true,
    status: "connected",
    status_detail: "backfilling",
    status_text: "Importing your history in small steps.",
    auth_method: "oauth",
    importing_history_from: day(-30),
    last_error: null,
    token_expires_at: iso(3_600_000),
  });
  return { authorize_url: null };
}

export function mockTestProviderConnection(provider: ProviderId): ConnectionTestResult {
  const c = find(provider);
  if (!c.connected) return { connected: false, ok: false, message: "Not connected." };
  if (c.status === "needs_reconnect") return { connected: true, ok: false, needs_reconnect: true, message: `${c.label} refused the saved authorization.` };
  return { connected: true, ok: true, message: "Connection works." };
}

export function mockSyncProvider(provider: ProviderId): SyncResult {
  const c = find(provider);
  if (!c.connected) return { source: provider, skipped: "not connected" };
  update(provider, { last_success_at: new Date().toISOString(), last_attempt_at: new Date().toISOString(), last_error: null, status: "connected" });
  return { source: provider };
}

export function mockDisconnectProvider(provider: ProviderId): { revoked: boolean; was_connected: boolean } {
  const c = find(provider);
  update(provider, {
    connected: false,
    status: "disconnected",
    status_detail: null,
    status_text: null,
    auth_method: null,
    last4: "",
    scopes: [],
    credential_expires_on: null,
    token_expires_at: null,
    last_success_at: null,
    last_attempt_at: null,
    last_error: null,
    importing_history_from: null,
  });
  return { revoked: provider === "whoop", was_connected: c.connected };
}
