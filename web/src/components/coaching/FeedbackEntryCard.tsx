import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fetchFeedbackHistory, respondToFeedback } from "../../lib/api";
import { formatShortDate } from "../../lib/format";
import type { FeedbackEntry } from "../../lib/types";
import { invalidateFeedback } from "./FeedbackSheet";
import { focusLabel } from "./labels";
import { PrivacyBadge } from "./PrivacyBadge";

function authorLine(e: FeedbackEntry): string {
  if (e.author.role === "coach") return e.author.name;
  return e.coach_name ? `${e.coach_name} · logged by you` : "You";
}

function History({ id }: { id: number }) {
  const { data, isLoading, isError } = useQuery({ queryKey: ["coach-feedback", id, "history"], queryFn: () => fetchFeedbackHistory(id) });
  if (isLoading) return <p className="text-sm text-text-tertiary">Loading history…</p>;
  if (isError) return <p className="text-sm text-text-secondary">Couldn't load the history.</p>;
  const rows = data?.history ?? [];
  if (rows.length === 0) return <p className="text-sm text-text-tertiary">No earlier versions.</p>;
  return (
    <ol className="flex flex-col gap-2" data-testid="feedback-history">
      {rows.map((r) => (
        <li key={r.revision_no} className="rounded-md bg-surface-2 px-3 py-2 text-sm">
          <p className="text-xs text-text-tertiary">
            {r.kind === "response" ? "Before a response change" : r.kind === "delete" ? "Before it was removed" : "Earlier version"} · {r.edited_by} · {formatShortDate(r.edited_at.slice(0, 10))}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-text-secondary">{r.text}</p>
          {r.athlete_response && <p className="mt-1 text-text-tertiary">Response then: {r.athlete_response}</p>}
        </li>
      ))}
    </ol>
  );
}

export function FeedbackEntryCard({ entry, onEdit }: { entry: FeedbackEntry; onEdit: (e: FeedbackEntry) => void }) {
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const [editingResponse, setEditingResponse] = useState(false);
  const [draft, setDraft] = useState(entry.athlete_response ?? "");
  const [error, setError] = useState<string | null>(null);
  const respond = useMutation({
    mutationFn: () => respondToFeedback(entry.id, draft.trim() || null),
    onSuccess: () => {
      invalidateFeedback(qc);
      setEditingResponse(false);
    },
    onError: (e: Error) => setError(e.message),
  });
  const byCoach = entry.author.role === "coach";

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4" data-testid="feedback-entry" data-author-role={entry.author.role} data-visibility={entry.visibility}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-text-primary">{authorLine(entry)}</span>
        <span className="rounded-full border border-border px-2 py-0.5 text-text-secondary">{byCoach ? "Coach" : "Your entry"}</span>
        {entry.created_via === "ai_coach" && <span className="rounded-full border border-border px-2 py-0.5 text-text-secondary">via AI coach</span>}
        <span className="text-text-tertiary">{formatShortDate(entry.date)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <PrivacyBadge visibility={entry.visibility} label={byCoach ? "Shared with you" : undefined} />
        {entry.focus_areas.map((f) => (
          <span key={f} className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">
            {focusLabel(f)}
          </span>
        ))}
      </div>
      <p className="whitespace-pre-wrap text-sm text-text-primary">{entry.text}</p>
      {(entry.workout || entry.event || entry.planned) && (
        <p className="text-sm text-text-secondary">
          {entry.workout && (
            <Link to={`/workouts/${entry.workout.id}`} className="text-accent underline">
              {entry.workout.title}
              {entry.workout.date ? ` · ${formatShortDate(entry.workout.date)}` : ""}
            </Link>
          )}
          {entry.event && (
            <Link to={`/calendar/events/${entry.event.id}`} className="text-accent underline">
              {entry.event.name}
            </Link>
          )}
          {entry.planned && <span>Planned: {entry.planned.title}</span>}
        </p>
      )}

      {entry.athlete_response && !editingResponse && (
        <div className="rounded-md bg-surface-2 px-3 py-2 text-sm" data-testid="athlete-response">
          <p className="text-xs text-text-tertiary">Your response</p>
          <p className="whitespace-pre-wrap text-text-primary">{entry.athlete_response}</p>
        </div>
      )}
      {entry.can_respond && !editingResponse && (
        <button type="button" data-testid="respond" onClick={() => { setDraft(entry.athlete_response ?? ""); setEditingResponse(true); }} className="min-h-11 self-start text-sm font-medium text-accent">
          {entry.athlete_response ? "Edit your response" : "Respond"}
        </button>
      )}
      {editingResponse && (
        <div className="flex flex-col gap-2">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} aria-label="Your response" className="w-full min-w-0 rounded-md border border-border bg-bg px-3 py-2 text-sm text-text-primary" />
          {error && <p role="alert" className="text-sm text-text-secondary">{error}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={() => respond.mutate()} disabled={respond.isPending} className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
              Save response
            </button>
            <button type="button" onClick={() => setEditingResponse(false)} className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {entry.can_edit ? (
          <button type="button" onClick={() => onEdit(entry)} className="min-h-11 text-sm font-medium text-accent">
            Edit
          </button>
        ) : (
          <span className="text-xs text-text-tertiary" data-testid="read-only-note">
            Written by {entry.author.name} — only they can edit it.
          </span>
        )}
        {entry.edited && (
          <button type="button" aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)} className="min-h-11 text-sm text-text-secondary underline">
            Edited · history ({entry.edit_count})
          </button>
        )}
      </div>
      {showHistory && <History id={entry.id} />}
    </li>
  );
}
