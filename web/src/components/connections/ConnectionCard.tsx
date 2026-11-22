import { formatInstantDateTime } from "../../lib/localTime";
import { isNative } from "../../lib/native/platform";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { disconnectConnection, putConnectionExpiry, startConnectionOAuth, syncConnection, testConnection } from "../../lib/api";
import {
  CAPABILITY_LABEL,
  daysUntil,
  disconnectText,
  maskedCredential,
  recoveryText,
  STATUS_GLYPH,
  statusLabel,
  statusTone,
} from "../../lib/connections";
import { formatRelativeTime } from "../../lib/format";
import type { ConnectionCard as Card_, ConnectionTestResult } from "../../lib/types";
import { Card } from "../ui/Card";
import { CredentialSheet } from "./CredentialSheet";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";
const TONE: Record<string, string> = {
  good: "border-band-green/40 text-band-green",
  bad: "border-band-red/40 text-band-red-text",
  warn: "border-band-yellow/50 text-text-primary",
  quiet: "border-border text-text-tertiary",
};
const CAP_WORD = { yes: "Yes", no: "No", unknown: "Not published" } as const;

/** One provider. Every provider uses this same card; only the way you connect differs (a sign-in page, a pasted key, or both). Nothing
 *  here ever holds a secret except the sheet, and that clears it. */
export function ConnectionCard({ card, returnTo }: { card: Card_; returnTo?: "onboarding" }) {
  const queryClient = useQueryClient();
  const [sheet, setSheet] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [test, setTest] = useState<ConnectionTestResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["connections"] });
    queryClient.invalidateQueries({ queryKey: ["sync-status"] });
  };

  const connect = useMutation({
    mutationFn: () => startConnectionOAuth(card.provider, returnTo),
    onSuccess: (r) => {
      if (r.authorize_url) {
        if (isNative()) void import("@capacitor/browser").then(({ Browser }) => Browser.open({ url: r.authorize_url! }));
        else window.location.assign(r.authorize_url);
      }
      else refresh();
    },
    onError: (e: Error) => setNotice(e.message),
  });
  const testMutation = useMutation({
    mutationFn: () => testConnection(card.provider),
    onSuccess: (r) => {
      setTest(r);
      refresh();
    },
  });
  const sync = useMutation({
    mutationFn: () => syncConnection(card.provider),
    onSuccess: (r) => {
      setNotice(r.error ? r.error : r.skipped ? `Skipped: ${r.skipped}.` : "Synced.");
      refresh();
    },
  });
  const disconnect = useMutation({
    mutationFn: () => disconnectConnection(card.provider),
    onSuccess: (r) => {
      setConfirm(false);
      setTest(null);
      setNotice(card.auth_method === "oauth" ? disconnectText(card.label, r.revoked) : null);
      refresh();
    },
  });
  const expiry = useMutation({ mutationFn: (v: string | null) => putConnectionExpiry(card.provider, v), onSuccess: refresh });

  const tone = statusTone(card.status);
  const garmin = card.provider === "garmin";
  const pasted = card.auth_method === "api_key" || card.auth_method === "personal_token";
  const recovery = recoveryText(card);
  const days = daysUntil(card.credential_expires_on);
  const noun = garmin ? "key" : "token";

  return (
    <Card title={card.label}>
      <div className="flex flex-col gap-3" data-testid={`connection-${card.provider}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span data-testid={`conn-status-${card.provider}`} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${TONE[tone]}`}>
            <span aria-hidden="true">{card.connected ? STATUS_GLYPH[card.status] : STATUS_GLYPH.disconnected}</span>
            {card.connected ? statusLabel(card) : "Not connected"}
          </span>
          {card.connected && pasted && <span className="font-mono-nums text-xs text-text-tertiary">{maskedCredential(card)}</span>}
          {card.connected && card.auth_method === "oauth" && <span className="text-xs text-text-tertiary">Signed in with {card.label}</span>}
        </div>

        {card.notes && (
          <p data-testid={`conn-note-${card.provider}`} className="rounded-md border border-border bg-surface-2 px-3 py-2 text-xs text-text-secondary">
            {card.notes}
          </p>
        )}

        {card.connected && (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm text-text-secondary">
            <dt className="text-text-tertiary">Last sync</dt>
            <dd>{card.last_success_at ? formatRelativeTime(card.last_success_at) : "not yet"}</dd>
            {card.importing_history_from && (
              <>
                <dt className="text-text-tertiary">History</dt>
                <dd data-testid={`conn-history-${card.provider}`}>Importing from {card.importing_history_from} onward</dd>
              </>
            )}
            {card.scopes.length > 0 && (
              <>
                <dt className="text-text-tertiary">Allowed</dt>
                <dd>{card.scopes.join(", ")}</dd>
              </>
            )}
            {card.credential_expires_on && (
              <>
                <dt className="text-text-tertiary">Key expires</dt>
                <dd className={days != null && days <= 14 ? "text-band-red-text" : undefined}>
                  {card.credential_expires_on}
                  {days != null && days <= 14 && (days <= 0 ? " — expired" : ` — in ${days} day${days === 1 ? "" : "s"}`)}
                </dd>
              </>
            )}
            {card.next_attempt_at && card.status !== "connected" && (
              <>
                <dt className="text-text-tertiary">Next try</dt>
                <dd>{formatInstantDateTime(card.next_attempt_at)}</dd>
              </>
            )}
          </dl>
        )}

        {recovery && (
          <p role="status" data-testid={`conn-recovery-${card.provider}`} className="rounded-md border border-border px-3 py-2 text-sm text-text-secondary">
            {recovery}
          </p>
        )}
        {card.last_error && card.status !== "needs_reconnect" && <p className="text-xs text-band-red-text">Last error: {card.last_error}</p>}

        {!card.available && <p className="text-sm text-text-tertiary">{card.label} isn't available on this server.</p>}

        {card.connected && card.from_environment && (
          <p data-testid={`conn-env-${card.provider}`} className="rounded-md border border-border px-3 py-2 text-xs text-text-secondary">
            This connection uses the {garmin ? "key" : "token"} in this server's <span className="font-mono-nums">.env</span> file. To disconnect it, remove it from
            that file; pasting a {noun} here replaces it for this account.
          </p>
        )}

        {card.available && garmin && card.connected && (
          <label className="flex flex-col gap-1.5 text-sm text-text-secondary sm:flex-row sm:items-center sm:gap-3">
            Key expires on
            <input
              type="date"
              defaultValue={card.credential_expires_on ?? ""}
              onBlur={(e) => e.target.value !== (card.credential_expires_on ?? "") && expiry.mutate(e.target.value || null)}
              className="min-h-11 rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary"
            />
          </label>
        )}

        {card.available && (
          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            {card.auth_methods.includes("oauth") && card.oauth_available && (
              <button type="button" onClick={() => connect.mutate()} disabled={connect.isPending} className={btn}>
                {connect.isPending ? "Opening…" : card.connected && card.auth_method === "oauth" ? "Reconnect" : `Connect ${card.label}`}
              </button>
            )}
            {(card.auth_methods.includes("api_key") || card.auth_methods.includes("personal_token")) && (
              <button type="button" onClick={() => setSheet(true)} className={btn}>
                {pasted ? `Replace ${noun}` : card.auth_methods.includes("oauth") && card.oauth_available ? "Use a personal token instead" : `Add your ${card.label} ${noun}`}
              </button>
            )}
            {card.connected && (
              <>
                <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending} className={btn}>
                  {sync.isPending ? "Syncing…" : "Sync now"}
                </button>
                <button type="button" onClick={() => testMutation.mutate()} disabled={testMutation.isPending} className={btn}>
                  {testMutation.isPending ? "Testing…" : "Test connection"}
                </button>
                {!confirm && !card.from_environment && (
                  <button type="button" onClick={() => setConfirm(true)} className="min-h-11 px-2 text-sm font-medium text-band-red-text hover:underline">
                    Disconnect
                  </button>
                )}
              </>
            )}
          </div>
        )}

        {confirm && (
          <div role="group" aria-label={`Confirm disconnecting ${card.label}`} className="flex flex-col gap-2 rounded-md border border-border p-3 text-sm text-text-secondary">
            <p>
              Disconnect {card.label}? Catch forgets the saved {pasted ? noun : "authorization"} and stops syncing. Everything already imported stays.{" "}
              {garmin ? "To end access completely, also delete the key in Garmin Connect." : null}
              {card.capabilities.token_revocation === "yes" ? `Catch also ends its access at ${card.label}.` : null}
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => disconnect.mutate()} disabled={disconnect.isPending} className="min-h-11 rounded-md border border-band-red/40 px-4 text-sm font-medium text-band-red-text">
                {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
              </button>
              <button type="button" onClick={() => setConfirm(false)} className={btn}>
                Keep it
              </button>
            </div>
          </div>
        )}

        {test && (
          <p role="status" data-testid={`conn-test-${card.provider}`} className={`text-sm ${test.ok ? "text-band-green" : "text-band-red-text"}`}>
            {test.message}
          </p>
        )}
        {notice && (
          <p role="status" data-testid={`conn-notice-${card.provider}`} className="text-sm text-text-secondary">
            {notice}
          </p>
        )}

        <details className="text-sm text-text-secondary" data-testid={`conn-limits-${card.provider}`}>
          <summary className="min-h-11 cursor-pointer content-center">What Catch can and can't do with {card.label}</summary>
          <ul className="mb-2 list-disc space-y-1.5 pl-5 text-xs text-text-secondary">
            {card.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <ul className="flex flex-col gap-1 text-xs text-text-tertiary">
            {Object.entries(card.capabilities).map(([k, v]) => (
              <li key={k} className="flex justify-between gap-3">
                <span>{CAPABILITY_LABEL[k] ?? k}</span>
                <span>{CAP_WORD[v]}</span>
              </li>
            ))}
          </ul>
        </details>
      </div>
      {(card.auth_methods.includes("api_key") || card.auth_methods.includes("personal_token")) && <CredentialSheet card={card} open={sheet} onOpenChange={setSheet} />}
    </Card>
  );
}
