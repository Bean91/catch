// Session 30 (docs/mobile/deep-links.md). Pure: turns an incoming URL — a universal/app link, the app's custom scheme (OAuth
// return), or a notification's `url` — into either an in-app route or a Supabase auth code. Everything arriving from outside
// the app is untrusted, so only an allow-list of routes is ever navigated to; anything else lands on Today.

export type DeepLinkTarget =
  | { kind: "route"; to: string }
  | { kind: "auth"; code: string }
  | { kind: "auth-error"; message: string };

const ID = "[A-Za-z0-9_-]{1,64}";
// Query parameters a target page actually reads. Nothing else is carried through.
const ROUTES: { pattern: RegExp; keepQuery?: string[]; keepHash?: boolean }[] = [
  { pattern: /^\/$/ },
  { pattern: /^\/checkin$/ },
  { pattern: /^\/calendar$/ },
  { pattern: /^\/calendar\/plan$/ },
  { pattern: new RegExp(`^/calendar/events/${ID}$`) },
  { pattern: /^\/workouts$/ },
  { pattern: new RegExp(`^/workouts/${ID}$`) },
  { pattern: /^\/gym$/ },
  { pattern: /^\/coach$/ },
  { pattern: /^\/nutrition$/ },
  { pattern: /^\/trends$/ },
  { pattern: /^\/clubs$/ },
  { pattern: /^\/clubs\/join$/, keepHash: true },
  { pattern: new RegExp(`^/clubs/${ID}$`) },
  { pattern: /^\/settings\/connections$/, keepQuery: ["provider", "result"] },
  { pattern: /^\/settings\/health$/ },
  { pattern: /^\/settings\/status$/ },
  { pattern: /^\/settings\/privacy$/ },
  { pattern: /^\/settings$/ },
];

export interface DeepLinkContext {
  /** Hostnames whose https links belong to this app (the deployment's own). */
  hosts: string[];
  /** The app's custom URL scheme (its bundle/application id), used for the OAuth return. */
  scheme: string;
}

const HOME: DeepLinkTarget = { kind: "route", to: "/" };

function routeFor(path: string, params: URLSearchParams, hash: string): DeepLinkTarget {
  const clean = path.length > 1 ? path.replace(/\/+$/, "") : path;
  for (const r of ROUTES) {
    if (!r.pattern.test(clean)) continue;
    const kept = new URLSearchParams();
    for (const k of r.keepQuery ?? []) {
      const v = params.get(k);
      if (v && /^[A-Za-z0-9_.-]{1,40}$/.test(v)) kept.set(k, v);
    }
    const q = kept.toString();
    return { kind: "route", to: `${clean}${q ? `?${q}` : ""}${r.keepHash && /^#[A-Za-z0-9_.~-]{1,512}$/.test(hash) ? hash : ""}` };
  }
  return HOME;
}

/** A notification payload carries a relative app path ("/calendar/events/7"); same allow-list, no host to check. */
export function resolveNotificationPath(url: unknown): DeepLinkTarget {
  if (typeof url !== "string" || !url.startsWith("/") || url.startsWith("//")) return HOME;
  try {
    const u = new URL(url, "https://app.invalid");
    return routeFor(u.pathname, u.searchParams, u.hash);
  } catch {
    return HOME;
  }
}

/** Null = not ours, ignore it. */
export function resolveDeepLink(raw: string, ctx: DeepLinkContext): DeepLinkTarget | null {
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    return null;
  }
  const protocol = u.protocol.replace(/:$/, "").toLowerCase();

  if (protocol === "https") {
    if (!ctx.hosts.includes(u.hostname.toLowerCase())) return null;
  } else if (protocol !== ctx.scheme.toLowerCase()) {
    return null;
  }

  const code = u.searchParams.get("code");
  if (code && /^[A-Za-z0-9._~-]{8,512}$/.test(code)) return { kind: "auth", code };
  const err = u.searchParams.get("error_description") ?? u.searchParams.get("error");
  if (err && (u.pathname === "/" || u.pathname === "")) return { kind: "auth-error", message: err.slice(0, 200) };

  // com.openoted.catch://settings/connections → WHATWG parses "settings" as the host.
  const path = protocol === "https" ? u.pathname || "/" : `/${u.hostname}${u.pathname}`.replace(/\/+$/, "") || "/";
  return routeFor(path, u.searchParams, u.hash);
}
