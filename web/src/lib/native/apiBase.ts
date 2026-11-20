// The web app and the personal install call their own origin with relative paths. A native shell's origin is
// capacitor://localhost (iOS) / https://localhost (Android), so every request needs the deployment's absolute address.
// On the web both constants are "" and every helper returns its input unchanged.
const trim = (v: string | undefined): string => (v ?? "").replace(/\/$/, "");

export const apiBase: string = import.meta.env.VITE_CATCH_NATIVE === "1" ? trim(import.meta.env.VITE_API_BASE_URL) : "";

/** The address people (and other apps) use to reach the deployment: invite links, email redirects, association files. */
export const webBase: string = import.meta.env.VITE_CATCH_NATIVE === "1" ? trim(import.meta.env.VITE_WEB_BASE_URL) : "";

/** A server path ("/api/…", "/auth/…") as a URL the current shell can fetch. Absolute URLs pass through. */
export function apiUrl(path: string): string {
  if (!apiBase || !path.startsWith("/")) return path;
  return `${apiBase}${path}`;
}

/** The public origin for links meant to be shared or opened elsewhere (not for fetches). */
export function publicOrigin(): string {
  return webBase || window.location.origin;
}
