import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { appealLbEntry, reportLbEntry } from "../../lib/api";
import { REPORT_REASONS } from "../../lib/leaderboards";
import { SheetContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

const inputCls = `${controlSkin} min-h-11 w-full`;

type Props = { mode: "report" | "appeal"; entryId: string; subject: string; open: boolean; onOpenChange: (open: boolean) => void };

/** Report someone's result, or appeal a decision about your own. Both need a written reason; nothing is sent until you press the button. */
export function ReasonSheet({ mode, entryId, subject, open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState(REPORT_REASONS[0].value);
  const [text, setText] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = useMutation<unknown>({
    mutationFn: () => (mode === "report" ? reportLbEntry(entryId, reason, text) : appealLbEntry(entryId, text)),
    onSuccess: (res) => {
      setError(null);
      const hidden = mode === "report" && (res as { hidden_for_review?: boolean }).hidden_for_review === true;
      setDone(mode === "report" ? (hidden ? "Thanks. This result was hidden for review." : "Thanks. A moderator will look at this.") : "Your appeal was sent. You'll see the decision, with its reason, in Settings → Leaderboards.");
      queryClient.invalidateQueries({ queryKey: ["lb-me"] });
      queryClient.invalidateQueries({ queryKey: ["lb-board"] });
    },
    onError: (e: Error) => setError(e.message || "That didn't send."),
  });

  function close(next: boolean) {
    if (!next) {
      setText("");
      setDone(null);
      setError(null);
      send.reset();
    }
    onOpenChange(next);
  }

  return (
    <Dialog.Root open={open} onOpenChange={close}>
      <SheetContent width="md" onOpenAutoFocus={(e) => e.preventDefault()} data-testid={`${mode}-sheet`}>
          <Dialog.Title className="text-lg font-semibold text-text-primary">{mode === "report" ? "Report this result" : "Appeal this decision"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {mode === "report"
              ? `${subject}. A moderator reviews reports; the athlete is never told who reported them.`
              : `${subject}. A moderator reads your appeal and records their decision with a reason.`}
          </Dialog.Description>
          {done ? (
            <div className="mt-4 flex flex-col gap-3">
              <p role="status" data-testid={`${mode}-done`} className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
                {done}
              </p>
              <button type="button" onClick={() => close(false)} className={buttonClass("secondary", "md", "self-end")}>
                Close
              </button>
            </div>
          ) : (
            <form
              className="mt-4 flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                send.mutate();
              }}
            >
              {mode === "report" && (
                <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
                  What's wrong?
                  <select value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls} data-testid="report-reason">
                    {REPORT_REASONS.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
                {mode === "report" ? "Details (optional)" : "Why should this change?"}
                <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={4} className={`${inputCls} py-2`} data-testid={`${mode}-text`} />
              </label>
              {error && (
                <p role="alert" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
                  {error}
                </p>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <button type="button" onClick={() => close(false)} className={buttonClass("secondary", "md")}>
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={send.isPending || (mode === "appeal" && !text.trim())}
                  data-testid={`${mode}-send`}
                  className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50"
                >
                  {send.isPending ? "Sending…" : mode === "report" ? "Send report" : "Send appeal"}
                </button>
              </div>
            </form>
          )}
        </SheetContent>
    </Dialog.Root>
  );
}
