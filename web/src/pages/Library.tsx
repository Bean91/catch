import { useQuery } from "@tanstack/react-query";
import { buttonClass } from "../components/ui/Button";
import { BackLink } from "../components/ui/PageHeader";
import { useState } from "react";
import { Link } from "react-router-dom";
import { EXAMPLE_NOTICE, WORKOUT_TYPES, workoutTypeLabel } from "../components/library/labels";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { fetchLibraryFolders, fetchLibraryTemplates } from "../lib/api";
import { formatMinutesOrHours } from "../lib/duration";
import type { TemplateScope, WorkoutTemplate } from "../lib/types";
import { controlSkin } from "../components/ui/Field";

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
        className="flex min-h-11 min-w-0 flex-col gap-1 rounded-lg border border-border bg-surface p-4 transition-colors hover:border-accent/40"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 wrap-anywhere font-medium text-text-primary">{t.name}</span>
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
        {(t.folder || t.tags.length > 0) && (
          <p className="text-xs text-text-tertiary">
            {t.folder ? <span data-testid="template-folder-label">{`Folder: ${t.folder}`}</span> : null}
            {t.folder && t.tags.length > 0 ? " · " : ""}
            {t.tags.join(" · ")}
          </p>
        )}
      </Link>
    </li>
  );
}

export function LibraryPage() {
  const [scope, setScope] = useState<TemplateScope>("mine");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [folder, setFolder] = useState("");
  const folders = useQuery({ queryKey: ["library-folders"], queryFn: fetchLibraryFolders });
  const folderList = folders.data?.folders ?? [];
  // Examples are shared and never filed, so the folder filter applies to your own templates only.
  const activeFolder = scope === "examples" ? "" : folder;
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["library", { scope, type, q, folder: activeFolder }],
    queryFn: () => fetchLibraryTemplates({ scope, workout_type: type || undefined, q: q.trim() || undefined, folder: activeFolder || undefined }),
  });
  const templates = data?.templates ?? [];

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <BackLink to="/calendar">Calendar</BackLink>
          <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">Workout library</h1>
        </div>
        <Link to="/library/new" data-testid="new-template" className={buttonClass("primary")}>
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
          className={controlSkin + " min-h-11 w-full min-w-0"}
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
        {scope !== "examples" && folderList.length > 0 && (
          <label className="flex flex-wrap items-center gap-2 text-sm text-text-secondary">
            Folder
            <select value={folder} onChange={(e) => setFolder(e.target.value)} data-testid="folder-filter" className={controlSkin + " min-h-11 min-w-0 max-w-full flex-1 sm:flex-none"}>
              <option value="">All folders</option>
              {folderList.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} ({f.count})
                </option>
              ))}
            </select>
          </label>
        )}
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
