import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { deleteAccount } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Card } from "../ui/Card";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

/** Public deployment only. Sign-in, email and password live in Supabase Auth; this is the person's way out. */
export function AccountCard() {
  const { email, logout } = useAuth();
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  const everywhere = useMutation({ mutationFn: () => logout(true) });
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
          Signed in as <span className="font-medium text-text-primary">{email ?? "your account"}</span>. Your data is private to this account.
        </p>
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
              This permanently deletes your account and everything in it — workouts, wellness, nutrition, notes, check-ins, coach conversations,
              stored photos and any AI keys you saved. It cannot be undone. Type <span className="font-mono-nums text-text-primary">DELETE</span> to confirm.
            </p>
            <input
              aria-label="Type DELETE to confirm"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="min-h-11 w-full rounded-md border border-border bg-bg px-3 text-text-primary outline-none focus-visible:border-accent"
            />
            {remove.isError && <p className="text-sm text-band-red">Could not delete the account. Nothing else was changed — try again.</p>}
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
