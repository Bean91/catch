import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { BlockEditor, blankRow, blockToRow, rowToBlock, type BlockRow } from "../components/library/BlockEditor";
import { SummaryPanel } from "../components/library/SummaryPanel";
import { DIFFICULTIES, SESSION_TYPE_CHOICES, WORKOUT_TYPES } from "../components/library/labels";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import { createLibraryTemplate, fetchExercises, fetchLibraryTemplate, previewLibraryTemplate, updateLibraryTemplate } from "../lib/api";
import type { Difficulty, SessionType, TemplateBlock, TemplateInput, TemplateStrengthItem, WorkoutType, ZoneLabel } from "../lib/types";

const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";
const ZONES: ZoneLabel[] = ["UT2", "UT1", "AT", "TR", "AN"];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-text-secondary">{label}</span>
      {children}
    </label>
  );
}

const FIRST_ROWS: Record<WorkoutType, BlockRow[]> = {
  erg_intervals: [blankRow()],
  steady_state: [{ ...blankRow(), reps: "1", kind: "time", work: "60:00", rest: "" }],
  rate_ladder: [18, 20, 22].map((r) => ({ ...blankRow(), reps: "1", kind: "time" as const, work: "4:00", rateMin: String(r), rateMax: String(r) })),
  distance_piece: [{ ...blankRow(), reps: "1", work: "5000", rest: "" }],
  time_piece: [{ ...blankRow(), reps: "1", kind: "time", work: "30:00", rest: "" }],
  strength: [],
  on_water: [{ ...blankRow(), reps: "3", kind: "time", work: "10:00", rest: "3:00" }],
  custom: [],
};

export function LibraryEditorPage() {
  const { id } = useParams();
  const editing = id !== undefined;
  const tid = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const existing = useQuery({ queryKey: ["library", tid], queryFn: () => fetchLibraryTemplate(tid), enabled: editing });

  const [name, setName] = useState("");
  const [type, setType] = useState<WorkoutType>("erg_intervals");
  const [sessionType, setSessionType] = useState<SessionType | "">("");
  const [description, setDescription] = useState("");
  const [purpose, setPurpose] = useState("");
  const [difficulty, setDifficulty] = useState<Difficulty | "">("");
  const [zone, setZone] = useState<ZoneLabel | "">("");
  const [tags, setTags] = useState("");
  const [warm, setWarm] = useState("");
  const [cool, setCool] = useState("");
  const [rows, setRows] = useState<BlockRow[]>(FIRST_ROWS.erg_intervals);
  const [items, setItems] = useState<TemplateStrengthItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(!editing);

  useEffect(() => {
    const t = existing.data;
    if (!editing || !t || loaded) return;
    setName(t.name);
    setType(t.workout_type);
    setSessionType(t.session_type);
    setDescription(t.description ?? "");
    setPurpose(t.purpose ?? "");
    setDifficulty(t.difficulty ?? "");
    setZone(t.target_zone ?? "");
    setTags(t.tags.join(", "));
    setWarm(t.structure.warmup?.duration_min != null ? String(t.structure.warmup.duration_min) : "");
    setCool(t.structure.cooldown?.duration_min != null ? String(t.structure.cooldown.duration_min) : "");
    setRows((t.structure.blocks ?? []).map(blockToRow));
    setItems(t.structure.strength_items ?? []);
    setLoaded(true);
  }, [editing, existing.data, loaded]);

  const exercises = useQuery({ queryKey: ["exercises", ""], queryFn: () => fetchExercises(), enabled: type === "strength" });

  const built = useMemo(() => {
    const problems: string[] = [];
    const blocks: TemplateBlock[] = [];
    rows.forEach((r, i) => {
      const { block, error: e } = rowToBlock(r, i);
      if (e) problems.push(e);
      else if (block) blocks.push(block);
    });
    const minutes = (s: string, label: string) => {
      if (!s.trim()) return null;
      const n = Number(s);
      if (!Number.isFinite(n) || n <= 0) {
        problems.push(`${label} must be a number of minutes.`);
        return null;
      }
      return { duration_min: n };
    };
    const warmup = minutes(warm, "Warm-up");
    const cooldown = minutes(cool, "Cool-down");
    const input: TemplateInput = {
      name: name.trim(),
      workout_type: type,
      session_type: sessionType || null,
      description: description.trim() || null,
      purpose: purpose.trim() || null,
      difficulty: difficulty || null,
      target_zone: zone || null,
      tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      structure: type === "strength" ? { strength_items: items } : { warmup, blocks, cooldown },
    };
    return { input, problems };
  }, [name, type, sessionType, description, purpose, difficulty, zone, tags, warm, cool, rows, items]);

  const preview = useQuery({
    queryKey: ["library-preview", built.input],
    queryFn: () => previewLibraryTemplate(built.input),
    enabled: loaded && built.problems.length === 0 && built.input.name.length > 0,
    placeholderData: (prev) => prev,
  });

  const save = useMutation({
    mutationFn: () => (editing ? updateLibraryTemplate(tid, built.input) : createLibraryTemplate(built.input)),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["library"] });
      navigate(`/library/${t.id}`);
    },
    onError: (e: Error) => setError(e.message),
  });

  const changeType = (next: WorkoutType) => {
    setType(next);
    setSessionType("");
    if (!editing || rows.length === 0) setRows(FIRST_ROWS[next]);
  };

  if (editing && existing.isLoading) return <CardSkeleton lines={5} />;
  if (editing && (existing.isError || !existing.data)) return <ErrorState message="Couldn't load this template." onRetry={() => existing.refetch()} />;
  if (editing && existing.data?.is_example) {
    return (
      <Card>
        <p className="text-sm text-text-secondary">Examples are read-only. Duplicate it from its page to make a copy you can change.</p>
        <Link to={`/library/${tid}`} className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-accent">
          ← Back to the example
        </Link>
      </Card>
    );
  }

  const issues = preview.data && !preview.data.ok ? preview.data.issues : [];
  const canSave = built.problems.length === 0 && issues.length === 0 && built.input.name.length > 0 && !save.isPending;
  const sessionChoices = SESSION_TYPE_CHOICES[type];

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to={editing ? `/library/${tid}` : "/library"} className="text-sm text-text-tertiary">
          ← {editing ? "Template" : "Library"}
        </Link>
        <h1 className="text-lg font-semibold text-text-primary">{editing ? "Edit template" : "New template"}</h1>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem] lg:gap-5">
        <div className="flex min-w-0 flex-col gap-4">
          <Card title="Basics">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <Field label="Name">
                  <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} aria-label="Template name" />
                </Field>
              </div>
              <Field label="Type">
                <select value={type} onChange={(e) => changeType(e.target.value as WorkoutType)} className={inputCls} aria-label="Workout type">
                  {WORKOUT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Session type">
                <select value={sessionType} onChange={(e) => setSessionType(e.target.value as SessionType | "")} className={inputCls} aria-label="Session type">
                  <option value="">Default</option>
                  {sessionChoices.map((s) => (
                    <option key={s} value={s}>
                      {s.replace("_", " ")}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Difficulty">
                <select value={difficulty} onChange={(e) => setDifficulty(e.target.value as Difficulty | "")} className={inputCls} aria-label="Difficulty">
                  <option value="">Not set</option>
                  {DIFFICULTIES.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Target zone">
                <select value={zone} onChange={(e) => setZone(e.target.value as ZoneLabel | "")} className={inputCls} aria-label="Target zone">
                  <option value="">Not set</option>
                  {ZONES.map((z) => (
                    <option key={z} value={z}>
                      {z}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="col-span-2">
                <Field label="Purpose (what it's for, in your words)">
                  <input value={purpose} onChange={(e) => setPurpose(e.target.value)} className={inputCls} />
                </Field>
              </div>
              <div className="col-span-2">
                <Field label="Description">
                  <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className={`${inputCls} py-2`} />
                </Field>
              </div>
              <div className="col-span-2">
                <Field label="Tags (comma-separated)">
                  <input value={tags} onChange={(e) => setTags(e.target.value)} className={inputCls} />
                </Field>
              </div>
            </div>
          </Card>

          {type === "strength" ? (
            <Card title="Exercises">
              <div className="flex flex-col gap-3" data-testid="strength-editor">
                {items.map((it, i) => (
                  <div key={i} className="grid grid-cols-[1fr_4rem_4rem_auto] items-end gap-2">
                    <select value={it.exercise_id} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, exercise_id: Number(e.target.value) } : x)))} className={inputCls} aria-label={`Exercise ${i + 1}`}>
                      {(exercises.data ?? []).map((ex) => (
                        <option key={ex.id} value={ex.id}>
                          {ex.name}
                        </option>
                      ))}
                    </select>
                    <input value={it.target_sets ?? ""} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, target_sets: e.target.value ? Number(e.target.value.replace(/\D/g, "")) : null } : x)))} inputMode="numeric" placeholder="Sets" aria-label={`Exercise ${i + 1} sets`} className={inputCls} />
                    <input value={it.target_reps ?? ""} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, target_reps: e.target.value ? Number(e.target.value.replace(/\D/g, "")) : null } : x)))} inputMode="numeric" placeholder="Reps" aria-label={`Exercise ${i + 1} reps`} className={inputCls} />
                    <button type="button" onClick={() => setItems(items.filter((_, j) => j !== i))} aria-label={`Remove exercise ${i + 1}`} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary">
                      ×
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  disabled={!exercises.data?.length}
                  onClick={() => exercises.data?.[0] && setItems([...items, { exercise_id: exercises.data[0].id, target_sets: 3, target_reps: 8 }])}
                  className="min-h-11 self-start rounded-md border border-border px-3 text-sm text-text-secondary disabled:opacity-60"
                >
                  + Add exercise
                </button>
              </div>
            </Card>
          ) : (
            <Card title={type === "rate_ladder" ? "Steps" : "Structure"}>
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Warm-up (minutes)">
                    <input value={warm} onChange={(e) => setWarm(e.target.value)} inputMode="decimal" className={inputCls} aria-label="Warm-up minutes" />
                  </Field>
                  <Field label="Cool-down (minutes)">
                    <input value={cool} onChange={(e) => setCool(e.target.value)} inputMode="decimal" className={inputCls} aria-label="Cool-down minutes" />
                  </Field>
                </div>
                <BlockEditor rows={rows} onChange={setRows} ladder={type === "rate_ladder"} />
              </div>
            </Card>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-4 lg:self-start">
          <Card title="Check">
            <div className="flex flex-col gap-3" data-testid="editor-check">
              {built.problems.map((p) => (
                <p key={p} className="text-sm text-text-secondary" role="status">
                  {p}
                </p>
              ))}
              {issues.map((i) => (
                <p key={i.path + i.message} className="text-sm text-text-secondary" role="status" data-testid="issue">
                  {i.message}
                </p>
              ))}
              {preview.data?.ok && preview.data.summary ? <SummaryPanel summary={preview.data.summary} /> : built.problems.length === 0 && issues.length === 0 && <p className="text-sm text-text-tertiary">Totals appear once the template is valid.</p>}
            </div>
          </Card>
          {error && (
            <p role="alert" className="text-sm text-text-secondary">
              {error}
            </p>
          )}
          <button type="button" data-testid="save-template" onClick={() => save.mutate()} disabled={!canSave} className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Create template"}
          </button>
        </div>
      </div>
    </div>
  );
}
