import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, UNAUTHORIZED_EVENT, fetchSyncStatus, isMock, login as apiLogin, logout as apiLogout } from "./api";
import { isPublic } from "./deployment";
import { clearLocalUserState, rememberUser } from "./session";

// "recovery": the person followed a password-reset link and must choose a new password before anything else.
type AuthStatus = "checking" | "authed" | "anon" | "recovery";

export interface SignUpResult {
  /** True when the project requires email confirmation first (no session was issued). */
  needsConfirmation: boolean;
}

interface AuthContextValue {
  status: AuthStatus;
  /** The personal install signs in with a password alone; the public one with an email too. */
  login: (password: string, email?: string) => Promise<void>;
  logout: (everywhere?: boolean) => Promise<void>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  sendPasswordReset: (email: string) => Promise<void>;
  setNewPassword: (password: string) => Promise<void>;
  email: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const LAST_AUTHED_KEY = "catch:lastAuthed";

function rememberAuthed(authed: boolean) {
  try {
    if (authed) localStorage.setItem(LAST_AUTHED_KEY, "1");
    else localStorage.removeItem(LAST_AUTHED_KEY);
  } catch {
    // Private browsing / blocked storage — the offline-reload optimism below just won't apply.
  }
}

function wasLastAuthed(): boolean {
  try {
    return localStorage.getItem(LAST_AUTHED_KEY) === "1";
  } catch {
    return false;
  }
}

const unsupported = () => Promise.reject(new Error("Not available on a personal install"));

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(isMock ? "authed" : "checking");
  const [email, setEmail] = useState<string | null>(null);

  // --- personal install: the login cookie ---------------------------------------------------------------------------
  useEffect(() => {
    if (isMock || isPublic) return;
    // No /api/me endpoint exists on the Pi — probe with a lightweight authenticated route instead of
    // duplicating session-cookie verification logic in the frontend. Only a real 401 means
    // "anon" — a network failure (reloading offline, no connectivity yet) must not drop a
    // previously-authed session back to the login screen, or the offline shell can never show
    // the service worker's cached Today data.
    fetchSyncStatus()
      .then(() => {
        rememberAuthed(true);
        setStatus("authed");
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          rememberAuthed(false);
          setStatus("anon");
        } else {
          setStatus(wasLastAuthed() ? "authed" : "anon");
        }
      });
  }, []);

  // --- public deployment: Supabase Auth ----------------------------------------------------------------------------
  useEffect(() => {
    if (isMock || !isPublic) return;
    let unsubscribe: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const { getAuthClient } = await import("./supabase");
      const client = await getAuthClient();
      const { data: sub } = client.onAuthStateChange((event, session) => {
        // Never call back into the auth client synchronously from this handler (it holds a lock): defer.
        setTimeout(async () => {
          if (cancelled) return;
          if (event === "PASSWORD_RECOVERY") {
            setStatus("recovery");
            return;
          }
          if (event === "SIGNED_OUT" || !session) {
            await clearLocalUserState();
            setEmail(null);
            setStatus("anon");
            return;
          }
          await rememberUser(session.user.id);
          setEmail(session.user.email ?? null);
          setStatus((current) => (current === "recovery" ? current : "authed"));
        }, 0);
      });
      unsubscribe = () => sub.subscription.unsubscribe();
      const { data } = await client.getSession();
      if (cancelled) return;
      if (data.session) {
        await rememberUser(data.session.user.id);
        setEmail(data.session.user.email ?? null);
        setStatus((current) => (current === "recovery" ? current : "authed"));
      } else {
        setStatus((current) => (current === "recovery" ? current : "anon"));
      }
    })().catch(() => setStatus((current) => (current === "checking" ? "anon" : current)));
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, []);

  // A 401 from the API that a token refresh couldn't fix (session revoked: signed out elsewhere, or the account is
  // gone) ends the local session too, so the person lands on sign-in instead of a screen of Retry buttons.
  useEffect(() => {
    if (isMock) return;
    const onUnauthorized = async () => {
      if (isPublic) {
        const { getAuthClient } = await import("./supabase");
        await (await getAuthClient()).signOut({ scope: "local" }).catch(() => undefined);
        await clearLocalUserState();
      } else {
        rememberAuthed(false);
      }
      setStatus("anon");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (password: string, emailAddress?: string) => {
    if (isPublic) {
      const { getAuthClient } = await import("./supabase");
      const { error } = await (await getAuthClient()).signInWithPassword({ email: emailAddress ?? "", password });
      if (error) throw error;
      return; // onAuthStateChange moves the status
    }
    await apiLogin(password);
    rememberAuthed(true);
    setStatus("authed");
  }, []);

  const logout = useCallback(async (everywhere = false) => {
    if (isPublic) {
      const { getAuthClient } = await import("./supabase");
      // scope "global" ends every session of this account; the default ends this device's only.
      await (await getAuthClient()).signOut({ scope: everywhere ? "global" : "local" });
      await clearLocalUserState();
      setStatus("anon");
      return;
    }
    await apiLogout();
    rememberAuthed(false);
    setStatus("anon");
  }, []);

  const signUp = useCallback(async (emailAddress: string, password: string): Promise<SignUpResult> => {
    if (!isPublic) return unsupported();
    const { getAuthClient } = await import("./supabase");
    const { data, error } = await (await getAuthClient()).signUp({
      email: emailAddress,
      password,
      options: { emailRedirectTo: window.location.origin },
    });
    if (error) throw error;
    return { needsConfirmation: !data.session };
  }, []);

  const sendPasswordReset = useCallback(async (emailAddress: string) => {
    if (!isPublic) return unsupported();
    const { getAuthClient } = await import("./supabase");
    const { error } = await (await getAuthClient()).resetPasswordForEmail(emailAddress, { redirectTo: window.location.origin });
    if (error) throw error;
  }, []);

  const setNewPassword = useCallback(async (password: string) => {
    if (!isPublic) return unsupported();
    const { getAuthClient } = await import("./supabase");
    const { error } = await (await getAuthClient()).updateUser({ password });
    if (error) throw error;
    setStatus("authed");
  }, []);

  const value = useMemo(
    () => ({ status, login, logout, signUp, sendPasswordReset, setNewPassword, email }),
    [status, login, logout, signUp, sendPasswordReset, setNewPassword, email],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
