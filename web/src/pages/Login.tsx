import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { describeAuthError, passwordProblem } from "../lib/authErrors";
import { isPublic } from "../lib/deployment";

const INPUT =
  "min-h-11 w-full rounded-md border border-border bg-bg px-3 text-text-primary outline-none focus-visible:border-accent";
const BUTTON =
  "mt-4 min-h-11 w-full rounded-md bg-accent text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50";
const LINK = "min-h-11 text-sm text-text-secondary underline-offset-4 hover:text-text-primary hover:underline";

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg px-4 text-text-primary">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-6">
        <div className="mb-6 text-center">
          <p className="font-mono-nums text-lg font-semibold tracking-wide">CATCH</p>
          <p className="mt-1 text-sm text-text-tertiary">Rowing training &amp; recovery</p>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field(props: { id: string; label: string; type: string; value: string; onChange: (v: string) => void; autoComplete?: string; autoFocus?: boolean }) {
  return (
    <>
      <label htmlFor={props.id} className="mb-1.5 mt-3 block text-sm font-medium text-text-secondary first:mt-0">
        {props.label}
      </label>
      <input
        id={props.id}
        type={props.type}
        autoFocus={props.autoFocus}
        autoComplete={props.autoComplete}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className={INPUT}
      />
    </>
  );
}

function PersonalLogin() {
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
    <Frame>
      <form onSubmit={onSubmit}>
        <Field id="password" label="Password" type="password" autoFocus value={password} onChange={setPassword} />
        {error && <p className="mt-2 text-sm text-band-red">{error}</p>}
        <button type="submit" disabled={pending || password.length === 0} className={BUTTON}>
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </Frame>
  );
}

type View = "signin" | "signup" | "reset" | "check-email" | "reset-sent";

function PublicAuth() {
  const { status, login, signUp, sendPasswordReset, setNewPassword } = useAuth();
  const [view, setView] = useState<View>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function run(context: "signin" | "signup" | "reset" | "update", action: () => Promise<void>) {
    setPending(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(describeAuthError(err, context));
    } finally {
      setPending(false);
    }
  }

  if (status === "recovery") {
    return (
      <Frame>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const problem = passwordProblem(password);
            if (problem) return setError(problem);
            void run("update", () => setNewPassword(password));
          }}
        >
          <p className="mb-3 text-sm text-text-secondary">Choose a new password.</p>
          <Field id="new-password" label="New password" type="password" autoComplete="new-password" autoFocus value={password} onChange={setPassword} />
          {error && <p className="mt-2 text-sm text-band-red">{error}</p>}
          <button type="submit" disabled={pending || password.length === 0} className={BUTTON}>
            {pending ? "Saving…" : "Save password"}
          </button>
        </form>
      </Frame>
    );
  }

  if (view === "check-email" || view === "reset-sent") {
    return (
      <Frame>
        <p className="text-sm text-text-secondary" role="status">
          {view === "check-email"
            ? "Check your email — we sent a link to confirm your address. Once confirmed, sign in."
            : "If that address has an account, a reset link is on its way."}
        </p>
        <button type="button" className={`${BUTTON} bg-surface-raised text-text-primary`} onClick={() => setView("signin")}>
          Back to sign in
        </button>
      </Frame>
    );
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (view === "signin") void run("signin", () => login(password, email));
    else if (view === "signup") {
      const problem = passwordProblem(password);
      if (problem) return setError(problem);
      void run("signup", async () => {
        const result = await signUp(email, password);
        if (result.needsConfirmation) setView("check-email");
      });
    } else void run("reset", async () => {
      await sendPasswordReset(email);
      setView("reset-sent"); // the same message whether or not the address exists
    });
  }

  const title = view === "signin" ? "Sign in" : view === "signup" ? "Create account" : "Reset password";
  return (
    <Frame>
      <form onSubmit={onSubmit}>
        <p className="mb-3 text-sm font-medium text-text-secondary">{title}</p>
        <Field id="email" label="Email" type="email" autoComplete="email" autoFocus value={email} onChange={setEmail} />
        {view !== "reset" && (
          <Field
            id="password"
            label="Password"
            type="password"
            autoComplete={view === "signup" ? "new-password" : "current-password"}
            value={password}
            onChange={setPassword}
          />
        )}
        {error && (
          <p className="mt-2 text-sm text-band-red" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={pending || email.length === 0 || (view !== "reset" && password.length === 0)} className={BUTTON}>
          {pending ? "Working…" : title}
        </button>
      </form>
      <div className="mt-3 flex flex-col items-center">
        {view !== "signin" && (
          <button type="button" className={LINK} onClick={() => { setView("signin"); setError(null); }}>
            Have an account? Sign in
          </button>
        )}
        {view === "signin" && (
          <>
            <button type="button" className={LINK} onClick={() => { setView("signup"); setError(null); }}>
              New here? Create an account
            </button>
            <button type="button" className={LINK} onClick={() => { setView("reset"); setError(null); }}>
              Forgot your password?
            </button>
          </>
        )}
      </div>
    </Frame>
  );
}

export function LoginPage() {
  return isPublic ? <PublicAuth /> : <PersonalLogin />;
}
