import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button, buttonClass } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { controlSkin } from "../components/ui/Field";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";
import { SheetContent } from "../components/ui/Sheet";
import { CardSkeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";
import { createGoal, deleteGoal, fetchGoals, updateGoal } from "../lib/api";
import { addDays, todayISO, weekRangeLabel } from "../lib/dates";
import { parseClock } from "../lib/duration";
import { formatShortDate, formatSplit } from "../lib/format";
import type { Goal, GoalInput, GoalKind } from "../lib/types";

const inputCls = `${controlSkin} min-h-11 w-full min-w-0`;

const KIND_TEXT: Record<GoalKind, string> = {
  text: "In your own words",
  distance_total: "Total distance",
  workout_count: "Number of sessions",
  weekly_volume: "Minutes each week",
  frequency: "Sessions each week",
  target_split: "A split over a distance",
  target_power: "Average power for a duration",
};

function valueText(g: Goal, v: number | null | undefined): string {
  if (v == null) return "—";
  switch (g.kind) {
    case "distance_total":
      return `${(v / 1000).toFixed(1)} km`;
    case "workout_count":
    case "frequency":
      return `${Math.round(v)}`;
    case "weekly_volume":
      return `${Math.round(v)} min`;
    case "target_split":
      return `${formatSplit(v)} ${g.sport === "cycling" ? "/1000m" : "/500m"}`;
    case "target_power":
      return `${Math.round(v)} W`;
    default:
      return `${v}`;
  }
}

function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div className="h-2 rounded-full bg-surface-2" role="img" aria-label={label}>
      <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(pct, 100))}%` }} />
    </div>
  );
}

const STATE_TEXT = { active: "Active", done: "✓ Done", abandoned: "Set aside", ended: "Window ended" } as const;

function GoalCard({ g, onEdit }: { g: Goal; onEdit: (g: Goal) => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [confirm, setConfirm] = useState(false);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["goals"] });
  const setStatus = useMutation({ mutationFn: (status: Goal["status"]) => updateGoal(g.id, { status }), onSuccess: (_d, s) => (invalidate(), toast(s === "done" ? "Marked done" : s === "abandoned" ? "Set aside" : "Back to active")) });
  const remove = useMutation({ mutationFn: () => deleteGoal(g.id), onSuccess: () => (invalidate(), toast("Goal deleted")) });
  const p = g.progress;
  return (
    <Card testId="goal-card">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="min-w-0 wrap-anywhere text-base font-semibold text-text-primary">{g.text}</h3>
          <p className="text-xs text-text-tertiary">
            {KIND_TEXT[g.kind]}
            {g.start_date && g.end_date ? ` · ${formatShortDate(g.start_date)} – ${formatShortDate(g.end_date)}` : g.target_date ? ` · by ${formatShortDate(g.target_date)}` : ""}
            {p.days_left != null && p.state === "active" ? ` · ${p.days_left} day${p.days_left === 1 ? "" : "s"} left` : ""}
          </p>
        </div>
        <Badge tone={p.state === "active" ? "accent" : "outline"}>{STATE_TEXT[p.state]}</Badge>
      </div>

      {p.measurable && (g.kind === "distance_total" || g.kind === "workout_count") && (
        <div className="mt-3 flex flex-col gap-1">
          <ProgressBar pct={p.pct ?? 0} label={`${valueText(g, p.current)} of ${valueText(g, g.target_value)}`} />
          <p className="text-sm text-text-secondary">
            <span className="font-mono-nums text-text-primary">{valueText(g, p.current)}</span> of <span className="font-mono-nums">{valueText(g, g.target_value)}</span>
            {p.achieved ? " · reached" : ""}
          </p>
        </div>
      )}

      {p.measurable && (g.kind === "weekly_volume" || g.kind === "frequency") && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-sm text-text-secondary">
            Target {valueText(g, g.target_value)} a week · {p.weeks_met ?? 0} of {p.weeks_finished ?? 0} finished week{p.weeks_finished === 1 ? "" : "s"} reached it
          </p>
          <ul className="flex flex-col gap-1.5" data-testid="goal-weeks">
            {(p.weeks ?? []).map((w) => (
              <li key={w.week_start} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 text-xs">
                <div>
                  <span className="text-text-tertiary">{weekRangeLabel(w.week_start)}{w.current ? " · this week" : ""}</span>
                  <ProgressBar pct={g.target_value ? (w.value / g.target_value) * 100 : 0} label={`${valueText(g, w.value)} of ${valueText(g, g.target_value)}`} />
                </div>
                <span className="font-mono-nums text-text-secondary">
                  {valueText(g, w.value)} {w.met ? "✓" : ""}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-text-tertiary">
            A weekly target is the week's total — there's nothing to make up on any one day.
            {g.recovery_today ? ` Recovery today: ${g.recovery_today}.` : ""}
          </p>
        </div>
      )}

      {p.measurable && (g.kind === "target_split" || g.kind === "target_power") && (
        <div className="mt-3 text-sm text-text-secondary">
          {p.achieved ? (
            <p>
              ✓ Reached on {formatShortDate(p.achieved_on!)}
              {p.achieved_ref && (
                <>
                  {" "}
                  — <Link to={p.achieved_ref} className="text-accent underline">see the effort</Link>
                </>
              )}
            </p>
          ) : p.current != null ? (
            <p>
              Best so far <span className="font-mono-nums text-text-primary">{valueText(g, p.current)}</span> against <span className="font-mono-nums">{valueText(g, g.target_value)}</span>
              {p.gap != null && <> · {g.kind === "target_split" ? `${p.gap.toFixed(1)} s to go` : `${Math.round(p.gap)} W to go`}</>}
              {p.best_ref && (
                <>
                  {" "}
                  · <Link to={p.best_ref} className="text-accent underline">best effort</Link>
                </>
              )}
            </p>
          ) : (
            <p>No qualifying effort in the window yet.</p>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {g.status === "active" ? (
          <>
            <Button size="sm" variant="secondary" onClick={() => setStatus.mutate("done")} disabled={setStatus.isPending}>
              Mark done
            </Button>
            <Button size="sm" variant="subtle" onClick={() => setStatus.mutate("abandoned")} disabled={setStatus.isPending}>
              Set aside
            </Button>
            <Button size="sm" variant="subtle" onClick={() => onEdit(g)}>
              Edit
            </Button>
          </>
        ) : (
          <Button size="sm" variant="subtle" onClick={() => setStatus.mutate("active")} disabled={setStatus.isPending}>
            Make active again
          </Button>
        )}
        {!confirm ? (
          <button type="button" onClick={() => setConfirm(true)} className="min-h-9 px-2 text-xs text-text-tertiary underline">
            Delete
          </button>
        ) : (
          <div role="group" aria-label="Confirm delete" className="flex w-full flex-wrap items-center gap-2 rounded-md border border-border p-2 text-sm">
            <span className="flex-1 text-text-secondary">Delete this goal? Your workouts aren't affected.</span>
            <Button size="sm" variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
              Delete
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setConfirm(false)}>
              Keep it
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function GoalSheet({ open, onOpenChange, existing }: { open: boolean; onOpenChange: (o: boolean) => void; existing: Goal | null }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [kind, setKind] = useState<GoalKind>("distance_total");
  const [text, setText] = useState("");
  const [sport, setSport] = useState("rowing");
  const [target, setTarget] = useState("");
  const [extra, setExtra] = useState("");
  const [start, setStart] = useState(todayISO());
  const [end, setEnd] = useState(addDays(todayISO(), 41));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setKind(existing?.kind ?? "distance_total");
    setText(existing?.text ?? "");
    setSport(existing?.sport ?? "rowing");
    const k = existing?.kind;
    const tv = existing?.target_value ?? null;
    setTarget(tv == null ? "" : k === "distance_total" ? String(tv / 1000) : k === "target_split" ? formatSplit(tv) : String(tv));
    setExtra(existing?.params?.distance_m != null ? String(existing.params.distance_m) : existing?.params?.min_duration_s != null ? String(existing.params.min_duration_s / 60) : "");
    setStart(existing?.start_date ?? todayISO());
    setEnd(existing?.end_date ?? existing?.target_date ?? addDays(todayISO(), 41));
  }, [open, existing]);

  const body = (): GoalInput | string => {
    const input: GoalInput = { kind, text: text.trim() || null };
    if (kind === "text") return { ...input, target_date: end || null };
    let tv: number | null = null;
    if (kind === "target_split") tv = parseClock(target);
    else if (kind === "distance_total") tv = Number(target) * 1000;
    else tv = Number(target);
    if (tv == null || !Number.isFinite(tv) || tv <= 0) return "Enter the target as a number" + (kind === "target_split" ? " like 1:45.0" : "") + ".";
    input.target_value = tv;
    input.start_date = start;
    input.end_date = end;
    input.sport = kind === "workout_count" || kind === "frequency" || kind === "weekly_volume" ? null : sport;
    if (kind === "target_split") input.params = { distance_m: Number(extra) };
    if (kind === "target_power") input.params = { min_duration_s: Number(extra) * 60 };
    return input;
  };

  const save = useMutation({
    mutationFn: async () => {
      const b = body();
      if (typeof b === "string") throw new Error(b);
      return existing ? updateGoal(existing.id, b) : createGoal(b);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      onOpenChange(false);
      toast(existing ? "Goal updated" : "Goal added");
    },
    onError: (e: Error) => setError(e.message),
  });

  const targetLabel: Record<GoalKind, string> = {
    text: "",
    distance_total: "Kilometres",
    workout_count: "Sessions",
    weekly_volume: "Minutes per week",
    frequency: "Sessions per week",
    target_split: `Split ${sport === "cycling" ? "/1000m" : "/500m"} (m:ss.t)`,
    target_power: "Watts",
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <SheetContent width="md" onOpenAutoFocus={(e) => e.preventDefault()} data-testid="goal-sheet">
        <Dialog.Title className="text-lg font-semibold text-text-primary">{existing ? "Edit goal" : "Add a goal"}</Dialog.Title>
        <Dialog.Description className="mt-1 text-sm text-text-secondary">Progress is worked out from your logged training. Nothing is added to your plan.</Dialog.Description>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="col-span-2 flex min-w-0 flex-col gap-1 text-sm">
            <span className="text-text-secondary">Kind of goal</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as GoalKind)} className={inputCls} disabled={!!existing}>
              {(Object.keys(KIND_TEXT) as GoalKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_TEXT[k]}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 flex min-w-0 flex-col gap-1 text-sm">
            <span className="text-text-secondary">{kind === "text" ? "Your goal" : "Name (optional — one is written for you)"}</span>
            <input value={text} onChange={(e) => setText(e.target.value)} className={inputCls} maxLength={500} />
          </label>
          {kind !== "text" && (
            <>
              <label className="flex min-w-0 flex-col gap-1 text-sm">
                <span className="text-text-secondary">{targetLabel[kind]}</span>
                <input value={target} onChange={(e) => setTarget(e.target.value)} inputMode="decimal" className={inputCls} data-testid="goal-target" />
              </label>
              {(kind === "distance_total" || kind === "target_split" || kind === "target_power") && (
                <label className="flex min-w-0 flex-col gap-1 text-sm">
                  <span className="text-text-secondary">Sport</span>
                  <select value={sport} onChange={(e) => setSport(e.target.value)} className={inputCls}>
                    <option value="rowing">Rowing</option>
                    <option value="cycling">Cycling</option>
                    {kind === "distance_total" && <option value="running">Running</option>}
                  </select>
                </label>
              )}
              {kind === "target_split" && (
                <label className="flex min-w-0 flex-col gap-1 text-sm">
                  <span className="text-text-secondary">Over a distance of (m)</span>
                  <input value={extra} onChange={(e) => setExtra(e.target.value)} inputMode="numeric" placeholder="2000" className={inputCls} />
                </label>
              )}
              {kind === "target_power" && (
                <label className="flex min-w-0 flex-col gap-1 text-sm">
                  <span className="text-text-secondary">For at least (minutes)</span>
                  <input value={extra} onChange={(e) => setExtra(e.target.value)} inputMode="decimal" placeholder="20" className={inputCls} />
                </label>
              )}
              <label className="flex min-w-0 flex-col gap-1 text-sm">
                <span className="text-text-secondary">From</span>
                <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={`${inputCls} overflow-hidden`} />
              </label>
            </>
          )}
          <label className="flex min-w-0 flex-col gap-1 text-sm">
            <span className="text-text-secondary">{kind === "text" ? "By (optional)" : "Until"}</span>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={`${inputCls} overflow-hidden`} />
          </label>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-sm text-text-secondary">
            {error}
          </p>
        )}
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className={buttonClass("primary", "md", "flex-1")} data-testid="save-goal">
            {save.isPending ? "Saving…" : existing ? "Save" : "Add goal"}
          </button>
          <Dialog.Close className={buttonClass("secondary", "md")}>Cancel</Dialog.Close>
        </div>
      </SheetContent>
    </Dialog.Root>
  );
}

export function GoalsPage() {
  const q = useQuery({ queryKey: ["goals"], queryFn: () => fetchGoals("all") });
  const [sheet, setSheet] = useState<{ open: boolean; existing: Goal | null }>({ open: false, existing: null });
  const goals = q.data?.goals ?? [];
  const active = goals.filter((g) => g.progress.state === "active");
  const history = goals.filter((g) => g.progress.state !== "active");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow="Training"
        title="Goals"
        subtitle="Targets with a window, measured from what you actually did. No streaks, and nothing to catch up on."
        actions={
          <Button size="sm" variant="primary" onClick={() => setSheet({ open: true, existing: null })} data-testid="add-goal">
            + Goal
          </Button>
        }
      />
      {q.isError ? (
        <ErrorState message="Couldn't load goals." onRetry={() => q.refetch()} />
      ) : !q.data ? (
        <div className="flex flex-col gap-3">
          <CardSkeleton lines={3} />
          <CardSkeleton lines={3} />
        </div>
      ) : (
        <>
          {active.length === 0 ? (
            <EmptyState title="No active goals" message="Add one — a distance for a block, a split over 2,000 m, or how many sessions a week." />
          ) : (
            <div className="grid gap-3 lg:grid-cols-2" data-testid="active-goals">
              {active.map((g) => (
                <GoalCard key={g.id} g={g} onEdit={(x) => setSheet({ open: true, existing: x })} />
              ))}
            </div>
          )}
          {history.length > 0 && (
            <>
              <SectionHeader title="Earlier goals" description="Done, set aside, or their window has passed." />
              <div className="grid gap-3 lg:grid-cols-2" data-testid="goal-history">
                {history.map((g) => (
                  <GoalCard key={g.id} g={g} onEdit={(x) => setSheet({ open: true, existing: x })} />
                ))}
              </div>
            </>
          )}
        </>
      )}
      <GoalSheet open={sheet.open} onOpenChange={(o) => setSheet((s) => ({ ...s, open: o }))} existing={sheet.existing} />
    </div>
  );
}
