import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { FeedbackEntryCard } from "../components/coaching/FeedbackEntryCard";
import { FeedbackSheet } from "../components/coaching/FeedbackSheet";
import { FOCUS_AREAS, NOT_MEASURED, TECHNIQUE_CATEGORIES } from "../components/coaching/labels";
import { PrivacyBadge } from "../components/coaching/PrivacyBadge";
import { TechniqueNoteItem } from "../components/coaching/TechniqueNoteItem";
import { TechniqueNoteSheet } from "../components/coaching/TechniqueNoteSheet";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { fetchFeedback, fetchTechniqueNotes } from "../lib/api";
import type { FeedbackEntry, FocusArea, TechniqueNote } from "../lib/types";

const selectCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";

export function FeedbackPage() {
  const [coach, setCoach] = useState("");
  const [category, setCategory] = useState<FocusArea | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const filters = { coach, category, from, to };
  const feedback = useQuery({ queryKey: ["coach-feedback", filters], queryFn: () => fetchFeedback(filters) });
  const [sheet, setSheet] = useState<{ open: boolean; existing: FeedbackEntry | null }>({ open: false, existing: null });

  const [noteCategory, setNoteCategory] = useState<string>("");
  const notes = useQuery({ queryKey: ["technique-notes", { category: noteCategory }], queryFn: () => fetchTechniqueNotes({ category: noteCategory || undefined }) });
  const [noteSheet, setNoteSheet] = useState<{ open: boolean; existing: TechniqueNote | null }>({ open: false, existing: null });

  const entries = feedback.data?.feedback ?? [];
  const coaches = feedback.data?.coaches ?? [];

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link to="/calendar" className="text-sm text-text-tertiary">
            ← Calendar
          </Link>
          <h1 className="text-lg font-semibold text-text-primary">Coaching feedback</h1>
        </div>
        <button type="button" data-testid="log-feedback" onClick={() => setSheet({ open: true, existing: null })} className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast">
          Log feedback
        </button>
      </div>

      <Card title="Who can see what">
        <ul className="flex flex-col gap-2 text-sm text-text-secondary">
          <li className="flex flex-wrap items-center gap-2">
            <PrivacyBadge visibility="private" /> stays with you and is never sent to a coach.
          </li>
          <li className="flex flex-wrap items-center gap-2">
            <PrivacyBadge visibility="shared" /> can be read by a linked coach.
          </li>
          <li>Feedback your coach writes can only be edited by them; you can respond to it. Edits to shared feedback keep their history.</li>
        </ul>
      </Card>

      <Card title="Timeline">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="feedback-filters">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">Coach</span>
              <select value={coach} onChange={(e) => setCoach(e.target.value)} className={selectCls}>
                <option value="">Anyone</option>
                {coaches.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">Focus</span>
              <select value={category} onChange={(e) => setCategory(e.target.value as FocusArea | "")} className={selectCls}>
                <option value="">All areas</option>
                {FOCUS_AREAS.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">From</span>
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={`${selectCls} overflow-hidden`} />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">To</span>
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={`${selectCls} overflow-hidden`} />
            </label>
          </div>
          {feedback.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : feedback.isError ? (
            <ErrorState message="Couldn't load feedback." onRetry={() => feedback.refetch()} />
          ) : entries.length === 0 ? (
            <EmptyState message={coach || category || from || to ? "No feedback matches those filters." : "No feedback yet. Log what your coach tells you, or have them add it."} />
          ) : (
            <ul className="flex flex-col gap-3" data-testid="feedback-timeline">
              {entries.map((e) => (
                <FeedbackEntryCard key={e.id} entry={e} onEdit={(x) => setSheet({ open: true, existing: x })} />
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card
        title="Technique notes"
        action={
          <button type="button" data-testid="add-note-here" onClick={() => setNoteSheet({ open: true, existing: null })} className="min-h-11 text-sm font-medium text-accent">
            Add note
          </button>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="text-sm text-text-tertiary">{NOT_MEASURED}</p>
          <div role="tablist" aria-label="Technique category" className="flex gap-2 overflow-x-auto pb-1">
            {[{ value: "", label: "All" }, ...TECHNIQUE_CATEGORIES].map((c) => (
              <button
                key={c.value || "all"}
                type="button"
                role="tab"
                aria-selected={noteCategory === c.value}
                onClick={() => setNoteCategory(c.value)}
                className={`min-h-11 shrink-0 rounded-full border px-4 text-sm font-medium ${noteCategory === c.value ? "border-accent bg-accent text-accent-contrast" : "border-border bg-surface text-text-secondary hover:border-accent/40"}`}
              >
                {c.label}
              </button>
            ))}
          </div>
          {notes.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : notes.isError ? (
            <ErrorState message="Couldn't load technique notes." onRetry={() => notes.refetch()} />
          ) : (notes.data?.notes ?? []).length === 0 ? (
            <EmptyState message="No technique notes here yet." />
          ) : (
            <ul className="flex flex-col gap-2">
              {notes.data!.notes.map((n) => (
                <TechniqueNoteItem key={n.id} note={n} showWorkout onEdit={(x) => setNoteSheet({ open: true, existing: x })} />
              ))}
            </ul>
          )}
        </div>
      </Card>

      <FeedbackSheet open={sheet.open} onOpenChange={(open) => setSheet((s) => ({ ...s, open }))} existing={sheet.existing} />
      <TechniqueNoteSheet open={noteSheet.open} onOpenChange={(open) => setNoteSheet((s) => ({ ...s, open }))} existing={noteSheet.existing} />
    </div>
  );
}
