import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { webBase } from "./apiBase";
import { emitDeepLink, onDeepLink } from "./deepLinkBus";
import { resolveDeepLink, type DeepLinkTarget } from "./deepLinkTargets";
import { isNative } from "./platform";

const DEDUPE_MS = 2_000;

async function exchangeAuthCode(code: string): Promise<void> {
  // PKCE: the code verifier was stored by this same app (secure storage) when the sign-up/recovery email was requested,
  // so only the app that asked can finish the exchange. AuthProvider's onAuthStateChange picks up the resulting session.
  const { getAuthClient } = await import("../supabase");
  const { error } = await (await getAuthClient()).exchangeCodeForSession(code);
  if (error) console.warn("auth link could not be used:", error.message);
}

/** Routes links opened from outside the app (universal/app links, the OAuth return, notification taps) into the router.
 * A target that arrives before sign-in is held and used once, so a notification tapped from a locked-out state still lands
 * on the right screen after login instead of on whatever the login redirect picks. */
export function useDeepLinks(): void {
  const navigate = useNavigate();
  const { status } = useAuth();
  const statusRef = useRef(status);
  statusRef.current = status;
  const pending = useRef<string | null>(null);

  useEffect(() => {
    return onDeepLink((t: DeepLinkTarget) => {
      if (t.kind === "auth") {
        void exchangeAuthCode(t.code);
        return;
      }
      if (t.kind === "auth-error") {
        console.warn("auth link error:", t.message);
        return;
      }
      if (statusRef.current === "authed") navigate(t.to);
      else pending.current = t.to;
    });
  }, [navigate]);

  useEffect(() => {
    if (status === "authed" && pending.current) {
      const to = pending.current;
      pending.current = null;
      navigate(to);
    }
  }, [status, navigate]);

  useEffect(() => {
    if (!isNative()) return;
    let removed = false;
    let remove: (() => void) | null = null;
    let last = { url: "", at: 0 };

    void (async () => {
      const [{ App }, { Browser }] = await Promise.all([import("@capacitor/app"), import("@capacitor/browser")]);
      const [info] = await Promise.all([App.getInfo()]);
      const ctx = { hosts: webBase ? [new URL(webBase).hostname] : [], scheme: info.id };
      const take = (url: string) => {
        const now = Date.now();
        if (url === last.url && now - last.at < DEDUPE_MS) return;
        last = { url, at: now };
        const target = resolveDeepLink(url, ctx);
        if (!target) return;
        // iOS keeps the in-app Safari sheet (OAuth) open until told to close; Android returns to the app by itself.
        void Browser.close().catch(() => {});
        emitDeepLink(target);
      };
      const launch = await App.getLaunchUrl();
      if (launch?.url) take(launch.url);
      const handle = await App.addListener("appUrlOpen", (e) => take(e.url));
      if (removed) void handle.remove();
      else remove = () => void handle.remove();
    })();

    return () => {
      removed = true;
      remove?.();
    };
  }, []);
}
