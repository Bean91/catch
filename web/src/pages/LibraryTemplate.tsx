import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ScheduleSheet } from "../components/library/ScheduleSheet";
import { StructureView } from "../components/library/StructureView";
import { SummaryPanel } from "../components/library/SummaryPanel";
import { EXAMPLE_NOTICE, workoutTypeLabel } from "../components/library/labels";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import { duplicateLibraryTemplate, fetchExercises, fetchLibraryTemplate, setLibraryTemplateArchived } from "../lib/api";

export function LibraryTemplatePage() {
  const { id } = useParams();
  const tid = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [schedule, setSchedule] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: t, isLoading, isError, refetch } = useQuery({ queryKey: ["library", tid], queryFn: () => fetchLibraryTemplate(tid), enabled: Number.isFinite(tid) });
  const exercises = useQuery({ queryKey: ["exercises", ""], queryFn: () => fetchExercises(), enabled: t?.workout_type === "strength" });
  const names = Object.fromEntries((exercises.data ?? []).map((e) => [e.id, e.name]));

  const duplicate = useMutation({
    mutationFn: () => duplicateLibraryTemplate(tid),
    onSuccess: (copy) => {
      qc.invalidateQueries({ queryKey: ["library"] });
      navigate(`/library/${copy.id}`);
    },
    onError: (e: Error) => setError(e.message),
  });
  const archive = useMutation({
    mutationFn: (archived: boolean) => setLibraryTemplateArchived(tid, archived),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["library"] }),
    onError: (e: Error) => setError(e.message),
  });

  if (isLoading) return <CardSkeleton lines={4} />;
  if (isError || !t) return <ErrorState message="Couldn't load this template." onRetry={() => refetch()} />;

  const btn = "flex min-h-11 items-center justify-center rounded-md border border-border px-4 text-sm font-medium text-text-secondary hover:border-accent/40";
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/library" className="text-sm text-text-tertiary">
          ← Library
        </Link>
        <h1 className="text-lg font-semibold text-text-primary" data-testid="template-title">
          {t.name}
        </h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-secondary">
          <span>{workoutTypeLabel(t.workout_type)}</span>
          {t.difficulty && <span>· {t.difficulty}</span>}
          {t.target_zone && <span>· {t.target_zone}</span>}
          {t.is_example && <span className="rounded-full border border-border px-2 py-0.5 text-xs">Example — not prescribed training</span>}
          {t.archived && <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-tertiary">Archived</span>}
        </div>
      </div>

      {t.is_example && (
        <Card>
          <p className="text-sm text-text-secondary">{EXAMPLE_NOTICE}</p>
        </Card>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" data-testid="add-to-calendar" disabled={t.archived} onClick={() => setSchedule(true)} className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
          Add to calendar
        </button>
        {!t.is_example && (
          <Link to={`/library/${t.id}/edit`} className={btn}>
            Edit
          </Link>
        )}
        <button type="button" data-testid="duplicate" onClick={() => duplicate.mutate()} disabled={duplicate.isPending} className={btn}>
          Duplicate
        </button>
        <button type="button" data-testid="archive" onClick={() => archive.mutate(!t.archived)} disabled={archive.isPending} className={btn}>
          {t.archived ? "Unarchive" : "Archive"}
        </button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-text-secondary">
          {error}
        </p>
      )}

      {(t.purpose || t.description || t.tags.length > 0) && (
        <Card title="About">
          <div className="flex flex-col gap-2 text-sm">
            {t.purpose && (
              <p className="text-text-primary">
                <span className="text-text-tertiary">Purpose · </span>
                {t.purpose}
              </p>
            )}
            {t.description && <p className="whitespace-pre-wrap text-text-secondary">{t.description}</p>}
            {t.tags.length > 0 && <p className="text-text-tertiary">{t.tags.join(" · ")}</p>}
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
        <Card title="Structure">
          <StructureView structure={t.structure} exerciseNames={names} />
        </Card>
        <Card title="Totals">
          <SummaryPanel summary={t.summary} />
        </Card>
      </div>

      <ScheduleSheet open={schedule} onOpenChange={setSchedule} template={t} />
    </div>
  );
}
