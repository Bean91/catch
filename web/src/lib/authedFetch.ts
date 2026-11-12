import { isPublic } from "./deployment";
import { accessToken, refreshedAccessToken } from "./supabase";

// A session cookie can expire mid-visit (30-day max age, but still). AuthProvider listens
// for this so a stale session drops the user back to the login screen instead of leaving
// every card stuck on "Couldn't load" with a Retry button that will never succeed.
export const UNAUTHORIZED_EVENT = "catch:unauthorized";

/** The one place the app talks to its own API. Personal build: the login cookie. Public build: the Supabase access
 * token in the Authorization header — refreshed once and retried on a 401 (an expired token, or one revoked since the
 * last refresh), and only then is the person sent back to sign in. */
export async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  if (!isPublic) return fetch(input, { credentials: "include", ...init });

  const send = (token: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return fetch(input, { ...init, headers, credentials: "omit" });
  };
  const token = await accessToken();
  if (!token) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    return new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401, headers: { "Content-Type": "application/json" } });
  }
  let res = await send(token);
  if (res.status === 401) {
    const fresh = await refreshedAccessToken();
    if (fresh) res = await send(fresh);
  }
  return res;
}
