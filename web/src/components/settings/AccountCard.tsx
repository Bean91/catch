import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, deleteAccount } from "../../lib/api";
import { revokeAllDeviceTokens } from "../../lib/privacy";
import { useAuth } from "../../lib/auth";
import { confirmProblem, describeAuthError, passwordProblem } from "../../lib/authErrors";
import { PasswordField } from "../auth/PasswordField";
import { Card } from "../ui/Card";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

/** Public deployment only. Sign-in, email and password live in Supabase Auth; this is the person's way out. */
/** Session 32: change the password while signed in. Supabase's "secure password change" may ask for a recent sign-in; that comes
 * back as a plain sentence with the way out, never a raw error. */
function ChangePassword() {
  const { setNewPassword } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirmValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => setNewPassword(password),
    onSuccess: () => {
      setPassword("");
      setConfirmValue("");
      setOpen(false);
    },
    onError: (e) => setError(describeAuthError(e, "change")),
  });
  if (!open) {
    return (
      <div className="flex flex-col gap-1">
        <button type="button" className={`${btn} self-start`} onClick={() => setOpen(true)}>
          Change password
        </button>
        {change.isSuccess && <p role="status" className="text-sm text-text-secondary">Password changed.</p>}
      </div>
    );
  }
  return (
    <form
      className="flex flex-col rounded-md border border-border p-3"
      aria-label="Change password"
      onSubmit={(e) => {
        e.preventDefault();
        const problem = passwordProblem(password) ?? confirmProblem(password, confirm);
        if (problem) return setError(problem);
        setError(null);
        change.mutate();
      }}
    >
      <PasswordField id="account-new-password" label="New password" autoComplete="new-password" value={password} onChange={setPassword} checklist />
      <PasswordField id="account-confirm-password" label="Confirm new password" autoComplete="new-password" value={confirm} onChange={setConfirmValue} />
      {error && <p role="alert" className="mt-2 text-sm text-band-red">{error}</p>}
      <div className="mt-3 flex gap-2">
        <button type="submit" className={btn} disabled={change.isPending || !password || !confirm}>
          {change.isPending ? "Saving…" : "Save new password"}
        </button>
        <button type="button" className={btn} onClick={() => { setOpen(false); setPassword(""); setConfirmValue(""); setError(null); }}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function AccountCard() {
  const { email, logout } = useAuth();
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  // Apps connected with a device token aren't tied to this sign-in, so "all devices" ends them first, while this session can still ask.
  const everywhere = useMutation({
    mutationFn: async () => {
      await revokeAllDeviceTokens().catch(() => undefined);
      await logout(true);
    },
  });
  const remove = useMutation({
    mutationFn: async () => {
      await deleteAccount();
      await logout(false);
    },
  });

  return (
    <Card title="Account">
      <div className="flex flex-col gap-4" data-testid="account-card">
        <p className="text-sm text-text-secondary">
          Signed in as <span className="font-medium text-text-primary wrap-anywhere">{email ?? "your account"}</span>. Your data is private to this account.
        </p>
        <ChangePassword />
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btn} disabled={everywhere.isPending} onClick={() => everywhere.mutate()}>
            {everywhere.isPending ? "Signing out…" : "Sign out of all devices"}
          </button>
          {!confirm && (
            <button type="button" className={`${btn} text-band-red`} onClick={() => setConfirm(true)}>
              Delete account…
            </button>
          )}
        </div>
        {confirm && (
          <div className="flex flex-col gap-2 rounded-md border border-band-red p-3" role="alertdialog" aria-label="Delete account">
            <p className="text-sm text-text-secondary">
              This permanently deletes your account and the data you own — workouts, wellness, nutrition, notes, check-ins, coach conversations,
              stored photos, saved AI keys and connected-source credentials — and ends any app access. It cannot be undone. Kept after deletion: a moderation
              decision about a published result stays on record (no longer linked to you), and what you posted in a club stays with the club without your name.
              Data you already sent to an AI provider, and your grants at Garmin, Withings and Concept2 (which can't be ended from here), are outside Catch's control. Type <span className="font-mono-nums text-text-primary">DELETE</span> to confirm.
            </p>
            <input
              aria-label="Type DELETE to confirm"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-text-primary outline-none focus-visible:border-accent"
            />
            {remove.isError && remove.error instanceof ApiError && remove.error.status === 403 && remove.error.message === "reauth_required" && (
              <div className="flex flex-col gap-2" data-testid="reauth-required">
                <p className="text-sm text-band-red-text">
                  For your safety, deleting an account needs a recent sign-in. Sign out, sign back in, and come straight back here.
                </p>
                <div><button type="button" className={btn} onClick={() => logout(false)}>Sign out and sign in again</button></div>
              </div>
            )}
            {remove.isError && !(remove.error instanceof ApiError && remove.error.message === "reauth_required") && (
              <p className="text-sm text-band-red">Could not delete the account. Some of your public posts and files may already have been removed — try again.</p>
            )}
            <div className="flex gap-2">
              <button type="button" className={btn} onClick={() => { setConfirm(false); setTyped(""); }}>
                Cancel
              </button>
              <button
                type="button"
                className="min-h-11 rounded-md bg-band-red px-4 text-sm font-medium text-white disabled:opacity-50"
                disabled={typed !== "DELETE" || remove.isPending}
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? "Deleting…" : "Delete everything"}
              </button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
