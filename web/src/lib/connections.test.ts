import { describe, expect, it } from "vitest";
import { maskedCredential, recoveryText, statusLabel, statusTone } from "./connections";
import type { ConnectionCard } from "./types";

const base = {
  provider: "garmin",
  label: "Garmin",
  auth_methods: ["api_key"],
  available: true,
  oauth_available: false,
  connected: true,
  status: "connected",
  status_detail: null,
  status_text: null,
  from_environment: false,
  auth_method: "api_key",
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
  capabilities: {},
  limitations: [],
  notes: "",
} as ConnectionCard;

describe("connection copy", () => {
  it("never shows more than the server sent, and says 'saved' for a short key", () => {
    expect(maskedCredential({ ...base, last4: "9f3a" })).toBe("Key …9f3a");
    expect(maskedCredential(base)).toBe("Key saved");
    expect(maskedCredential({ ...base, auth_method: "personal_token" })).toBe("Token saved");
  });

  it("says what to do for each broken state, in words", () => {
    const needs = recoveryText({ ...base, status: "needs_reconnect" });
    expect(needs).toContain("Create a new Personal API key");
    expect(recoveryText({ ...base, provider: "whoop", label: "Whoop", auth_method: "oauth", status: "needs_reconnect" })).toContain("Choose Reconnect");
    expect(recoveryText({ ...base, status: "rate_limited" })).toContain("nothing needs doing");
    expect(recoveryText(base)).toBeNull();
  });

  it("labels an import in progress and keeps tone separate from colour", () => {
    expect(statusLabel({ ...base, importing_history_from: "2026-10-01" })).toBe("Connected — importing history");
    expect(statusTone("needs_reconnect")).toBe("bad");
    expect(statusTone("disconnected")).toBe("quiet");
  });
});
