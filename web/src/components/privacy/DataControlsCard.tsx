import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { deleteCategory, downloadExport, fetchPrivacySummary } from "../../lib/privacy";
import { Card } from "../ui/Card";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

export function ExportCard() {
  const [error, setError] = useState<string | null>(null);
  const run = useMutation({ mutationFn: downloadExport, onMutate: () => setError(null), onError: (e: Error) => setError(e.message) });
  return (
    <Card title="Download your data">
      <div className="flex flex-col gap-3" data-testid="export-card">
        <p className="text-sm text-text-secondary">
          Everything Catch holds about you in one file: workouts, recovery and sleep, nutrition, notes, check-ins, coach conversations, settings, your public
          results and club memberships. Saved-key and token secrets are left out (their existence is listed). Up to three downloads a day.
        </p>
        <div>
          <button type="button" className={btn} disabled={run.isPending} onClick={() => run.mutate()} data-testid="export-button">
            {run.isPending ? "Preparing…" : "Download everything"}
          </button>
        </div>
        {error && <p role="alert" className="text-sm text-band-red-text">{error}</p>}
      </div>
    </Card>
  );
}

export function DeleteDataCard() {
  const qc = useQueryClient();
  const summary = useQuery({ queryKey: ["privacy-summary"], queryFn: fetchPrivacySummary });
  const [confirming, setConfirming] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const del = useMutation({
    mutationFn: deleteCategory,
    onSuccess: (r) => {
      setConfirming(null);
      setMessage(`Removed ${r.rows_removed} item${r.rows_removed === 1 ? "" : "s"}${r.files_removed ? ` and ${r.files_removed} stored file${r.files_removed === 1 ? "" : "s"}` : ""}.`);
      qc.invalidateQueries({ queryKey: ["privacy-summary"] });
    },
    onError: (e: Error) => { setConfirming(null); setMessage(e.message); },
  });

  return (
    <Card title="Delete selected data">
      <div className="flex flex-col gap-3" data-testid="delete-data-card">
        <p className="text-sm text-text-secondary">Remove one kind of data at a time. This can't be undone; download your data first if you want a copy.</p>
        <ul className="flex flex-col gap-2">
          {summary.data?.categories.map((c) => (
            <li key={c.key} className="rounded-md border border-border p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">{c.label} <span className="font-mono-nums text-text-secondary">({c.rows})</span></p>
                  <p className="mt-0.5 text-xs text-text-secondary">{c.note}</p>
                </div>
                {confirming !== c.key && (
                  <button type="button" className={`${btn} shrink-0`} disabled={c.rows === 0} onClick={() => setConfirming(c.key)} data-testid={`delete-${c.key}`}>
                    Delete…
                  </button>
                )}
              </div>
              {confirming === c.key && (
                <div className="mt-2 flex flex-wrap gap-2" role="alertdialog" aria-label={`Delete ${c.label}`}>
                  <button type="button" className={btn} onClick={() => setConfirming(null)}>Cancel</button>
                  <button type="button" className="min-h-11 rounded-md bg-band-red px-4 text-sm font-medium text-white disabled:opacity-50" disabled={del.isPending} onClick={() => del.mutate(c.key)} data-testid={`confirm-delete-${c.key}`}>
                    {del.isPending ? "Deleting…" : "Yes, delete"}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
        {message && <p role="status" className="text-sm text-text-secondary" data-testid="delete-message">{message}</p>}
        <p className="text-xs text-text-secondary">
          Workouts themselves, and what you've published or posted, are removed from the places they live (Workouts, Leaderboards, Clubs) or by deleting your account.
        </p>
      </div>
    </Card>
  );
}
