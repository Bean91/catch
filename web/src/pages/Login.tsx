import { useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { login } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(password);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Incorrect password." : "Could not log in. Try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4 text-text-primary">
      <form onSubmit={onSubmit} className="w-full max-w-sm rounded-lg border border-border bg-surface p-6">
        <div className="mb-6 text-center">
          <p className="font-mono-nums text-lg font-semibold tracking-wide">CATCH</p>
          <p className="mt-1 text-sm text-text-tertiary">Rowing training &amp; recovery</p>
        </div>
        <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-text-secondary">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="min-h-11 w-full rounded-md border border-border bg-bg px-3 text-text-primary outline-none focus-visible:border-accent"
        />
        {error && <p className="mt-2 text-sm text-band-red">{error}</p>}
        <button
          type="submit"
          disabled={pending || password.length === 0}
          className="mt-4 min-h-11 w-full rounded-md bg-accent text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
