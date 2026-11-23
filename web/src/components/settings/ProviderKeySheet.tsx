import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { putAiKey } from "../../lib/api";
import type { AiProviderCard } from "../../lib/types";
import { SheetContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

const inputCls = `${controlSkin} min-h-11 w-full`;

/** Add or replace a provider key. The key lives only in this component's state, only until the
 *  request is sent, and is cleared on close, success and failure — it is never read back. */
export function ProviderKeySheet({ card, open, onOpenChange }: { card: AiProviderCard; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const replacing = card.configured;

  const save = useMutation({
    mutationFn: () => putAiKey(card.id, value),
    onSuccess: () => {
      setValue("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["ai-providers"] });
      queryClient.invalidateQueries({ queryKey: ["ai-models", card.id] });
      onOpenChange(false);
    },
    onError: (e: Error) => {
      setValue("");
      setError(e.message || "Couldn't save that key.");
    },
  });

  function close(next: boolean) {
    if (!next) {
      setValue("");
      setError(null);
      save.reset();
    }
    onOpenChange(next);
  }

  return (
    <Dialog.Root open={open} onOpenChange={close}>
      <SheetContent width="md" onOpenAutoFocus={(e) => e.preventDefault()} data-testid="provider-key-sheet">
          <Dialog.Title className="text-lg font-semibold text-text-primary">
            {replacing ? `Replace your ${card.label} key` : `Add your ${card.label} key`}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            Catch checks the key with {card.label} first, then stores it encrypted on the server. It's never shown again — only its last four
            characters.
          </Dialog.Description>
          <form
            className="mt-4 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (value.trim()) save.mutate();
            }}
          >
            <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
              API key
              <input
                type="password"
                name="provider-api-key"
                autoComplete="off"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                placeholder={card.key_hint}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className={inputCls}
              />
            </label>
            <p className="text-xs text-text-tertiary">
              Get a key from{" "}
              <a href={card.docs_url} target="_blank" rel="noreferrer" className="font-medium text-accent underline underline-offset-2">
                {card.label}'s console
              </a>
              . You pay {card.label} directly for what you use; Catch never does.
            </p>
            {error && (
              <p role="alert" data-testid="key-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => close(false)} className={buttonClass("secondary", "md")}>
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
        </SheetContent>
    </Dialog.Root>
  );
}
