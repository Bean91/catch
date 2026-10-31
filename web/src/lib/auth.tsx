import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { UNAUTHORIZED_EVENT, fetchSyncStatus, isMock, login as apiLogin, logout as apiLogout } from "./api";

type AuthStatus = "checking" | "authed" | "anon";

interface AuthContextValue {
  status: AuthStatus;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(isMock ? "authed" : "checking");

  useEffect(() => {
    if (isMock) return;
    // No /api/me endpoint exists — probe with a lightweight authenticated route instead of
    // duplicating session-cookie verification logic in the frontend.
    fetchSyncStatus()
      .then(() => setStatus("authed"))
      .catch(() => setStatus("anon"));
  }, []);

  useEffect(() => {
    if (isMock) return;
    // A session cookie expiring mid-visit shouldn't leave every card stuck on a Retry
    // button that can never succeed — drop back to the login screen instead.
    const onUnauthorized = () => setStatus("anon");
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  async function login(password: string) {
    await apiLogin(password);
    setStatus("authed");
  }

  async function logout() {
    await apiLogout();
    setStatus("anon");
  }

  return <AuthContext.Provider value={{ status, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
