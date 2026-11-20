import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { putConnectionCredential } from "../../lib/api";
import { CONCEPT2_TOKEN_HELP, GARMIN_KEY_PAGE_URL } from "../../lib/connections";
import type { ConnectionCard } from "../../lib/types";

const inputCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary placeholder:text-text-tertiary";

/** Add or replace a Garmin Personal API key or a Concept2 personal token. The secret lives only in this component's state, only until the
 *  request is sent, and is cleared on close, success and failure — it is never read back, cached, put in a URL or stored. */
export function CredentialSheet({ card, open, onOpenChange }: { card: ConnectionCard; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [expires, setExpires] = useState("");
  const [error, setError] = useState<string | null>(null);
  const garmin = card.provider === "garmin";
  const noun = garmin ? "key" : "token";
  const replacing = card.connected && (card.auth_method === "api_key" || card.auth_method === "personal_token");

  const save = useMutation({
    mutationFn: () => putConnectionCredential(card.provider, value, expires || null),
    onSuccess: () => {
      setValue("");
      setExpires("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      onOpenChange(false);
    },
    onError: (e: Error) => {
      setValue("");
      setError(e.message || `Couldn't save that ${noun}.`);
    },
  });

  function close(next: boolean) {
    if (!next) {
      setValue("");
      setExpires("");
      setError(null);
      save.reset();
    }
    onOpenChange(next);
  }

  return (
    <Dialog.Root open={open} onOpenChange={close}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="credential-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90dvh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,480px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">
            {replacing ? `Replace your ${card.label} ${noun}` : `Add your ${card.label} ${noun}`}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            Catch checks the {noun} with {card.label} first, then stores it encrypted on the server. It's never shown again — only its last four
            characters. {garmin ? "This is not your Garmin password, and Catch never asks for that." : "This is not your Concept2 password."}
          </Dialog.Description>
          <form
            className="mt-4 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (value.trim()) save.mutate();
            }}
          >
            <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
              {garmin ? "Personal API key" : "Personal access token"}
              <input
                type="password"
                name="connection-secret"
                autoComplete="off"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className={inputCls}
              />
            </label>
            {garmin && (
              <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
                Key expires on (optional)
                <input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} className={inputCls} />
                <span className="text-xs text-text-tertiary">Garmin doesn't tell Catch when a key expires. Enter the date you chose and Catch will remind you before it does.</span>
              </label>
            )}
            <p className="text-xs text-text-tertiary">
              {garmin ? (
                <>
                  Create one in Garmin Connect on the web:{" "}
                  <a href={GARMIN_KEY_PAGE_URL} target="_blank" rel="noreferrer" className="font-medium text-accent underline underline-offset-2">
                    Settings → Personal API Key
                  </a>
                  . Garmin shows it once, so paste it here straight away.
                </>
              ) : (
                CONCEPT2_TOKEN_HELP
              )}
            </p>
            {error && (
              <p role="alert" data-testid="credential-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => close(false)} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-secondary">
                Cancel
              </button>
              <button
                type="submit"
                disabled={!value.trim() || save.isPending}
                className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50"
              >
                {save.isPending ? "Checking…" : replacing ? "Check and replace" : "Check and save"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
