import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { EXAMPLE_NOTICE, WORKOUT_TYPES, workoutTypeLabel } from "../components/library/labels";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { fetchLibraryTemplates } from "../lib/api";
import { formatMinutesOrHours } from "../lib/duration";
import type { TemplateScope, WorkoutTemplate } from "../lib/types";

const SCOPES: { value: TemplateScope; label: string }[] = [
  { value: "mine", label: "My templates" },
  { value: "examples", label: "Examples" },
  { value: "archived", label: "Archived" },
];

export function TemplateRow({ t }: { t: WorkoutTemplate }) {
  return (
    <li className="min-w-0">
      <Link
        to={`/library/${t.id}`}
        data-testid="template-card"
        className="flex min-h-11 min-w-0 flex-col gap-1 break-words rounded-lg border border-border bg-surface p-4 transition-colors hover:border-accent/40"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-text-primary">{t.name}</span>
          {t.is_example && (
            <span data-testid="example-badge" className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">
              Example — not prescribed training
            </span>
          )}
          {t.archived && <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-tertiary">Archived</span>}
        </div>
        <p className="text-sm text-text-secondary">
          {workoutTypeLabel(t.workout_type)}
          {t.difficulty ? ` · ${t.difficulty}` : ""}
          {t.signature && t.signature.length <= 28 ? ` · ${t.signature}` : ""}
          {t.summary.total_duration_s != null ? ` · ${formatMinutesOrHours(t.summary.total_duration_s)}${t.summary.duration_basis === "estimated" ? " (est.)" : ""}` : ""}
        </p>
        {t.tags.length > 0 && <p className="text-xs text-text-tertiary">{t.tags.join(" · ")}</p>}
      </Link>
    </li>
  );
}

export function LibraryPage() {
  const [scope, setScope] = useState<TemplateScope>("mine");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["library", { scope, type, q }],
    queryFn: () => fetchLibraryTemplates({ scope, workout_type: type || undefined, q: q.trim() || undefined }),
  });
  const templates = data?.templates ?? [];

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link to="/calendar" className="text-sm text-text-tertiary">
            ← Calendar
          </Link>
          <h1 className="text-lg font-semibold text-text-primary">Workout library</h1>
        </div>
        <Link to="/library/new" data-testid="new-template" className="flex min-h-11 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast">
          New template
        </Link>
      </div>

      <div role="tablist" aria-label="Library" className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-surface p-1">
        {SCOPES.map((s) => (
          <button
            key={s.value}
            type="button"
            role="tab"
            aria-selected={scope === s.value}
            onClick={() => setScope(s.value)}
            className={`min-h-11 rounded-md px-2 text-sm font-medium ${scope === s.value ? "bg-surface-2 text-accent" : "text-text-secondary"}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search templates"
          aria-label="Search templates"
          className="min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary"
        />
        <div role="tablist" aria-label="Workout type" className="flex gap-2 overflow-x-auto pb-1">
          {[{ value: "", label: "All types" }, ...WORKOUT_TYPES].map((t) => (
            <button
              key={t.value || "all"}
              type="button"
              role="tab"
              aria-selected={type === t.value}
              onClick={() => setType(t.value)}
              className={`min-h-11 shrink-0 rounded-full border px-4 text-sm font-medium ${type === t.value ? "border-accent bg-accent text-accent-contrast" : "border-border bg-surface text-text-secondary hover:border-accent/40"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {scope === "examples" && (
        <Card>
          <p className="text-sm text-text-secondary" data-testid="example-notice">
            {EXAMPLE_NOTICE}
          </p>
        </Card>
      )}

      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : isError ? (
        <ErrorState message="Couldn't load the library." onRetry={() => refetch()} />
      ) : templates.length === 0 ? (
        <EmptyState message={scope === "mine" ? "No templates yet. Create one, or duplicate an example to start." : scope === "archived" ? "Nothing archived." : "No examples match."} />
      ) : (
        <ul className="grid gap-2 lg:grid-cols-2" data-testid="template-list">
          {templates.map((t) => (
            <TemplateRow key={t.id} t={t} />
          ))}
        </ul>
      )}
    </div>
  );
}
