import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, UNAUTHORIZED_EVENT, fetchSyncStatus, isMock, login as apiLogin, logout as apiLogout } from "./api";

type AuthStatus = "checking" | "authed" | "anon";

interface AuthContextValue {
  status: AuthStatus;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(isMock ? "authed" : "checking");

  useEffect(() => {
    if (isMock) return;
    // No /api/me endpoint exists — probe with a lightweight authenticated route instead of
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

  useEffect(() => {
    if (isMock) return;
    // A session cookie expiring mid-visit shouldn't leave every card stuck on a Retry
    // button that can never succeed — drop back to the login screen instead.
    const onUnauthorized = () => {
      rememberAuthed(false);
      setStatus("anon");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  async function login(password: string) {
    await apiLogin(password);
    rememberAuthed(true);
    setStatus("authed");
  }

  async function logout() {
    await apiLogout();
    rememberAuthed(false);
    setStatus("anon");
  }

  return <AuthContext.Provider value={{ status, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
