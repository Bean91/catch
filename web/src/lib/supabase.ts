import type { AuthChangeEvent, GoTrueClient, Session } from "@supabase/auth-js";
import { supabasePublishableKey, supabaseUrl } from "./deployment";

// The browser holds a session for the Supabase Auth project and nothing else: it sends the access token to Catch's own
// API in the Authorization header. Supported session handling only — auth-js stores the session, refreshes it shortly
// before expiry (autoRefreshToken), and shares sign-in/out across tabs.
//
// Storage: an SPA with a separate API has no httpOnly-cookie option without a server-side session proxy, so auth-js's
// default (localStorage) is used. The exposure is XSS; the mitigations are a short access-token lifetime (Supabase's
// default 1 h), PKCE, no third-party scripts, the strict CSP the host should send (docs/public-setup.md), and clearing
// every local trace on sign-out (lib/session.ts).
let client: Promise<GoTrueClient> | null = null;

export function getAuthClient(): Promise<GoTrueClient> {
  // Read straight from import.meta.env (not via an imported constant) so the bundler folds it to a literal in THIS
  // module and drops the dynamic import — auth-js is then absent from a personal build, not just unused.
  if (import.meta.env.VITE_CATCH_DEPLOYMENT !== "public") return Promise.reject(new Error("Supabase Auth is not part of a personal build"));
  client ??= import("@supabase/auth-js").then(
    ({ GoTrueClient }) =>
      new GoTrueClient({
        url: `${supabaseUrl}/auth/v1`,
        headers: { apikey: supabasePublishableKey },
        storageKey: "catch.auth",
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
        flowType: "pkce",
      }),
  );
  return client;
}

export async function currentSession(): Promise<Session | null> {
  const { data } = await (await getAuthClient()).getSession();
  return data.session;
}

export async function accessToken(): Promise<string | null> {
  return (await currentSession())?.access_token ?? null;
}

/** Forces a refresh (after a 401); returns the new token, or null if the refresh token is no longer good. */
export async function refreshedAccessToken(): Promise<string | null> {
  const { data, error } = await (await getAuthClient()).refreshSession();
  return error ? null : (data.session?.access_token ?? null);
}

export type { AuthChangeEvent, Session };
