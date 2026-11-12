import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchTechniqueNotes } from "../../lib/api";
import type { TechniqueNote } from "../../lib/types";
import { Card } from "../ui/Card";
import { EmptyState, ErrorState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";
import { NOT_MEASURED } from "./labels";
import { TechniqueNoteItem } from "./TechniqueNoteItem";
import { TechniqueNoteSheet } from "./TechniqueNoteSheet";

// Titled "Technique notes" on purpose: the existing "Technique" card on a rowing workout is
// stroke-data analytics. This one is the athlete's own words, and never carries a score.
export function TechniqueNotesCard({
  canonicalId,
  date,
  pieces,
}: {
  canonicalId: number;
  date?: string | null;
  pieces?: { id: number; label: string }[];
}) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["technique-notes", { workout_id: canonicalId }],
    queryFn: () => fetchTechniqueNotes({ workout_id: canonicalId }),
  });
  const [sheet, setSheet] = useState<{ open: boolean; existing: TechniqueNote | null }>({ open: false, existing: null });
  const notes = data?.notes ?? [];

  return (
    <Card
      title="Technique notes"
      action={
        <button type="button" data-testid="add-note" onClick={() => setSheet({ open: true, existing: null })} className="min-h-11 text-sm font-medium text-accent">
          Add note
        </button>
      }
    >
      <div className="flex flex-col gap-3" data-testid="technique-notes">
        <p className="text-sm text-text-tertiary">{NOT_MEASURED}</p>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : isError ? (
          <ErrorState message="Couldn't load technique notes." onRetry={() => refetch()} />
        ) : notes.length === 0 ? (
          <EmptyState message="No technique notes for this workout yet." />
        ) : (
          <ul className="flex flex-col gap-2">
            {notes.map((n) => (
              <TechniqueNoteItem key={n.id} note={n} onEdit={(x) => setSheet({ open: true, existing: x })} />
            ))}
          </ul>
        )}
      </div>
      <TechniqueNoteSheet
        open={sheet.open}
        onOpenChange={(open) => setSheet((s) => ({ ...s, open }))}
        existing={sheet.existing}
        canonicalId={canonicalId}
        pieces={pieces}
        defaultDate={date ?? null}
      />
    </Card>
  );
}
